"""CAS store for immutable evolution policy versions."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import RLock
from typing import Protocol

from contracts.evolution import EvolutionPolicyVersion


class EvolutionVersionConflict(ValueError):
    pass


class EvolutionStore(Protocol):
    def active(self) -> EvolutionPolicyVersion: ...
    def get(self, version: int) -> EvolutionPolicyVersion: ...
    def list_versions(self) -> list[EvolutionPolicyVersion]: ...
    def create(
        self, value: EvolutionPolicyVersion, *, expected_active: int
    ) -> EvolutionPolicyVersion: ...


class InMemoryEvolutionStore:
    def __init__(self) -> None:
        self._versions = {0: EvolutionPolicyVersion(version=0, policy={})}
        self._active = 0
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

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = [
    "EvolutionStore",
    "EvolutionVersionConflict",
    "InMemoryEvolutionStore",
    "SQLiteEvolutionStore",
]
