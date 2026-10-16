"""Explicit schema for the durable activation journal and formal version head.

Both tables live in the Workflow ledger database next to the planning and
materialization journals. The head row is the single formal GraphVersion
authority for one Run; the journal row is the controlled activation fact.
"""
from contextlib import closing
import sqlite3
from contracts import stable_checksum
from contracts.graph_activation import GraphActivationHead, GraphActivationRecord
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore

TABLES = {
    "graph_activations": """CREATE TABLE graph_activations(
    activation_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL,
    materialization_id TEXT NOT NULL, run_id TEXT NOT NULL, status TEXT NOT NULL,
    payload TEXT NOT NULL, checksum TEXT NOT NULL)""",
    "graph_activation_heads": """CREATE TABLE graph_activation_heads(
    run_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, graph_id TEXT NOT NULL,
    active_graph_version INTEGER NOT NULL, activation_id TEXT NOT NULL UNIQUE)""",
}
INDEXES = {
    "graph_activation_key_unique": "CREATE UNIQUE INDEX graph_activation_key_unique ON graph_activations(idempotency_key)",
    "graph_activation_materialization_unique": "CREATE UNIQUE INDEX graph_activation_materialization_unique ON graph_activations(materialization_id)",
}


def normalized(sql):
    return "".join(sql.lower().split())


class SQLiteGraphActivationStore(SQLiteGraphMaterializationStore):
    @staticmethod
    def _check_schema(conn):
        if [r[0] for r in conn.execute("SELECT version FROM graph_activation_schema")] != [1]:
            raise RuntimeError("unsupported activation schema")
        for name, sql in {**TABLES, **INDEXES}.items():
            row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if not row or normalized(row[0]) != normalized(sql):
                raise RuntimeError("activation schema definition mismatch: " + name)

    @staticmethod
    def upgrade_schema(db_path):
        # Administrative only. Requires the already prepared materialization journal.
        SQLiteGraphMaterializationStore(db_path)
        with closing(sqlite3.connect(str(db_path))) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS graph_activation_schema(version INTEGER PRIMARY KEY)")
            versions = [r[0] for r in conn.execute("SELECT version FROM graph_activation_schema")]
            if versions and versions != [1]:
                raise RuntimeError("unsupported activation schema")
            for name, sql in {**TABLES, **INDEXES}.items():
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                    conn.execute(sql)
            conn.execute("INSERT OR IGNORE INTO graph_activation_schema(version) VALUES(1)")
            SQLiteGraphActivationStore._check_schema(conn)

    def __init__(self, db_path):
        super().__init__(db_path)
        with self.connection() as conn:
            self._check_schema(conn)

    def _activation(self, column, value):
        with self.connection() as conn:
            row = conn.execute(f"SELECT * FROM graph_activations WHERE {column}=?", (value,)).fetchone()
        if row is None:
            return None
        record = GraphActivationRecord.model_validate_json(row["payload"])
        if (stable_checksum(record) != row["checksum"] or record.activation_id != row["activation_id"]
                or record.idempotency_key != row["idempotency_key"]
                or record.materialization_id != row["materialization_id"]
                or record.run_id != row["run_id"] or record.status != row["status"]):
            raise ValueError("activation journal index or content mismatch")
        return record

    def get_activation(self, activation_id):
        return self._activation("activation_id", activation_id)

    def activation_by_key(self, key):
        return self._activation("idempotency_key", key)

    def activation_for(self, materialization_id):
        return self._activation("materialization_id", materialization_id)

    def head(self, run_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM graph_activation_heads WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        head = GraphActivationHead(runId=row["run_id"], missionId=row["mission_id"], graphId=row["graph_id"],
                                   activeGraphVersion=row["active_graph_version"], activationId=row["activation_id"])
        if (head.run_id != row["run_id"] or head.mission_id != row["mission_id"]
                or head.graph_id != row["graph_id"] or head.active_graph_version != row["active_graph_version"]
                or head.activation_id != row["activation_id"]):
            raise ValueError("activation head index mismatch")
        return head

    def _append_activation(self, record):
        record = GraphActivationRecord.model_validate_json(record.model_dump_json(by_alias=True))
        conn = self._local.connection
        conn.execute("INSERT INTO graph_activations VALUES(?,?,?,?,?,?,?)", (
            record.activation_id, record.idempotency_key, record.materialization_id, record.run_id,
            record.status, record.model_dump_json(by_alias=True), stable_checksum(record)))

    def _activate_head(self, record):
        """Promote one journal row to ACTIVATED_PAUSED and upsert the formal head.

        Caller holds the store transaction and has already proved the head CAS
        precondition; the defensive checks here keep corrupt rows from being
        laundered into an activation.
        """
        activated = record.model_copy(update={"status": "ACTIVATED_PAUSED"})
        conn = self._local.connection
        row = conn.execute("SELECT payload FROM graph_activations WHERE activation_id=?",
                           (record.activation_id,)).fetchone()
        current = GraphActivationRecord.model_validate_json(row["payload"]) if row is not None else None
        if current is None or current.status != "ACTIVATION_PREPARED" or current != record:
            raise ValueError("activation journal row cannot be promoted")
        conn.execute("UPDATE graph_activations SET status=?, payload=?, checksum=? WHERE activation_id=?", (
            activated.status, activated.model_dump_json(by_alias=True), stable_checksum(activated),
            activated.activation_id))
        conn.execute("""INSERT INTO graph_activation_heads(run_id, mission_id, graph_id, active_graph_version, activation_id)
            VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET
                mission_id=excluded.mission_id, graph_id=excluded.graph_id,
                active_graph_version=excluded.active_graph_version, activation_id=excluded.activation_id""",
            (activated.run_id, activated.mission_id, activated.graph_id,
             activated.candidate_graph_version, activated.activation_id))
