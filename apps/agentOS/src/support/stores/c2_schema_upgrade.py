"""Administrative C2 upgrade orchestration; never imported by Runtime wiring.

DDL and version ownership remain with the existing stores. Each existing
upgrade commits independently. Inspect again after a crash, then reapply;
there is deliberately no second migration ledger or cross-database COMMIT.
"""
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory

from components.recovery.checkpoint import ACGCheckpointStore
from storage.sqlite import CURRENT_SCHEMA_VERSION, SQLiteV2Storage
from storage.schema import SCHEMA_SQL
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.stores.planning_commit_store import SQLitePlanningCommitStore
from support.stores.planning_commit_store import content_fingerprint
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from support.stores.graph_activation_store import SQLiteGraphActivationStore, validate_activation_run
from contracts.workflow import RuntimeRunRecord
from support.stores.graph_handoff_store import SQLiteGraphHandoffStore, SQLiteStagedGraphCheckpointStore
from support.stores.execution_permit_store import SQLiteExecutionPermitStore
from support.stores.workspace_projection import IDENTITY_SOURCES, RUNTIME_SOURCES, install_revision_triggers


UPGRADERS = (
    SQLitePlanningCommitStore, SQLiteGraphMaterializationStore,
    SQLiteGraphActivationStore, SQLiteGraphHandoffStore, SQLiteExecutionPermitStore,
)
GROUPS = {
    "planning_commit_schema": ("planning_commit_records", "planning_commit_outbox"),
    "graph_materialization_schema": ("graph_materializations",),
    "graph_activation_schema": ("graph_activations", "graph_activation_heads"),
    "graph_execution_permit_schema": ("graph_execution_permits",),
}
C2_TABLES = {*GROUPS, *(name for names in GROUPS.values() for name in names), "graph_handoffs"}
C2_INDEXES = {
    "planning_graph_source_unique", "graph_materialization_key_unique",
    "graph_materialization_source_unique", "graph_activation_key_unique",
    "graph_activation_materialization_unique",
}
TASK_POLICY_UPDATE_TRIGGER = "workspace_revision_task_copilot_permissions_update"
TASK_POLICY_TRIGGER_UPGRADE = "task_copilot_permissions:projection-trigger"


class SchemaUpgradeError(RuntimeError):
    pass


def _normalize(sql):
    sql = re.sub(r"^(CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX|TRIGGER))\s+IF\s+NOT\s+EXISTS\b",
                 r"\1", sql.strip(), flags=re.IGNORECASE)
    # SQL keywords are case-insensitive; CHECK literals and trigger strings
    # are not. Never normalize 'read_only' into the different value 'READ_ONLY'.
    pieces = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`[^`]*`|\[[^\]]*\])", sql)
    return "".join(piece if n % 2 else re.sub(r"\s+", "", piece).lower() for n, piece in enumerate(pieces))


def _objects(conn):
    return {name: (kind, table, _normalize(sql)) for kind, name, table, sql in conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}


def _connect(path, *, readonly=True):
    return closing(sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True))


class _AdministrativeWorkflowStore(SQLiteWorkflowStore):
    @contextmanager
    def _connect(self):
        # Close maintenance connections deterministically, including Windows.
        with closing(super()._connect()) as conn, conn:
            yield conn


def _initialize(role, path):
    """Only for an explicitly declared, completely empty database."""
    if role == "workflow":
        _AdministrativeWorkflowStore(path, enable_mission_semantics=True)
    elif role == "checkpoint":
        store = ACGCheckpointStore(db_path=path)
        store.close()
    else:
        with SQLiteV2Storage(path):
            pass


@lru_cache(maxsize=1)
def _reference():
    """Derive the manifest by running the ORIGINAL initializers/upgraders.

    This operates only on disposable temporary files, closes all connections,
    and avoids duplicating SQL definitions or inventing a global version.
    """
    result = {}
    with TemporaryDirectory(prefix="agentos-c2-schema-") as folder:
        paths = {role: Path(folder) / f"{role}.sqlite" for role in ("workflow", "checkpoint", "identity")}
        for role, path in paths.items():
            _initialize(role, path)
        with _connect(paths["workflow"]) as conn:
            base = set(_objects(conn))
        for factory in UPGRADERS:
            factory.upgrade_schema(paths["workflow"])
        SQLiteStagedGraphCheckpointStore.upgrade_schema(paths["checkpoint"])
        for role, path in paths.items():
            with _connect(path) as conn:
                result[role] = _objects(conn)
        # SQLite's official ADD COLUMN migration places semantic_key last.
        # Accept exactly that migration-produced table, not arbitrary reordered
        # SQL or relaxed constraints. Only disposable reference files are opened
        # by the Identity constructor; existing Identity remains verify-only.
        legacy_path = Path(folder) / "identity_alter.sqlite"
        table = re.search(r"CREATE TABLE IF NOT EXISTS semantic_tasks \(.*?\n\);", SCHEMA_SQL, re.S).group()
        with closing(sqlite3.connect(legacy_path)) as conn:
            conn.execute(table.replace("    semantic_key TEXT,\n", "", 1))
        with SQLiteV2Storage(legacy_path):
            pass
        with _connect(legacy_path) as conn:
            result["identity_alter_semantic_tasks"] = _objects(conn)["semantic_tasks"]
        legacy_policy_path = Path(folder) / "workflow_legacy_policy.sqlite"
        with closing(sqlite3.connect(legacy_policy_path)) as conn:
            conn.execute("""CREATE TABLE task_copilot_permissions (
                mission_id TEXT PRIMARY KEY, permission TEXT NOT NULL
                CHECK(permission IN ('read_only', 'task_collaboration')))""")
            install_revision_triggers(conn, {
                "task_copilot_permissions": RUNTIME_SOURCES["task_copilot_permissions"]})
            result["workflow_legacy_task_operator_policy"] = _objects(conn)["task_copilot_permissions"]
            result["workflow_legacy_task_policy_update_trigger"] = _objects(conn)[TASK_POLICY_UPDATE_TRIGGER]
        result["workflow_base"] = base
    return result


def _paths(workflow, checkpoint, identity):
    result = {}
    for role, value in (("workflow", workflow), ("checkpoint", checkpoint), ("identity", identity)):
        path = Path(value)
        if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
            raise SchemaUpgradeError(f"{role}: absolute, non-symlink database path required")
        path = path.resolve()
        if not path.parent.is_dir() or path.is_dir():
            raise SchemaUpgradeError(f"{role}: existing parent directory and regular file path required")
        if path.exists() and not path.is_file():
            raise SchemaUpgradeError(f"{role}: regular SQLite file required")
        if (not path.exists() or path.stat().st_size == 0) and any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise SchemaUpgradeError(f"{role}: orphan SQLite sidecars require operator investigation")
        for other in result.values():
            if path == other or path.exists() and other.exists() and path.samefile(other):
                raise SchemaUpgradeError("database roles must use distinct files (including hard links)")
        result[role] = path
    return result


def _missing_unique_is_safe(conn, current):
    # Missing indexes are additive only if original uniqueness can be installed.
    checks = {
        "planning_graph_source_unique": ("planning_commit_records", "json_extract(payload,'$.proposalPayload.sourceCommitId')", "json_extract(payload,'$.proposalType')='graph_revision'"),
        "graph_materialization_key_unique": ("graph_materializations", "idempotency_key", "1"),
        "graph_materialization_source_unique": ("graph_materializations", "source_commit_id", "1"),
        "graph_activation_key_unique": ("graph_activations", "idempotency_key", "1"),
        "graph_activation_materialization_unique": ("graph_activations", "materialization_id", "1"),
    }
    for name, (table, field, predicate) in checks.items():
        if name in current or table not in current:
            continue
        # Identifiers/expressions are internal constants, never operator input.
        if conn.execute(f"SELECT 1 FROM {table} WHERE ({predicate}) AND {field} IS NOT NULL "
                        f"GROUP BY {field} HAVING COUNT(*)>1 LIMIT 1").fetchone():
            raise SchemaUpgradeError(f"workflow: historical duplicates prevent {name}; no data was repaired")


def _inspect_one(role, path, reference, initialize_empty):
    if not path.exists() or path.stat().st_size == 0:
        if not initialize_empty:
            raise SchemaUpgradeError(f"{role}: absent/empty database; explicit --initialize-empty required")
        return {"status": "EMPTY_REQUIRES_INITIALIZATION", "missing": sorted(reference), "present": []}
    with _connect(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        target = CURRENT_SCHEMA_VERSION if role == "identity" else 0
        if version != target:
            raise SchemaUpgradeError(f"{role}: unsupported user_version {version}, expected {target}")
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise SchemaUpgradeError(f"{role}: SQLite integrity check failed")
        current = _objects(conn)
        required = (_reference()["workflow_base"] if role == "workflow" else
                    {"acg_execution_checkpoints"} if role == "checkpoint" else set(reference))
        missing_required = set(required) - current.keys()
        legacy_policy = (role == "workflow"
            and current.get("task_copilot_permissions") == _reference()["workflow_legacy_task_operator_policy"]
            and "task_operator_policy_receipts" not in current)
        legacy_policy_trigger = (role == "workflow"
            and current.get(TASK_POLICY_UPDATE_TRIGGER) == _reference()["workflow_legacy_task_policy_update_trigger"]
            and (legacy_policy or current.get("task_copilot_permissions") == reference["task_copilot_permissions"]))
        if legacy_policy:
            missing_required.discard("task_operator_policy_receipts")
        # Projection bookkeeping is an additive extension to existing volumes.
        # Only its wholly absent legacy form is upgradeable: a partially missing
        # installation may have lost durable watermarks and must not be reset.
        projection_objects = {name for name in reference
                              if name == "workspace_projection_versions"
                              or name.startswith("workspace_revision_")}
        if projection_objects and not (projection_objects & current.keys()):
            missing_required -= projection_objects
        legacy_revision = (role == "workflow"
                           and missing_required == {"mission_revision_decisions"}
                           and not (C2_TABLES & current.keys()))
        if legacy_revision:
            # Supported pre-C2 base: the original semantic initializer adds
            # this empty journal. Once any C2 component is installed, a missing
            # prerequisite remains damage and is never recreated.
            missing_required = set()
        if missing_required:
            raise SchemaUpgradeError(f"{role}: missing prerequisite objects: {sorted(missing_required)}")
        for name in current.keys() & reference.keys():
            if current[name] != reference[name]:
                if legacy_policy and name == "task_copilot_permissions":
                    continue
                if legacy_policy_trigger and name == TASK_POLICY_UPDATE_TRIGGER:
                    continue
                if (role == "identity" and name == "semantic_tasks"
                        and current[name] == _reference()["identity_alter_semantic_tasks"]):
                    continue
                raise SchemaUpgradeError(f"{role}: incompatible definition: {name}; no destructive repair")
        if role == "workflow":
            if [r[0] for r in conn.execute("SELECT version FROM mission_semantic_schema")] != [1]:
                raise SchemaUpgradeError("workflow: unsupported Mission semantic schema")
            for marker, tables in GROUPS.items():
                if marker not in current:
                    continue
                versions = [r[0] for r in conn.execute(f"SELECT version FROM {marker}")]
                if versions not in ([], [1]):
                    raise SchemaUpgradeError(f"workflow: unsupported {marker}: {versions}")
                if versions == [1] and not set(tables) <= current.keys():
                    raise SchemaUpgradeError(f"workflow: {marker} declares completion but required tables are missing")
            _missing_unique_is_safe(conn, current)
        if role == "identity" and conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SchemaUpgradeError("identity: existing foreign-key violations; no automatic repair")
        missing = sorted(reference.keys() - current.keys())
        if legacy_policy:
            missing.append("task_copilot_permissions:operator-policy")
        if legacy_policy_trigger:
            missing.append(TASK_POLICY_TRIGGER_UPGRADE)
        if role == "workflow":
            # An interrupted empty marker is supported by the original upgrader.
            missing += [f"{marker}:version=1" for marker in GROUPS if marker in current
                        and not conn.execute(f"SELECT version FROM {marker}").fetchall()]
        result = {"status": "UPGRADE_REQUIRED" if missing else "READY", "user_version": version,
                  "missing": missing, "present": sorted(reference.keys() & current.keys())}
        if role == "workflow":
            result["component_versions"] = {marker: [r[0] for r in conn.execute(f"SELECT version FROM {marker}")]
                                           if marker in current else None
                                           for marker in ("mission_semantic_schema", *GROUPS)}
        return result


def _historical_permit(conn, permit, run, head):
    """Prove an issued fact belongs to the validated Head's activated ancestry."""
    if (head is None or permit.run_id != run.run_id or permit.mission_id != run.mission_id
            or permit.graph_id != head.graph_id or permit.graph_version >= head.active_graph_version):
        return False
    version = head.active_graph_version
    while version >= permit.graph_version:
        rows = conn.execute("""SELECT * FROM graph_activations WHERE run_id=?
            AND status='ACTIVATED_PAUSED' AND json_extract(payload,'$.candidateGraphVersion')=?""",
            (run.run_id, version)).fetchall()
        if len(rows) != 1:
            return False
        activation = SQLiteGraphActivationStore._decode_activation(rows[0])
        if (activation.run_id != run.run_id or activation.mission_id != run.mission_id
                or activation.graph_id != permit.graph_id or activation.candidate_graph_version != version
                or (version == head.active_graph_version and activation.activation_id != head.activation_id)):
            return False
        if version == permit.graph_version:
            return (activation.activation_id == permit.activation_id
                    and activation.package_checksum == permit.package_checksum
                    and activation.source_kind == permit.source_kind)
        if activation.source_graph_version != version - 1:
            return False
        version = activation.source_graph_version
    return False


def _inspect_evidence(paths, result):
    """Check installed evidence dependencies, not current execution authority.

    A STAGING intent may precede its body COMMIT, but its table was installed
    before the Authority could run. STATE_PREPARED and every Permit require
    the immutable body. No missing historical fact may be recreated by DDL.
    These are read-only cross-file checks under the maintenance-window rule,
    not a joint SQLite snapshot or a new Handoff/Permit acceptance authority.
    """
    if result["workflow"]["status"] in {"INVALID", "EMPTY_REQUIRES_INITIALIZATION"}:
        return

    def invalid(role, reason):
        result[role]["status"] = "INVALID"
        result[role]["error"] = f"{role}: missing or inconsistent C2 evidence: {reason}"

    try:
        with _connect(paths["workflow"]) as conn:
            # One read snapshot for Run, Permit, Handoff and formal Head. The
            # existing validator is also used by ordinary Workflow writes; this
            # preflight neither repairs evidence nor grants execution rights.
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "graph_handoffs" not in tables and tables & {"graph_execution_permit_schema", "graph_execution_permits"}:
                invalid("workflow", "graph_handoffs is required by the installed execution Permit schema")
                return
            handoff_ids = [r[0] for r in conn.execute("SELECT handoff_id FROM graph_handoffs")] if "graph_handoffs" in tables else []
            permit_ids = [r[0] for r in conn.execute("SELECT permit_id FROM graph_execution_permits")] if "graph_execution_permits" in tables else []
            # Only opted-in projections are relevant; unrelated legacy rows
            # are not reinterpreted or backfilled by this Schema operation.
            projections = conn.execute("""SELECT run_id, mission_id, payload, json_extract(payload,
                '$.executionState.graphActivation.executionPermit.permitId') FROM runs
                WHERE CASE WHEN json_valid(payload) THEN json_extract(payload,
                '$.executionState.graphActivation') END IS NOT NULL""").fetchall()
            validated_owners = {}
            validated_runs = {}
            for row in projections:
                run_id, mission_id, payload, permit_id = row
                if permit_id is not None and permit_id not in permit_ids:
                    invalid("workflow", f"Run {run_id} references absent Permit {permit_id}")
                    return
                run = RuntimeRunRecord.model_validate_json(payload)
                if run.run_id != run_id or run.mission_id != mission_id:
                    invalid("workflow", f"Run {run_id} payload/index identity mismatch")
                    return
                try:
                    head = validate_activation_run(conn, run)
                    if head is None:
                        raise ValueError("Permit projection has no formal activation Head")
                except ValueError as exc:
                    invalid("workflow", f"Run {run_id} Permit {permit_id}: {exc}")
                    return
                validated_runs[run_id] = (run, head)
                if permit_id is not None:
                    validated_owners.setdefault(permit_id, []).append(run_id)
            # A missing/null Run projection must not hide an already ISSUED
            # fact. Decode every journal row (including its indexed status) in
            # this same read snapshot, then require exactly one owner whose
            # complete chain passed the existing activation validator above.
            # A newer activated graph legitimately replaces that projection;
            # require its complete formal ancestry before retaining history.
            # PREPARING is an incomplete Saga and does not require issuance's
            # Run projection; its existing Handoff checks remain unchanged.
            if "graph_execution_permits" in tables:
                for row in conn.execute("SELECT * FROM graph_execution_permits"):
                    permit = SQLiteExecutionPermitStore._decode(row)
                    owners = validated_owners.get(permit.permit_id, [])
                    if permit.status == "ISSUED" and owners != [permit.run_id]:
                        source = validated_runs.get(permit.run_id)
                        if not owners and source is not None and _historical_permit(conn, permit, *source):
                            continue
                        invalid("workflow", f"ISSUED Permit {permit.permit_id} requires exactly one "
                                f"validated Run {permit.run_id} projection or activated descendant ancestry; found {owners}")
                        return
        if not handoff_ids and not permit_ids:
            return  # Workflow installation may legitimately precede CP DDL.
        handoffs = SQLiteGraphHandoffStore(paths["workflow"])
        records = {key: handoffs.get_handoff(key) for key in handoff_ids}
        if any(record is None for record in records.values()):
            invalid("workflow", "Handoff disappeared during read-only inspection; stop concurrent writers")
            return
        if permit_ids:
            permits = SQLiteExecutionPermitStore(paths["workflow"])
            for key in permit_ids:
                permit = permits.get_permit(key)  # original Contract/checksum/index validation
                if permit is None:
                    invalid("workflow", f"Permit {key} disappeared during inspection")
                    return
                handoff = records.get(permit.handoff_id)
                if (handoff is None or handoff.status != "STATE_PREPARED"
                        or handoff.run_id != permit.run_id or handoff.activation_id != permit.activation_id
                        or handoff.source_kind != permit.source_kind or handoff.graph_version != permit.graph_version
                        or handoff.identity_link.candidate_graph.graph_id != permit.graph_id
                        or handoff.candidate.checkpoint_id != permit.staged_checkpoint_id
                        or handoff.candidate.package_checksum != permit.package_checksum
                        or content_fingerprint(handoff) != permit.handoff_fingerprint
                        or content_fingerprint(handoff.candidate) != permit.staged_checkpoint_fingerprint):
                    invalid("workflow", f"Permit {key} requires intact confirmed Handoff {permit.handoff_id}")
                    return
    except (RuntimeError, ValueError, sqlite3.Error) as exc:
        invalid("workflow", str(exc))
        return
    if result["checkpoint"]["status"] == "INVALID":
        return  # retain the more specific existing Schema error
    if "staged_graph_checkpoints" not in result["checkpoint"].get("present", []):
        invalid("checkpoint", f"staged_graph_checkpoints is required by persisted Handoff {handoff_ids[0]}")
        return
    try:
        stages = SQLiteStagedGraphCheckpointStore(paths["checkpoint"])
        for key, handoff in records.items():
            body = stages.get(handoff.candidate.checkpoint_id)
            if body is None and handoff.status == "STAGING":
                continue  # legal intent-before-external-COMMIT Saga window
            if body != handoff.candidate:
                invalid("checkpoint", f"Handoff {key} requires staged Checkpoint {handoff.candidate.checkpoint_id}")
                return
    except (RuntimeError, ValueError, sqlite3.Error) as exc:
        invalid("checkpoint", str(exc))


def inspect_databases(workflow, checkpoint, identity, *, initialize_empty=False):
    """Read-only target inspection. No constructor runs against existing files."""
    paths = _paths(workflow, checkpoint, identity)
    reference = _reference()
    result = {}
    for role, path in paths.items():
        try:
            result[role] = {"path": str(path), **_inspect_one(role, path, reference[role], initialize_empty)}
        except (SchemaUpgradeError, sqlite3.Error) as exc:
            result[role] = {"path": str(path), "status": "INVALID", "error": str(exc)}
    _inspect_evidence(paths, result)
    return result


def _upgrade_task_policy_trigger(path):
    """Replace only the exact pre-policy trigger, in explicit maintenance.

    The original initializer's IF NOT EXISTS deliberately preserves existing
    triggers. After ADD COLUMN its old UPDATE predicate still sees only the
    original two columns. A separate transaction is resumable: inspection also
    recognizes the new table with this exact old trigger after an interruption.
    """
    with _connect(path, readonly=False) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        current = _objects(conn).get(TASK_POLICY_UPDATE_TRIGGER)
        if current == _reference()["workflow"][TASK_POLICY_UPDATE_TRIGGER]:
            return
        if current != _reference()["workflow_legacy_task_policy_update_trigger"]:
            raise SchemaUpgradeError(f"workflow: incompatible definition: {TASK_POLICY_UPDATE_TRIGGER}; no destructive repair")
        conn.execute(f'DROP TRIGGER "{TASK_POLICY_UPDATE_TRIGGER}"')
        install_revision_triggers(conn, {
            "task_copilot_permissions": RUNTIME_SOURCES["task_copilot_permissions"]})


def upgrade_databases(workflow, checkpoint, identity, *, initialize_empty=False):
    """Explicit maintenance operation, with all-file preflight before any write.

    Must run while application workers are stopped. Existing individual SQLite
    transactions provide per-stage atomicity, not all-file or all-stage atomicity.
    Any error leaves durable completed stages intact; inspect and rerun.
    """
    paths = _paths(workflow, checkpoint, identity)
    before = inspect_databases(**paths, initialize_empty=initialize_empty)
    invalid = {role: item for role, item in before.items() if item["status"] == "INVALID"}
    if invalid:
        raise SchemaUpgradeError(f"preflight rejected before target writes: {invalid}")
    for role, path in paths.items():
        # Check again immediately before acting on this file, including file
        # contents: never initialize a file populated since the preflight.
        state = _inspect_one(role, path, _reference()[role], initialize_empty)
        if state["status"] == "EMPTY_REQUIRES_INITIALIZATION":
            _initialize(role, path)
        if "workspace_projection_versions" in state["missing"]:
            with _connect(path, readonly=False) as conn, conn:
                install_revision_triggers(conn, IDENTITY_SOURCES if role == "identity" else RUNTIME_SOURCES)
        if role == "workflow":
            if ("mission_revision_decisions" in state["missing"]
                    or "task_copilot_permissions:operator-policy" in state["missing"]):
                _AdministrativeWorkflowStore(path, enable_mission_semantics=True)
            if ("task_copilot_permissions:operator-policy" in state["missing"]
                    or TASK_POLICY_TRIGGER_UPGRADE in state["missing"]):
                _upgrade_task_policy_trigger(path)
            for factory in UPGRADERS:
                _inspect_one(role, path, _reference()[role], False)
                factory.upgrade_schema(path)
        elif role == "checkpoint":
            SQLiteStagedGraphCheckpointStore.upgrade_schema(path)
        # Existing Identity is deliberately NEVER passed to SQLiteV2Storage;
        # only the explicitly checked additive projection extension is installed.
    after = inspect_databases(**paths)
    if any(item["status"] != "READY" for item in after.values()):
        raise SchemaUpgradeError(f"upgrade incomplete; inspect and rerun: {after}")
    return {"status": "READY", "before": before, "after": after}
