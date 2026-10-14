"""Explicitly upgraded planning ledger in the existing Workflow SQLite database.

Constructor never creates a database or upgrades a schema. Acceptance writes only
the ledger and its outbox, not TaskPlan identity tables, Run, graph or receipts.
"""
from contextlib import contextmanager, closing
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock, local

from contracts.planning_commit import PlanningCommitRecord
from contracts.planning import TaskPlan, TaskPlanPatch


def content_fingerprint(model):
    return hashlib.sha256(json.dumps(model.model_dump(mode="json", by_alias=True),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class SQLitePlanningCommitStore:
    requires_durable_payload = True

    @staticmethod
    def upgrade_schema(db_path):
        """Explicit administrative operation; tests call it only on temporary DBs."""
        with closing(sqlite3.connect(str(db_path))) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS planning_commit_schema(version INTEGER PRIMARY KEY)")
            versions = [r[0] for r in conn.execute("SELECT version FROM planning_commit_schema")]
            if versions and versions != [1]:
                raise RuntimeError("unsupported planning commit schema")
            conn.execute("""CREATE TABLE IF NOT EXISTS planning_commit_records(
                commit_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, revision INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                UNIQUE(mission_id, revision))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS planning_commit_outbox(
                commit_id TEXT PRIMARY KEY, payload TEXT NOT NULL)""")
            conn.execute("INSERT OR IGNORE INTO planning_commit_schema(version) VALUES(1)")
            conn.commit()

    def __init__(self, db_path):
        self.db_path = Path(db_path).resolve()
        self._lock = RLock()
        self._local = local()
        with self.connection() as conn:
            if [r[0] for r in conn.execute("SELECT version FROM planning_commit_schema")] != [1]:
                raise RuntimeError("planning schema requires explicit upgrade")
            for table in ("planning_commit_records", "planning_commit_outbox"):
                conn.execute(f"SELECT 1 FROM {table} LIMIT 0")

    def _connect(self):
        conn = sqlite3.connect(self.db_path.as_uri() + "?mode=rw", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _transaction(self):
        with self._lock:
            if getattr(self._local, "connection", None) is not None:
                raise RuntimeError("reentrant durable acceptance is unsupported")
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._local.connection = conn
                yield
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                self._local.connection = None
                conn.close()

    @contextmanager
    def connection(self):
        current = getattr(self._local, "connection", None)
        if current is not None:
            yield current
        else:
            conn = self._connect()
            try:
                yield conn
            finally:
                conn.close()

    def _one(self, sql, params):
        with self._lock, self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            if not row:
                return None
            record = PlanningCommitRecord.model_validate_json(row["payload"])
            if (record.commit_id != row["commit_id"] or record.mission_id != row["mission_id"]
                    or record.commitment_revision != row["revision"]):
                raise ValueError("planning ledger index and content disagree")
            return record

    def get(self, commit_id):
        return self._one("SELECT * FROM planning_commit_records WHERE commit_id=?", (commit_id,))

    def get_by_idempotency_key(self, key):
        return self._one("SELECT * FROM planning_commit_records WHERE idempotency_key=?", (key,))

    def latest(self, mission_id):
        return self._one("SELECT * FROM planning_commit_records WHERE mission_id=? ORDER BY revision DESC LIMIT 1",
                         (mission_id,))

    def _append(self, key, record):
        record = PlanningCommitRecord.model_validate_json(record.model_dump_json(by_alias=True))
        payload = record.proposal_payload
        if payload is None or content_fingerprint(payload) != record.proposal_fingerprint:
            raise ValueError("durable candidate does not match its fingerprint")
        if payload.mission_id != record.mission_id:
            raise ValueError("candidate belongs to another Mission")
        if ((record.proposal_type == "initial_plan" and not isinstance(payload, TaskPlan))
                or (record.proposal_type == "plan_revision" and not isinstance(payload, TaskPlanPatch))
                or record.proposal_type not in {"initial_plan", "plan_revision"}):
            raise ValueError("unsupported durable proposal kind")
        conn = self._local.connection
        conn.execute("INSERT INTO planning_commit_records VALUES(?,?,?,?,?)", (
            record.commit_id, record.mission_id, record.commitment_revision, key,
            record.model_dump_json(by_alias=True)))
        conn.execute("INSERT INTO planning_commit_outbox VALUES(?,?)", (record.commit_id,
            json.dumps({"eventType": "planning.commit.accepted", "commitId": record.commit_id,
                        "missionId": record.mission_id, "commitmentRevision": record.commitment_revision,
                        "materializationStatus": record.materialization_status}, sort_keys=True)))

    def _rollback_append(self, key, record, parent):
        conn = self._local.connection
        conn.execute("DELETE FROM planning_commit_outbox WHERE commit_id=?", (record.commit_id,))
        conn.execute("DELETE FROM planning_commit_records WHERE commit_id=?", (record.commit_id,))

    def pending_events(self):
        with self.connection() as conn:
            return tuple(json.loads(r[0]) for r in conn.execute("SELECT payload FROM planning_commit_outbox ORDER BY rowid"))
