"""Durable evolution artifacts and atomic approval, version, pointer and receipt writes."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import RLock

from contracts.evolution import (
    EvolutionPolicyVersion, EvolutionProposal, EvolutionPublicationReceipt,
    Trajectory, TrajectoryEvaluation,
)
from components.evolution.domain.policy import publication_receipt, require_replay, require_transition
from components.evolution.ports.store import EvolutionVersionConflict


class SQLiteEvolutionStore:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._connection:
            self._connection.execute("CREATE TABLE IF NOT EXISTS evolution_policy_versions (version INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            self._connection.execute("CREATE TABLE IF NOT EXISTS evolution_policy_state (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), active_version INTEGER NOT NULL)")
            self._connection.execute("INSERT OR IGNORE INTO evolution_policy_versions(version, payload) VALUES (?, ?)",
                                     (0, EvolutionPolicyVersion(version=0, policy={}).model_dump_json(by_alias=True)))
            self._connection.execute("INSERT OR IGNORE INTO evolution_policy_state(singleton, active_version) VALUES (1, 0)")
            for table, key in (("evolution_trajectories", "trajectory_id"),
                               ("evolution_evaluations", "trajectory_id"),
                               ("evolution_proposals", "proposal_id"),
                               ("evolution_publication_receipts", "proposal_id")):
                self._connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({key} TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def _transaction(self):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def active(self) -> EvolutionPolicyVersion:
        with self._lock:
            row = self._connection.execute("""SELECT v.payload FROM evolution_policy_state AS s
                JOIN evolution_policy_versions AS v ON v.version = s.active_version
                WHERE s.singleton = 1""").fetchone()
            if row is None:
                raise RuntimeError("evolution active pointer is missing")
            return EvolutionPolicyVersion.model_validate_json(row["payload"])

    def get(self, version: int) -> EvolutionPolicyVersion:
        with self._lock:
            row = self._connection.execute("SELECT payload FROM evolution_policy_versions WHERE version = ?", (version,)).fetchone()
            if row is None:
                raise KeyError(f"unknown evolution policy version: {version}")
            return EvolutionPolicyVersion.model_validate_json(row["payload"])

    def list_versions(self) -> list[EvolutionPolicyVersion]:
        with self._lock:
            rows = self._connection.execute("SELECT payload FROM evolution_policy_versions ORDER BY version").fetchall()
            return [EvolutionPolicyVersion.model_validate_json(row["payload"]) for row in rows]

    def _check_version(self, value, expected_active):
        current = self.active()
        if current.version != expected_active or value.base_version != expected_active:
            raise EvolutionVersionConflict(f"expected active evolution version {expected_active}, current {current.version}")
        if value.version != current.version + 1:
            raise EvolutionVersionConflict(f"invalid next evolution version: {value.version}")
        return current

    def _insert_version(self, value, current):
        previous = current.model_copy(update={"status": "superseded"})
        self._connection.execute("UPDATE evolution_policy_versions SET payload = ? WHERE version = ?",
                                 (previous.model_dump_json(by_alias=True), current.version))
        self._connection.execute("INSERT INTO evolution_policy_versions(version, payload) VALUES (?, ?)",
                                 (value.version, value.model_dump_json(by_alias=True)))
        self._connection.execute("UPDATE evolution_policy_state SET active_version = ? WHERE singleton = 1", (value.version,))

    def create(self, value: EvolutionPolicyVersion, *, expected_active: int) -> EvolutionPolicyVersion:
        with self._transaction():
            current = self._check_version(value, expected_active)
            self._insert_version(value, current)
        return value.model_copy(deep=True)

    def commit_approval(self, value: EvolutionPolicyVersion, proposal: EvolutionProposal,
                        *, expected_active: int) -> EvolutionPublicationReceipt:
        with self._transaction():
            try:
                receipt = self.get_receipt(proposal.proposal_id)
            except KeyError:
                receipt = None
            if receipt is not None:
                require_replay(receipt, proposal, proposal.reviewed_by)
                return receipt
            current = self._check_version(value, expected_active)
            pending = self.get_proposal(proposal.proposal_id)
            receipt = publication_receipt(current, pending, proposal, value,
                [self.get_evaluation(key) for key in pending.trajectory_ids])
            self._insert_version(value, current)
            self._connection.execute("UPDATE evolution_proposals SET payload = ? WHERE proposal_id = ?",
                (proposal.model_dump_json(by_alias=True), proposal.proposal_id))
            self._connection.execute("INSERT INTO evolution_publication_receipts(proposal_id, payload) VALUES (?, ?)",
                (proposal.proposal_id, receipt.model_dump_json(by_alias=True)))
        return receipt

    def get_receipt(self, proposal_id: str) -> EvolutionPublicationReceipt:
        return EvolutionPublicationReceipt.model_validate_json(
            self._get_json("evolution_publication_receipts", "proposal_id", proposal_id, "publication receipt"))

    def save_trajectory(self, value: Trajectory) -> Trajectory:
        return self._save_immutable("evolution_trajectories", "trajectory_id", value.trajectory_id, value)

    def get_trajectory(self, trajectory_id: str) -> Trajectory:
        return Trajectory.model_validate_json(self._get_json("evolution_trajectories", "trajectory_id", trajectory_id, "trajectory"))

    def save_evaluation(self, value: TrajectoryEvaluation) -> TrajectoryEvaluation:
        return self._save_immutable("evolution_evaluations", "trajectory_id", value.trajectory_id, value)

    def get_evaluation(self, trajectory_id: str) -> TrajectoryEvaluation:
        return TrajectoryEvaluation.model_validate_json(self._get_json("evolution_evaluations", "trajectory_id", trajectory_id, "evaluation"))

    def save_proposal(self, value: EvolutionProposal) -> EvolutionProposal:
        with self._transaction():
            try:
                existing = self.get_proposal(value.proposal_id)
            except KeyError:
                existing = None
            try:
                require_transition(existing, value)
            except ValueError as exc:
                raise EvolutionVersionConflict(str(exc)) from exc
            if existing is None:
                self._connection.execute("INSERT INTO evolution_proposals(proposal_id, payload) VALUES (?, ?)",
                                         (value.proposal_id, value.model_dump_json(by_alias=True)))
            elif existing != value:
                self._connection.execute("UPDATE evolution_proposals SET payload = ? WHERE proposal_id = ?",
                                         (value.model_dump_json(by_alias=True), value.proposal_id))
        return value.model_copy(deep=True)

    def get_proposal(self, proposal_id: str) -> EvolutionProposal:
        return EvolutionProposal.model_validate_json(self._get_json("evolution_proposals", "proposal_id", proposal_id, "proposal"))

    def _save_immutable(self, table, key_name, key, value):
        payload = value.model_dump_json(by_alias=True)
        with self._transaction():
            row = self._connection.execute(f"SELECT payload FROM {table} WHERE {key_name} = ?", (key,)).fetchone()
            if row is not None:
                if type(value).model_validate_json(row["payload"]) != value:
                    raise EvolutionVersionConflict(f"{key} already exists with different content")
            else:
                self._connection.execute(f"INSERT INTO {table}({key_name}, payload) VALUES (?, ?)", (key, payload))
        return value.model_copy(deep=True)

    def _get_json(self, table, key_name, key, kind):
        with self._lock:
            row = self._connection.execute(f"SELECT payload FROM {table} WHERE {key_name} = ?", (key,)).fetchone()
            if row is None:
                raise KeyError(f"unknown evolution {kind}: {key}")
            return str(row["payload"])

    def close(self) -> None:
        with self._lock:
            self._connection.close()
