"""Persistent reference-only communication primitives for advanced ACG modes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal, Protocol


class CommunicationBackpressureError(RuntimeError):
    pass


class BlackboardConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReliableMessage:
    message_id: str
    run_id: str
    producer_step_id: str
    consumer_step_id: str
    artifact_ref: str
    correlation_id: str
    causation_id: str | None
    sequence: int
    schema_hash: str
    status: Literal["pending", "acked"] = "pending"

    def payload_hash(self) -> str:
        payload = {
            "runId": self.run_id,
            "producerStepId": self.producer_step_id,
            "consumerStepId": self.consumer_step_id,
            "artifactRef": self.artifact_ref,
            "correlationId": self.correlation_id,
            "causationId": self.causation_id,
            "sequence": self.sequence,
            "schemaHash": self.schema_hash,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ReliableCommunicationStore(Protocol):
    def publish(self, message: ReliableMessage, *, backlog_limit: int) -> ReliableMessage: ...
    def pending(self, *, run_id: str, consumer_step_id: str, limit: int = 100) -> tuple[ReliableMessage, ...]: ...
    def acknowledge(self, *, run_id: str, message_id: str) -> ReliableMessage: ...
    def blackboard_snapshot(self, *, run_id: str, partition: str) -> tuple[int, dict[str, str]]: ...
    def blackboard_write(self, *, run_id: str, partition: str, key: str, artifact_ref: str, expected_version: int, append: bool = False) -> int: ...


class SQLiteReliableCommunicationStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def publish(self, message: ReliableMessage, *, backlog_limit: int = 1000) -> ReliableMessage:
        if backlog_limit < 1:
            raise ValueError("backlog_limit must be positive")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_hash, status FROM communication_messages WHERE message_id = ?",
                (message.message_id,),
            ).fetchone()
            if row is not None:
                if str(row[0]) != message.payload_hash():
                    raise ValueError(f"message id payload conflict: {message.message_id}")
                return ReliableMessage(**{**message.__dict__, "status": str(row[1])})
            backlog = conn.execute(
                "SELECT COUNT(*) FROM communication_messages WHERE run_id = ? AND consumer_step_id = ? AND status = 'pending'",
                (message.run_id, message.consumer_step_id),
            ).fetchone()[0]
            if int(backlog) >= backlog_limit:
                raise CommunicationBackpressureError("communication backlog limit reached")
            conn.execute(
                """INSERT INTO communication_messages(
                    message_id, run_id, producer_step_id, consumer_step_id, artifact_ref,
                    correlation_id, causation_id, sequence, schema_hash, payload_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    message.message_id, message.run_id, message.producer_step_id,
                    message.consumer_step_id, message.artifact_ref, message.correlation_id,
                    message.causation_id, message.sequence, message.schema_hash,
                    message.payload_hash(), datetime.now(timezone.utc).isoformat(),
                ),
            )
            return message

    def pending(self, *, run_id: str, consumer_step_id: str, limit: int = 100) -> tuple[ReliableMessage, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT message_id, run_id, producer_step_id, consumer_step_id, artifact_ref,
                          correlation_id, causation_id, sequence, schema_hash, status
                   FROM communication_messages
                   WHERE run_id = ? AND consumer_step_id = ? AND status = 'pending'
                   ORDER BY sequence, message_id LIMIT ?""",
                (run_id, consumer_step_id, max(1, limit)),
            ).fetchall()
        return tuple(ReliableMessage(*row) for row in rows)

    def acknowledge(self, *, run_id: str, message_id: str) -> ReliableMessage:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT message_id, run_id, producer_step_id, consumer_step_id, artifact_ref,
                          correlation_id, causation_id, sequence, schema_hash, status
                   FROM communication_messages WHERE message_id = ?""",
                (message_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"communication message not found: {message_id}")
            message = ReliableMessage(*row)
            if message.run_id != run_id:
                raise PermissionError("communication message belongs to another run")
            conn.execute(
                "UPDATE communication_messages SET status = 'acked', acked_at = ? WHERE message_id = ?",
                (datetime.now(timezone.utc).isoformat(), message_id),
            )
            return ReliableMessage(**{**message.__dict__, "status": "acked"})

    def blackboard_snapshot(self, *, run_id: str, partition: str) -> tuple[int, dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT entry_key, artifact_ref, version FROM blackboard_entries
                   WHERE run_id = ? AND partition_id = ? ORDER BY entry_key, version""",
                (run_id, partition),
            ).fetchall()
        latest: dict[str, tuple[int, str]] = {}
        for key, artifact_ref, version in rows:
            latest[str(key)] = (int(version), str(artifact_ref))
        version = max((item[0] for item in latest.values()), default=0)
        return version, {key: item[1] for key, item in latest.items()}

    def blackboard_write(self, *, run_id: str, partition: str, key: str, artifact_ref: str, expected_version: int, append: bool = False) -> int:
        with self._connect() as conn:
            current = conn.execute(
                "SELECT MAX(version) FROM blackboard_entries WHERE run_id = ? AND partition_id = ?",
                (run_id, partition),
            ).fetchone()[0]
            current_version = int(current or 0)
            if current_version != expected_version:
                raise BlackboardConflictError(
                    f"blackboard version conflict: expected={expected_version}, actual={current_version}"
                )
            if not append and conn.execute(
                "SELECT 1 FROM blackboard_entries WHERE run_id = ? AND partition_id = ? AND entry_key = ?",
                (run_id, partition, key),
            ).fetchone() is not None:
                raise BlackboardConflictError(f"blackboard key already exists: {key}")
            next_version = current_version + 1
            conn.execute(
                """INSERT INTO blackboard_entries(run_id, partition_id, entry_key, version, artifact_ref, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, partition, key, next_version, artifact_ref, datetime.now(timezone.utc).isoformat()),
            )
            return next_version

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS communication_messages (
                    message_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    producer_step_id TEXT NOT NULL, consumer_step_id TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL, correlation_id TEXT NOT NULL,
                    causation_id TEXT, sequence INTEGER NOT NULL, schema_hash TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    acked_at TEXT
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS blackboard_entries (
                    run_id TEXT NOT NULL, partition_id TEXT NOT NULL, entry_key TEXT NOT NULL,
                    version INTEGER NOT NULL, artifact_ref TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, partition_id, version)
                )"""
            )

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


@dataclass(frozen=True)
class DebateSpec:
    participant_step_ids: tuple[str, ...]
    max_rounds: int
    quorum: int

    def __post_init__(self) -> None:
        if self.max_rounds < 1 or self.quorum < 1 or self.quorum > len(self.participant_step_ids):
            raise ValueError("debate must be bounded and quorum must fit participants")


class DebateCoordinator:
    """Reference-only propose/critique/vote round state machine."""

    phases = ("propose", "critique", "vote")

    def __init__(self, spec: DebateSpec) -> None:
        self.spec = spec
        self.round = 1
        self.phase = "propose"
        self._submissions: dict[tuple[int, str], dict[str, str]] = {}

    def submit(self, *, participant_step_id: str, artifact_ref: str) -> None:
        if participant_step_id not in self.spec.participant_step_ids:
            raise PermissionError("debate participant is not declared")
        key = (self.round, self.phase)
        submissions = self._submissions.setdefault(key, {})
        existing = submissions.get(participant_step_id)
        if existing is not None and existing != artifact_ref:
            raise ValueError("debate submission is immutable")
        submissions[participant_step_id] = artifact_ref

    def advance(self) -> tuple[int, str]:
        submissions = self._submissions.get((self.round, self.phase), {})
        if len(submissions) < self.spec.quorum:
            raise RuntimeError("DEBATE_QUORUM_UNREACHED")
        index = self.phases.index(self.phase)
        if index < len(self.phases) - 1:
            self.phase = self.phases[index + 1]
        elif self.round < self.spec.max_rounds:
            self.round += 1
            self.phase = "propose"
        else:
            self.phase = "complete"
        return self.round, self.phase


__all__ = [
    "BlackboardConflictError", "CommunicationBackpressureError", "DebateCoordinator",
    "DebateSpec", "ReliableCommunicationStore", "ReliableMessage",
    "SQLiteReliableCommunicationStore",
]
