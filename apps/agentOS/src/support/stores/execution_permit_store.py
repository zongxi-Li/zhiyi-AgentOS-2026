"""Explicitly upgraded Workflow ledger for execution permits."""

from contextlib import closing
import sqlite3

from contracts import stable_checksum
from contracts.execution_permit import ExecutionPermitRecord
from support.stores.graph_handoff_store import SQLiteGraphHandoffStore, schema


PERMIT_SQL = """CREATE TABLE graph_execution_permits(
    permit_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    handoff_id TEXT NOT NULL UNIQUE, activation_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
    checksum TEXT NOT NULL)"""
PERMIT_SCHEMA_SQL = "CREATE TABLE graph_execution_permit_schema(version INTEGER PRIMARY KEY)"


def _check_schema(conn):
    versions = [row[0] for row in conn.execute("SELECT version FROM graph_execution_permit_schema")]
    if versions != [1]:
        raise RuntimeError("unsupported execution permit schema")
    schema(conn, "graph_execution_permits", PERMIT_SQL)


class SQLiteExecutionPermitStore(SQLiteGraphHandoffStore):
    """Permit journal co-located with activation and handoff authority.

    The constructor is read-only with respect to schema. Runtime assembly must
    attach a store explicitly upgraded by an administrative/test operation.
    """

    @staticmethod
    def upgrade_schema(db_path):
        SQLiteGraphHandoffStore(db_path)
        with closing(sqlite3.connect(str(db_path))) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(PERMIT_SCHEMA_SQL.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
            versions = [row[0] for row in conn.execute("SELECT version FROM graph_execution_permit_schema")]
            if versions and versions != [1]:
                raise RuntimeError("unsupported execution permit schema")
            schema(conn, "graph_execution_permits", PERMIT_SQL, upgrade=True)
            conn.execute("INSERT OR IGNORE INTO graph_execution_permit_schema(version) VALUES(1)")
            _check_schema(conn)

    def __init__(self, db_path):
        super().__init__(db_path)
        with self.connection() as conn:
            _check_schema(conn)

    @staticmethod
    def _decode(row):
        record = ExecutionPermitRecord.model_validate_json(row["payload"])
        if (record.permit_id != row["permit_id"]
                or record.idempotency_key != row["idempotency_key"]
                or record.handoff_id != row["handoff_id"]
                or record.activation_id != row["activation_id"]
                or record.run_id != row["run_id"]
                or record.status != row["status"]
                or stable_checksum(record) != row["checksum"]):
            raise ValueError("execution permit index or checksum mismatch")
        return record

    def _read(self, column, value):
        if column not in {"permit_id", "idempotency_key", "handoff_id", "activation_id", "run_id"}:
            raise ValueError("unsupported permit lookup")
        with self.connection() as conn:
            _check_schema(conn)
            row = conn.execute(f"SELECT * FROM graph_execution_permits WHERE {column}=?", (value,)).fetchone()
        return self._decode(row) if row else None

    def get_permit(self, permit_id):
        return self._read("permit_id", permit_id)

    def permit_by_key(self, key):
        return self._read("idempotency_key", key)

    def permit_for_handoff(self, handoff_id):
        return self._read("handoff_id", handoff_id)

    def permit_for_activation(self, activation_id):
        return self._read("activation_id", activation_id)

    def permit_for_run(self, run_id):
        return self._read("run_id", run_id)

    def _append_preparing(self, record):
        if record.status != "PREPARING":
            raise ValueError("new permit must start in PREPARING")
        _check_schema(self._local.connection)
        self._local.connection.execute("INSERT INTO graph_execution_permits VALUES(?,?,?,?,?,?,?,?)", (
            record.permit_id, record.idempotency_key, record.handoff_id,
            record.activation_id, record.run_id, record.status,
            record.model_dump_json(by_alias=True), stable_checksum(record)))

    def _issue(self, expected):
        conn = self._local.connection
        _check_schema(conn)
        row = conn.execute("SELECT * FROM graph_execution_permits WHERE permit_id=?", (expected.permit_id,)).fetchone()
        current = self._decode(row) if row else None
        if current != expected or current.status != "PREPARING":
            raise ValueError("only the unchanged PREPARING permit can be issued")
        issued = current.model_copy(update={"status": "ISSUED"})
        result = conn.execute("UPDATE graph_execution_permits SET status=?,payload=?,checksum=? "
                              "WHERE permit_id=? AND status='PREPARING' AND checksum=?", (
            issued.status, issued.model_dump_json(by_alias=True), stable_checksum(issued),
            issued.permit_id, stable_checksum(current)))
        if result.rowcount != 1:
            raise ValueError("execution permit issuance lost its compare-and-swap")
        return issued


__all__ = ["SQLiteExecutionPermitStore"]
