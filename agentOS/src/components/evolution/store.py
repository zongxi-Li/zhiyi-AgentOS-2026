"""CAS store for immutable evolution policy versions."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import RLock
from typing import Protocol

from contracts.evolution import (
    EvolutionPolicyVersion,
    EvolutionProposal,
    EvolutionProposalStatus,
    Trajectory,
    TrajectoryEvaluation,
)


class EvolutionVersionConflict(ValueError):
    pass


class EvolutionStore(Protocol):
    def active(self) -> EvolutionPolicyVersion: ...
    def get(self, version: int) -> EvolutionPolicyVersion: ...
    def list_versions(self) -> list[EvolutionPolicyVersion]: ...
    def create(
        self, value: EvolutionPolicyVersion, *, expected_active: int
    ) -> EvolutionPolicyVersion: ...
    def save_trajectory(self, value: Trajectory) -> Trajectory: ...
    def get_trajectory(self, trajectory_id: str) -> Trajectory: ...
    def save_evaluation(self, value: TrajectoryEvaluation) -> TrajectoryEvaluation: ...
    def get_evaluation(self, trajectory_id: str) -> TrajectoryEvaluation: ...
    def save_proposal(self, value: EvolutionProposal) -> EvolutionProposal: ...
    def get_proposal(self, proposal_id: str) -> EvolutionProposal: ...


class InMemoryEvolutionStore:
    def __init__(self) -> None:
        self._versions = {0: EvolutionPolicyVersion(version=0, policy={})}
        self._active = 0
        self._trajectories: dict[str, Trajectory] = {}
        self._evaluations: dict[str, TrajectoryEvaluation] = {}
        self._proposals: dict[str, EvolutionProposal] = {}
        self._lock = RLock()

    def active(self) -> EvolutionPolicyVersion:
        return self._versions[self._active].model_copy(deep=True)

    def get(self, version: int) -> EvolutionPolicyVersion:
        try:
            return self._versions[version].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"unknown evolution policy version: {version}") from exc

    def list_versions(self) -> list[EvolutionPolicyVersion]:
        return [self._versions[key].model_copy(deep=True) for key in sorted(self._versions)]

    def create(self, value: EvolutionPolicyVersion, *, expected_active: int) -> EvolutionPolicyVersion:
        with self._lock:
            if expected_active != self._active or value.base_version != expected_active:
                raise EvolutionVersionConflict(
                    f"expected active evolution version {expected_active}, current {self._active}"
                )
            if value.version in self._versions or value.version != self._active + 1:
                raise EvolutionVersionConflict(f"invalid next evolution version: {value.version}")
            previous = self._versions[self._active]
            self._versions[self._active] = previous.model_copy(update={"status": "superseded"})
            self._versions[value.version] = value.model_copy(deep=True)
            self._active = value.version
            return value.model_copy(deep=True)

    def save_trajectory(self, value: Trajectory) -> Trajectory:
        return self._save_immutable(self._trajectories, value.trajectory_id, value)

    def get_trajectory(self, trajectory_id: str) -> Trajectory:
        return self._get(self._trajectories, trajectory_id, "trajectory")

    def save_evaluation(self, value: TrajectoryEvaluation) -> TrajectoryEvaluation:
        return self._save_immutable(self._evaluations, value.trajectory_id, value)

    def get_evaluation(self, trajectory_id: str) -> TrajectoryEvaluation:
        return self._get(self._evaluations, trajectory_id, "evaluation")

    def save_proposal(self, value: EvolutionProposal) -> EvolutionProposal:
        with self._lock:
            existing = self._proposals.get(value.proposal_id)
            self._validate_proposal_transition(existing, value)
            self._proposals[value.proposal_id] = value.model_copy(deep=True)
            return value.model_copy(deep=True)

    def get_proposal(self, proposal_id: str) -> EvolutionProposal:
        return self._get(self._proposals, proposal_id, "proposal")

    def _save_immutable(self, values, key: str, value):
        with self._lock:
            existing = values.get(key)
            if existing is not None and existing != value:
                raise EvolutionVersionConflict(f"{key} already exists with different content")
            values[key] = value.model_copy(deep=True)
            return value.model_copy(deep=True)

    def _get(self, values, key: str, kind: str):
        try:
            return values[key].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"unknown evolution {kind}: {key}") from exc

    @staticmethod
    def _validate_proposal_transition(existing, value: EvolutionProposal) -> None:
        if existing is None or existing == value:
            return
        if existing.model_copy(update={"status": value.status, "reviewed_by": value.reviewed_by, "reviewed_at": value.reviewed_at}) != value:
            raise EvolutionVersionConflict("proposal content cannot change after validation")
        if existing.status is not EvolutionProposalStatus.PENDING_REVIEW or value.status not in {
            EvolutionProposalStatus.APPROVED,
            EvolutionProposalStatus.REJECTED,
        }:
            raise EvolutionVersionConflict("invalid evolution proposal status transition")


class SQLiteEvolutionStore:
    """Durable immutable policy versions with a transactional active pointer."""

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evolution_policy_versions (
                    version INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evolution_policy_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    active_version INTEGER NOT NULL
                )
                """
            )
            initial = EvolutionPolicyVersion(version=0, policy={})
            self._connection.execute(
                "INSERT OR IGNORE INTO evolution_policy_versions(version, payload) VALUES (?, ?)",
                (0, initial.model_dump_json(by_alias=True)),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO evolution_policy_state(singleton, active_version) VALUES (1, 0)"
            )
            for table, key_name in (
                ("evolution_trajectories", "trajectory_id"),
                ("evolution_evaluations", "trajectory_id"),
                ("evolution_proposals", "proposal_id"),
            ):
                self._connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ({key_name} TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )

    def active(self) -> EvolutionPolicyVersion:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT versions.payload
                FROM evolution_policy_state AS state
                JOIN evolution_policy_versions AS versions
                  ON versions.version = state.active_version
                WHERE state.singleton = 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("evolution active pointer is missing")
        return EvolutionPolicyVersion.model_validate_json(row["payload"])

    def get(self, version: int) -> EvolutionPolicyVersion:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM evolution_policy_versions WHERE version = ?",
                (version,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown evolution policy version: {version}")
        return EvolutionPolicyVersion.model_validate_json(row["payload"])

    def list_versions(self) -> list[EvolutionPolicyVersion]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM evolution_policy_versions ORDER BY version"
            ).fetchall()
        return [EvolutionPolicyVersion.model_validate_json(row["payload"]) for row in rows]

    def create(self, value: EvolutionPolicyVersion, *, expected_active: int) -> EvolutionPolicyVersion:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                state = self._connection.execute(
                    "SELECT active_version FROM evolution_policy_state WHERE singleton = 1"
                ).fetchone()
                current = int(state["active_version"]) if state is not None else -1
                if current != expected_active or value.base_version != expected_active:
                    raise EvolutionVersionConflict(
                        f"expected active evolution version {expected_active}, current {current}"
                    )
                if value.version != current + 1:
                    raise EvolutionVersionConflict(f"invalid next evolution version: {value.version}")
                duplicate = self._connection.execute(
                    "SELECT 1 FROM evolution_policy_versions WHERE version = ?", (value.version,)
                ).fetchone()
                if duplicate is not None:
                    raise EvolutionVersionConflict(f"invalid next evolution version: {value.version}")
                previous = self.get(current).model_copy(update={"status": "superseded"})
                self._connection.execute(
                    "UPDATE evolution_policy_versions SET payload = ? WHERE version = ?",
                    (previous.model_dump_json(by_alias=True), current),
                )
                self._connection.execute(
                    "INSERT INTO evolution_policy_versions(version, payload) VALUES (?, ?)",
                    (value.version, value.model_dump_json(by_alias=True)),
                )
                self._connection.execute(
                    "UPDATE evolution_policy_state SET active_version = ? WHERE singleton = 1",
                    (value.version,),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return value.model_copy(deep=True)

    def save_trajectory(self, value: Trajectory) -> Trajectory:
        return self._save_json("evolution_trajectories", "trajectory_id", value.trajectory_id, value, immutable=True)

    def get_trajectory(self, trajectory_id: str) -> Trajectory:
        return Trajectory.model_validate_json(
            self._get_json("evolution_trajectories", "trajectory_id", trajectory_id, "trajectory")
        )

    def save_evaluation(self, value: TrajectoryEvaluation) -> TrajectoryEvaluation:
        return self._save_json("evolution_evaluations", "trajectory_id", value.trajectory_id, value, immutable=True)

    def get_evaluation(self, trajectory_id: str) -> TrajectoryEvaluation:
        return TrajectoryEvaluation.model_validate_json(
            self._get_json("evolution_evaluations", "trajectory_id", trajectory_id, "evaluation")
        )

    def save_proposal(self, value: EvolutionProposal) -> EvolutionProposal:
        with self._lock:
            try:
                existing = self.get_proposal(value.proposal_id)
            except KeyError:
                existing = None
            InMemoryEvolutionStore._validate_proposal_transition(existing, value)
            return self._save_json(
                "evolution_proposals",
                "proposal_id",
                value.proposal_id,
                value,
                immutable=False,
            )

    def get_proposal(self, proposal_id: str) -> EvolutionProposal:
        return EvolutionProposal.model_validate_json(
            self._get_json("evolution_proposals", "proposal_id", proposal_id, "proposal")
        )

    def _save_json(self, table: str, key_name: str, key: str, value, *, immutable: bool):
        payload = value.model_dump_json(by_alias=True)
        with self._lock:
            row = self._connection.execute(
                f"SELECT payload FROM {table} WHERE {key_name} = ?", (key,)
            ).fetchone()
            if row is not None and immutable and str(row["payload"]) != payload:
                raise EvolutionVersionConflict(f"{key} already exists with different content")
            self._connection.execute(
                f"INSERT OR REPLACE INTO {table}({key_name}, payload) VALUES (?, ?)",
                (key, payload),
            )
            self._connection.commit()
        return value.model_copy(deep=True)

    def _get_json(self, table: str, key_name: str, key: str, kind: str) -> str:
        with self._lock:
            row = self._connection.execute(
                f"SELECT payload FROM {table} WHERE {key_name} = ?", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown evolution {kind}: {key}")
        return str(row["payload"])

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = [
    "EvolutionStore",
    "EvolutionVersionConflict",
    "InMemoryEvolutionStore",
    "SQLiteEvolutionStore",
]
