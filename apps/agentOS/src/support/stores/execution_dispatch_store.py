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
    """Explicitly upgraded Workflow DB; one immutable execution command per Run."""
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
            return self.decode(conn.execute("SELECT * FROM execution_dispatch_commands WHERE run_id=?", (run_id,)).fetchone())

    def commands(self):
        with self.connection() as conn:
            self.check_schema(conn)
            return [self.decode(row) for row in conn.execute("SELECT * FROM execution_dispatch_commands ORDER BY rowid")]

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
