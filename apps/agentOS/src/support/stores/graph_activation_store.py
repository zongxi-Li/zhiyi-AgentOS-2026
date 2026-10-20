"""Explicit schema for the durable activation journal and formal version head.

Both tables live in the Workflow ledger database next to the planning and
materialization journals. The head row is the single formal GraphVersion
authority for one Run; the journal row is the controlled activation fact.
"""
from contextlib import closing
import sqlite3
from contracts import stable_checksum
from contracts.graph_activation import GraphActivationHead, GraphActivationRecord
from contracts.graph_activation import activation_projection
from contracts.graph_materialization import GraphMaterializationRecord
from contracts.compiled_acg import load_compiled_acg_package
from contracts.execution_permit import ExecutionPermitRecord, execution_permit_projection
from contracts.graph_handoff import GraphHandoffRecord
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from support.stores.planning_commit_store import content_fingerprint

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


def _issued_permit(conn, projection, activation, materialization):
    """Load and cross-check the immutable permit chain in the caller snapshot."""
    if not isinstance(projection, dict) or not isinstance(projection.get("permitId"), str):
        raise ValueError("execution permit projection is malformed")
    try:
        row = conn.execute("SELECT * FROM graph_execution_permits WHERE permit_id=?",
                           (projection["permitId"],)).fetchone()
        if row is None:
            raise ValueError("execution permit record is missing")
        permit = ExecutionPermitRecord.model_validate_json(row["payload"])
        if (permit.permit_id != row["permit_id"] or permit.idempotency_key != row["idempotency_key"]
                or permit.handoff_id != row["handoff_id"] or permit.activation_id != row["activation_id"]
                or permit.run_id != row["run_id"] or permit.status != row["status"]
                or stable_checksum(permit) != row["checksum"]):
            raise ValueError("execution permit row index or checksum mismatch")
        handoff_row = conn.execute("SELECT * FROM graph_handoffs WHERE handoff_id=?", (permit.handoff_id,)).fetchone()
        if handoff_row is None:
            raise ValueError("permit handoff record is missing")
        handoff = GraphHandoffRecord.model_validate_json(handoff_row["payload"])
        if (stable_checksum(handoff) != handoff_row["checksum"] or handoff.status != "STATE_PREPARED"
                or handoff.handoff_id != permit.handoff_id or handoff.activation_id != permit.activation_id
                or handoff.run_id != permit.run_id or content_fingerprint(handoff) != permit.handoff_fingerprint
                or stable_checksum(handoff.candidate) != handoff.candidate_fingerprint
                or handoff.candidate.checkpoint_id != permit.staged_checkpoint_id
                or handoff.candidate.package_checksum != permit.package_checksum
                or handoff.graph_version != permit.graph_version):
            raise ValueError("permit does not match its confirmed handoff")
        if (permit.status != "ISSUED" or permit.activation_id != activation.activation_id
                or permit.run_id != activation.run_id or permit.mission_id != activation.mission_id
                or permit.graph_id != activation.graph_id or permit.graph_version != activation.candidate_graph_version
                or permit.package_checksum != materialization.package_checksum):
            raise ValueError("execution permit is not issued for the formal activation head")
        if projection != execution_permit_projection(permit):
            raise ValueError("Run permit projection differs from durable permit")
        return permit
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise ValueError("workflow run conflicts with the durable execution permit") from exc


def validate_activation_run(conn, run):
    """Validate the durable head chain using the caller's SQLite snapshot.

    Ordinary writes call this inside BEGIN IMMEDIATE; reconciliation and the
    execution gate use one read transaction. No registry, compiler or cache is
    consulted. A missing legacy schema is compatible only without an activation
    projection. Once a head exists, missing evidence is always an error.
    """
    def invalid():
        raise ValueError("workflow run conflicts with the durable activation head")

    try:
        row = conn.execute("SELECT * FROM graph_activation_heads WHERE run_id=?", (run.run_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table: graph_activation_heads" not in str(exc):
            raise
        row = None
    if row is None:
        if "graphActivation" in run.execution_state:
            invalid()
        # A stale pre-activation snapshot must not erase the last durable
        # marker when a previously installed Head/schema has been lost.
        previous = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run.run_id,)).fetchone()
        if previous is not None:
            from contracts.workflow import RuntimeRunRecord
            if "graphActivation" in RuntimeRunRecord.model_validate_json(previous["payload"]).execution_state:
                invalid()
        return None
    try:
        head = GraphActivationHead(runId=row["run_id"], missionId=row["mission_id"], graphId=row["graph_id"],
                                   activeGraphVersion=row["active_graph_version"], activationId=row["activation_id"])
        row = conn.execute("SELECT * FROM graph_activations WHERE activation_id=?", (head.activation_id,)).fetchone()
        if row is None:
            invalid()
        record = SQLiteGraphActivationStore._decode_activation(row)
        row = conn.execute("SELECT * FROM graph_materializations WHERE materialization_id=?",
                           (record.materialization_id,)).fetchone()
        if row is None:
            invalid()
        materialization = GraphMaterializationRecord.model_validate_json(row["payload"])
        if (stable_checksum(materialization) != row["checksum"]
                or materialization.materialization_id != row["materialization_id"]
                or materialization.idempotency_key != row["idempotency_key"]
                or materialization.source_commit_id != row["source_commit_id"]):
            invalid()
        if (record.status != "ACTIVATED_PAUSED"
                or not (run.run_id == head.run_id == record.run_id == materialization.source_run_id)
                or not (run.mission_id == head.mission_id == record.mission_id == materialization.mission_id)
                or not (head.graph_id == record.graph_id == materialization.graph_id)
                or not (head.active_graph_version == record.candidate_graph_version == materialization.candidate_graph_version)
                or record.source_graph_version != materialization.source_graph_version
                or record.source_commit_id != materialization.source_commit_id
                or record.package_checksum != materialization.package_checksum
                or record.commitment_fingerprint != materialization.commitment_fingerprint
                or record.proof_fingerprint != materialization.proof_fingerprint):
            invalid()
        state, package = run.execution_state, materialization.package
        if (stable_checksum(run.acg_blueprint) != package.blueprint_hash
                or state.get("graphId") != head.graph_id
                or type(state.get("graphVersion")) is not int
                or state["graphVersion"] != head.active_graph_version
                or load_compiled_acg_package(state.get("compiledACGPackage")) != package
                or any(state.get(key) != value for key, value in {
                    "compiledPackageId": package.package_id, "compiledPackageChecksum": package.checksum,
                    "compiledPackageBlueprintHash": package.blueprint_hash,
                    "compiledPackageVersion": package.package_version}.items())):
            invalid()
        # Pin the checkpoint to the already-persisted projection on ordinary
        # writes. On the first v1->v2 write the old Run still owns its v1 head.
        old = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run.run_id,)).fetchone()
        from contracts.workflow import RuntimeRunRecord
        previous = RuntimeRunRecord.model_validate_json(old["payload"]) if old is not None else None
        if previous is None:
            invalid()
        previous_projection = previous.execution_state.get("graphActivation")
        checkpoint = (previous_projection.get("supersededCheckpointId")
                      if isinstance(previous_projection, dict) and previous_projection.get("activationId") == record.activation_id
                      else previous.execution_state.get("checkpointId"))
        projection = state.get("graphActivation")
        if not isinstance(projection, dict):
            invalid()
        permit_projection = projection.get("executionPermit")
        expected_projection = activation_projection(record, superseded_checkpoint_id=checkpoint)
        if permit_projection is None:
            if projection != expected_projection:
                invalid()
            if isinstance(previous_projection, dict) and previous_projection.get("activationId") == record.activation_id:
                if previous_projection.get("executionPermit") is not None:
                    invalid()
                # ACTIVATED_PAUSED remains immutable until the permit authority
                # installs its durable ISSUED record and exact Run transition.
                if (run.execution_state != previous.execution_state
                        or run.steps != previous.steps
                        or run.execution_scope != previous.execution_scope
                        or run.workflow_id != previous.workflow_id
                        or run.domain != previous.domain
                        or run.runtime_engine != previous.runtime_engine
                        or run.completed_step_ids != previous.completed_step_ids
                        or run.active_step_ids != previous.active_step_ids
                        or run.current_step_id != previous.current_step_id
                        or (run.status.value in {"completed", "superseded"} and run.status != previous.status)):
                    invalid()
        else:
            permit = _issued_permit(conn, permit_projection, record, materialization)
            expected_projection["executionPermit"] = execution_permit_projection(permit)
            if projection != expected_projection:
                invalid()
            if previous_projection is None or previous_projection.get("activationId") != record.activation_id:
                invalid()
            previous_permit = previous_projection.get("executionPermit")
            if previous_permit is None:
                if content_fingerprint(previous) != permit.source_run_fingerprint:
                    invalid()
                if (run.execution_state.get("executionPermitId") != permit.permit_id
                        or run.execution_state.get("executionGeneration") != permit.attempt_generation
                        or run.execution_state.get("checkpointId") != permit.promoted_checkpoint_id):
                    invalid()
                expected = previous.model_copy(deep=True)
                expected_projection_state = dict(expected.execution_state["graphActivation"])
                expected_projection_state["executionPermit"] = execution_permit_projection(permit)
                expected.execution_state.update({
                    "graphActivation": expected_projection_state,
                    "executionPermitId": permit.permit_id,
                    "executionGeneration": permit.attempt_generation,
                    "checkpointId": permit.promoted_checkpoint_id,
                })
                expected.runtime_revision = run.runtime_revision
                expected.updated_at = run.updated_at
                if expected != run:
                    invalid()
            else:
                if (previous_permit != execution_permit_projection(permit)
                        or run.execution_state.get("executionPermitId") != permit.permit_id
                        or run.execution_state.get("executionGeneration") != permit.attempt_generation):
                    invalid()
        if (type(projection.get("activeGraphVersion")) is not int
                or type(projection.get("sourceGraphVersion")) is not int):
            invalid()
        return head
    except (ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        raise ValueError("workflow run conflicts with the durable activation head") from exc


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
        return self._decode_activation(row)

    @staticmethod
    def _decode_activation(row):
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
