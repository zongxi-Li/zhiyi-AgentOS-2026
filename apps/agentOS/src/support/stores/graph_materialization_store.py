"""Explicit schema, single-transaction inactive journal in the Workflow ledger DB."""
from contextlib import closing
import sqlite3
from contracts import stable_checksum
from contracts.graph_materialization import GraphMaterializationRecord
from support.stores.planning_commit_store import SQLitePlanningCommitStore


TABLE_SQL = """CREATE TABLE graph_materializations(
    materialization_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL,
    source_commit_id TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)"""
INDEXES = {
    "graph_materialization_key_unique": "CREATE UNIQUE INDEX graph_materialization_key_unique ON graph_materializations(idempotency_key)",
    "graph_materialization_source_unique": "CREATE UNIQUE INDEX graph_materialization_source_unique ON graph_materializations(source_commit_id)",
}


def normalized(sql):
    return "".join(sql.lower().split())


class SQLiteGraphMaterializationStore(SQLitePlanningCommitStore):
    @staticmethod
    def _check_schema(conn):
        if [r[0] for r in conn.execute("SELECT version FROM graph_materialization_schema")] != [1]:
            raise RuntimeError("unsupported materialization schema")
        for name, sql in {"graph_materializations": TABLE_SQL, **INDEXES}.items():
            row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if not row or normalized(row[0]) != normalized(sql):
                raise RuntimeError("materialization schema definition mismatch: " + name)

    @staticmethod
    def upgrade_schema(db_path):
        # Administrative only. Requires the already prepared Planning ledger.
        SQLitePlanningCommitStore(db_path)
        with closing(sqlite3.connect(str(db_path))) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS graph_materialization_schema(version INTEGER PRIMARY KEY)")
            versions = [r[0] for r in conn.execute("SELECT version FROM graph_materialization_schema")]
            if versions and versions != [1]:
                raise RuntimeError("unsupported materialization schema")
            for name, sql in {"graph_materializations": TABLE_SQL, **INDEXES}.items():
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                    conn.execute(sql)
            conn.execute("INSERT OR IGNORE INTO graph_materialization_schema(version) VALUES(1)")
            SQLiteGraphMaterializationStore._check_schema(conn)

    def __init__(self, db_path):
        super().__init__(db_path)
        with self.connection() as conn:
            self._check_schema(conn)

    def _materialization(self, column, value):
        with self.connection() as conn:
            row = conn.execute(f"SELECT * FROM graph_materializations WHERE {column}=?", (value,)).fetchone()
        if row is None:
            return None
        record = GraphMaterializationRecord.model_validate_json(row["payload"])
        if (stable_checksum(record) != row["checksum"] or record.materialization_id != row["materialization_id"]
                or record.idempotency_key != row["idempotency_key"] or record.source_commit_id != row["source_commit_id"]):
            raise ValueError("materialization journal index or content mismatch")
        return record

    def get_materialization(self, materialization_id):
        return self._materialization("materialization_id", materialization_id)

    def materialization_by_key(self, key):
        return self._materialization("idempotency_key", key)

    def materialization_for(self, commit_id):
        return self._materialization("source_commit_id", commit_id)

    def _append_materialization(self, record):
        record = GraphMaterializationRecord.model_validate_json(record.model_dump_json(by_alias=True))
        self._local.connection.execute("INSERT INTO graph_materializations VALUES(?,?,?,?,?)", (
            record.materialization_id, record.idempotency_key, record.source_commit_id,
            record.model_dump_json(by_alias=True), stable_checksum(record)))
