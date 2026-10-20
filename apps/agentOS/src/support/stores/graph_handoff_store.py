"""Explicitly upgraded Workflow handoff ledger and separate staged checkpoint rows.

Neither store writes acg_execution_checkpoints, Run, Head, Identity or an outbox.
The external stage can be orphaned safely; only Workflow confirmation is a
handoff decision. It is still not a checkpoint recovery head or a permit.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
from contracts import stable_checksum
from contracts.graph_handoff import GraphHandoffRecord, StagedGraphCheckpoint
from support.stores.graph_activation_store import SQLiteGraphActivationStore, normalized

HANDOFF_SQL = """CREATE TABLE graph_handoffs(
    handoff_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    activation_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, status TEXT NOT NULL,
    payload TEXT NOT NULL, checksum TEXT NOT NULL)"""
STAGE_SQL = """CREATE TABLE staged_graph_checkpoints(
    checkpoint_id TEXT PRIMARY KEY, handoff_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)"""


def schema(conn, name, sql, *, upgrade=False):
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
    if row is None and upgrade:
        conn.execute(sql)
    elif row is None or normalized(row[0]) != normalized(sql):
        raise RuntimeError("explicit handoff schema upgrade required: " + name)


class SQLiteGraphHandoffStore(SQLiteGraphActivationStore):
    @staticmethod
    def upgrade_schema(db_path):
        SQLiteGraphActivationStore(db_path)
        with closing(sqlite3.connect(str(db_path))) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            schema(conn, "graph_handoffs", HANDOFF_SQL, upgrade=True)

    def __init__(self, db_path):
        super().__init__(db_path)
        with self.connection() as conn:
            schema(conn, "graph_handoffs", HANDOFF_SQL)

    def _read_handoff(self, column, value):
        with self.connection() as conn:
            schema(conn, "graph_handoffs", HANDOFF_SQL)
            row = conn.execute(f"SELECT * FROM graph_handoffs WHERE {column}=?", (value,)).fetchone()
        if row is None:
            return None
        record = GraphHandoffRecord.model_validate_json(row["payload"])
        if (record.handoff_id != row["handoff_id"] or record.idempotency_key != row["idempotency_key"]
                or record.activation_id != row["activation_id"] or record.run_id != row["run_id"]
                or record.status != row["status"] or stable_checksum(record) != row["checksum"]
                or stable_checksum(record.candidate) != record.candidate_fingerprint):
            raise ValueError("handoff index or checksum mismatch")
        return record

    def get_handoff(self, handoff_id):
        return self._read_handoff("handoff_id", handoff_id)

    def handoff_by_key(self, key):
        return self._read_handoff("idempotency_key", key)

    def handoff_for(self, activation_id):
        return self._read_handoff("activation_id", activation_id)

    def _append_handoff(self, record):
        self._local.connection.execute("INSERT INTO graph_handoffs VALUES(?,?,?,?,?,?,?)", (
            record.handoff_id, record.idempotency_key, record.activation_id, record.run_id,
            record.status, record.model_dump_json(by_alias=True), stable_checksum(record)))

    def _confirm_handoff(self, record):
        if self.get_handoff(record.handoff_id) != record or record.status != "STAGING":
            raise ValueError("handoff intent changed")
        confirmed = record.model_copy(update={"status": "STATE_PREPARED"})
        self._local.connection.execute("UPDATE graph_handoffs SET status=?,payload=?,checksum=? WHERE handoff_id=?", (
            confirmed.status, confirmed.model_dump_json(by_alias=True), stable_checksum(confirmed), record.handoff_id))
        return confirmed


class SQLiteStagedGraphCheckpointStore:
    @staticmethod
    def upgrade_schema(db_path):
        # Explicit admin operation on an EXISTING checkpoint DB, never a runtime migration.
        path = Path(db_path).resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            schema(conn, "staged_graph_checkpoints", STAGE_SQL, upgrade=True)

    def __init__(self, db_path):
        self.db_path = Path(db_path).resolve()
        with self.connection() as conn:
            schema(conn, "staged_graph_checkpoints", STAGE_SQL)

    def connection(self):
        return closing(sqlite3.connect(self.db_path.as_uri() + "?mode=rw", uri=True, timeout=5))

    def get(self, checkpoint_id):
        with self.connection() as conn:
            schema(conn, "staged_graph_checkpoints", STAGE_SQL)
            row = conn.execute("SELECT * FROM staged_graph_checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        if row is None:
            return None
        record = StagedGraphCheckpoint.model_validate_json(row[3])
        if (record.checkpoint_id != row[0] or record.handoff_id != row[1]
                or record.run_id != row[2] or stable_checksum(record) != row[4]):
            raise ValueError("staged checkpoint index or content mismatch")
        return record

    def stage(self, record):
        record = StagedGraphCheckpoint.model_validate_json(record.model_dump_json(by_alias=True))
        with self.connection() as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            schema(conn, "staged_graph_checkpoints", STAGE_SQL)
            row = conn.execute("SELECT payload,checksum FROM staged_graph_checkpoints WHERE checkpoint_id=? OR handoff_id=?",
                               (record.checkpoint_id, record.handoff_id)).fetchone()
            if row:
                if row[0] != record.model_dump_json(by_alias=True) or row[1] != stable_checksum(record):
                    raise ValueError("staged checkpoint conflict")
            else:
                conn.execute("INSERT INTO staged_graph_checkpoints VALUES(?,?,?,?,?)", (
                    record.checkpoint_id, record.handoff_id, record.run_id,
                    record.model_dump_json(by_alias=True), stable_checksum(record)))
