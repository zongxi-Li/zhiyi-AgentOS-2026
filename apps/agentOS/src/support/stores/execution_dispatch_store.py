"""Immutable dispatch admission facts, not an execution or recovery state machine."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from contracts import stable_checksum
from contracts.workflow import RuntimeRunRecord
from support.stores.execution_permit_store import SQLiteExecutionPermitStore


SCHEMA = "CREATE TABLE execution_dispatch_schema(version INTEGER PRIMARY KEY)"
TABLE = """CREATE TABLE execution_dispatch_commands(
run_id TEXT PRIMARY KEY, operation_key TEXT NOT NULL UNIQUE,
payload TEXT NOT NULL, checksum TEXT NOT NULL)"""
CONTINUATIONS = """CREATE TABLE execution_dispatch_continuations(
run_id TEXT NOT NULL, graph_version INTEGER NOT NULL,
operation_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, checksum TEXT NOT NULL,
PRIMARY KEY(run_id, graph_version))"""


class DispatchConflict(ValueError):
    pass


class DispatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["execution-dispatch-v1"] = "execution-dispatch-v1"
    dispatch_id: str
    operation_key: str
    request_fingerprint: str
    mission_id: str
    run_id: str
    permit_id: str
    graph_id: str
    graph_version: int = Field(ge=1)
    runtime_revision: int = Field(ge=0)
    actor_id: str
    tenant_id: str
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def public(self, replay=False):
        return {"dispatchId": self.dispatch_id, "runId": self.run_id, "permitId": self.permit_id,
                "graphVersion": self.graph_version, "status": "IDEMPOTENT_REPLAY" if replay else "ACCEPTED"}


class SQLiteExecutionDispatchStore:
    """Immutable initial admission and its formally permitted graph continuations."""
    def __init__(self, db_path):
        self.db_path = Path(db_path).resolve()
        SQLiteExecutionPermitStore(self.db_path)
        with self.connection() as conn:
            self.check_schema(conn)

    def connection(self):
        conn = sqlite3.connect(self.db_path.as_uri() + "?mode=rw", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    @staticmethod
    def check_schema(conn):
        if [r[0] for r in conn.execute("SELECT version FROM execution_dispatch_schema")] != [1]:
            raise RuntimeError("explicit Dispatch schema version 1 is required")
        for name, sql in (("execution_dispatch_schema", SCHEMA), ("execution_dispatch_commands", TABLE)):
            row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if not row or "".join(row[0].lower().split()) != "".join(sql.lower().split()):
                raise RuntimeError("Dispatch schema definition mismatch")
        continuation = conn.execute("SELECT sql FROM sqlite_master WHERE name='execution_dispatch_continuations'").fetchone()
        if continuation and "".join(continuation[0].lower().split()) != "".join(CONTINUATIONS.lower().split()):
            raise RuntimeError("Dispatch continuation schema definition mismatch")

    @staticmethod
    def upgrade_schema(db_path):
        """Administrative only; requires existing C2 ledgers, never called at startup."""
        path = Path(db_path).resolve()
        SQLiteExecutionPermitStore(path)
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            for name, sql in (("execution_dispatch_schema", SCHEMA), ("execution_dispatch_commands", TABLE)):
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                    conn.execute(sql)
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='execution_dispatch_continuations'").fetchone():
                conn.execute(CONTINUATIONS)
            conn.execute("INSERT OR IGNORE INTO execution_dispatch_schema VALUES(1)")
            SQLiteExecutionDispatchStore.check_schema(conn)

    @staticmethod
    def decode(row):
        if row is None:
            return None
        command = DispatchCommand.model_validate_json(row["payload"])
        if (command.run_id != row["run_id"] or command.operation_key != row["operation_key"]
                or stable_checksum(command) != row["checksum"]):
            raise ValueError("Dispatch record integrity failure")
        return command

    def get(self, run_id):
        with self.connection() as conn:
            self.check_schema(conn)
            return self._latest(conn, run_id)

    @classmethod
    def _latest(cls, conn, run_id):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='execution_dispatch_continuations'").fetchone():
            row = conn.execute("SELECT * FROM execution_dispatch_continuations WHERE run_id=? ORDER BY graph_version DESC LIMIT 1", (run_id,)).fetchone()
            if row is not None:
                command = cls.decode(row)
                if command.graph_version != row["graph_version"]:
                    raise ValueError("Dispatch continuation graph integrity failure")
                return command
        return cls.decode(conn.execute("SELECT * FROM execution_dispatch_commands WHERE run_id=?", (run_id,)).fetchone())

    def assert_admitted(self, conn, run, principal):
        """Bind an accepted fact to the caller's fenced Workflow snapshot."""
        self.check_schema(conn)
        command = self._latest(conn, run.run_id)
        state = run.execution_state
        if (command is None or principal is None or command.mission_id != run.mission_id
                or command.permit_id != state.get("executionPermitId")
                or command.graph_id != state.get("graphId") or command.graph_version != state.get("graphVersion")
                or command.runtime_revision > run.runtime_revision
                or command.actor_id != principal.actor_id or command.tenant_id != principal.tenant_id):
            raise ValueError("Dispatch admission is missing or differs from the formal Run/Permit/Graph/principal")
        return command

    def commands(self):
        with self.connection() as conn:
            self.check_schema(conn)
            return [self._latest(conn, row[0]) for row in conn.execute("SELECT run_id FROM execution_dispatch_commands ORDER BY rowid")]

    def accept_continuation(self, command, parent, validate):
        """Append admission for one next graph; retain the original task authorization.

        The caller holds the same Run/OS fence as initial admission. A current
        formal Permit and live semantic authorization are checked by validate.
        No checkpoint, graph, permission or execution result is created here.
        """
        with self.connection() as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self.check_schema(conn)
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='execution_dispatch_continuations'").fetchone():
                raise DispatchConflict("Explicit Dispatch continuation schema upgrade required")
            latest = self._latest(conn, command.run_id)
            if latest is not None and latest.graph_version == command.graph_version:
                if any(getattr(latest, key) != getattr(command, key) for key in (
                        "dispatch_id", "operation_key", "request_fingerprint", "mission_id", "run_id", "permit_id",
                        "graph_id", "graph_version", "runtime_revision", "actor_id", "tenant_id")):
                    raise DispatchConflict("Graph already has another Dispatch continuation")
                return latest, True
            if (latest != parent or parent is None
                    or command.graph_version != parent.graph_version + 1
                    or command.permit_id == parent.permit_id
                    or any(getattr(command, key) != getattr(parent, key)
                           for key in ("mission_id", "run_id", "graph_id", "actor_id", "tenant_id"))):
                raise DispatchConflict("Dispatch continuation does not extend the authorized graph lineage")
            row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (command.run_id,)).fetchone()
            run = RuntimeRunRecord.model_validate_json(row[0]) if row else None
            if (run is None or run.mission_id != command.mission_id
                    or run.execution_state.get("graphId") != command.graph_id
                    or run.execution_state.get("graphVersion") != command.graph_version
                    or run.execution_state.get("executionPermitId") != command.permit_id
                    or run.runtime_revision != command.runtime_revision):
                raise DispatchConflict("Dispatch continuation differs from the formal Run/Permit")
            validate(run)
            conn.execute("INSERT INTO execution_dispatch_continuations VALUES(?,?,?,?,?)", (
                command.run_id, command.graph_version, command.operation_key,
                command.model_dump_json(), stable_checksum(command)))
            return command, False

    def accept(self, command, validate):
        with self.connection() as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self.check_schema(conn)
            old = self.decode(conn.execute("SELECT * FROM execution_dispatch_commands WHERE run_id=?", (command.run_id,)).fetchone())
            if old:
                if old.operation_key != command.operation_key or old.request_fingerprint != command.request_fingerprint:
                    raise DispatchConflict("Run already has another Dispatch command")
                return old, True
            row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (command.run_id,)).fetchone()
            run = RuntimeRunRecord.model_validate_json(row[0]) if row else None
            # The callback is the existing live authority gate, under the same
            # Run/OS fence and Workflow write boundary, not a copied Permit check.
            validate(run)
            conn.execute("INSERT INTO execution_dispatch_commands VALUES(?,?,?,?)", (
                command.run_id, command.operation_key, command.model_dump_json(), stable_checksum(command)))
            return command, False
