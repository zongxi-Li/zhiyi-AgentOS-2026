"""Real temporary SQLite administrative upgrade, refusal and restart evidence."""
from contextlib import closing
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys

import pytest

from support.stores import c2_schema_upgrade as ops


ROOT = Path(__file__).resolve().parents[4]
CLI = ROOT / "scripts" / "upgrade_agentos_c2_schema.py"


@pytest.fixture
def paths(tmp_path):
    return {role: tmp_path / f"{role}.sqlite" for role in ("workflow", "checkpoint", "identity")}


def base(paths):
    for role, path in paths.items():
        ops._initialize(role, path)


def sql(path, statement, parameters=()):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys=ON")
        return conn.execute(statement, parameters).fetchall()


def contents(paths):
    result = {}
    for role, path in paths.items():
        if path.exists():
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                result[role] = tuple(conn.iterdump())
        else:
            result[role] = None
    return result


def checked(paths):
    result = ops.inspect_databases(**paths)
    assert {item["status"] for item in result.values()} == {"READY"}, result
    return result


def test_new_databases_require_explicit_initialization_and_upgrade(paths):
    with pytest.raises(ops.SchemaUpgradeError, match="preflight rejected"):
        ops.upgrade_databases(**paths)
    assert not any(path.exists() for path in paths.values())
    result = ops.upgrade_databases(**paths, initialize_empty=True)
    assert result["status"] == "READY"
    checked(paths)
    assert sql(paths["identity"], "PRAGMA user_version") == [(3,)]
    for marker in ops.GROUPS:
        assert sql(paths["workflow"], f"SELECT version FROM {marker}") == [(1,)]
    for table in ops.C2_TABLES - set(ops.GROUPS):
        assert sql(paths["workflow"], f"SELECT count(*) FROM {table}") == [(0,)]
    assert sql(paths["checkpoint"], "SELECT count(*) FROM acg_execution_checkpoints") == [(0,)]
    assert sql(paths["checkpoint"], "SELECT count(*) FROM staged_graph_checkpoints") == [(0,)]


def test_compatible_upgrade_preserves_data_indexes_triggers_and_repeat(paths):
    base(paths)
    sql(paths["workflow"], "INSERT INTO tasks VALUES(?,?,?)", ("mission_keep", '{"preserve":"任务"}', "2026-10-22"))
    sql(paths["workflow"], "CREATE TRIGGER user_keep_task BEFORE DELETE ON tasks BEGIN SELECT RAISE(ABORT,'keep'); END")
    sql(paths["checkpoint"], "INSERT INTO acg_execution_checkpoints(thread_id,checkpoint_id,state_json) VALUES('old','cp','{}')")
    sql(paths["identity"], "INSERT INTO missions(mission_id,user_id,goal,status,created_at,updated_at) VALUES('m','u','keep','created','now','now')")
    identity_before = paths["identity"].read_bytes()
    old = contents(paths)
    preflight = ops.inspect_databases(**paths)
    assert len(preflight["workflow"]["missing"]) == 16  # 11 tables, five explicit indexes
    assert preflight["checkpoint"]["missing"] == ["staged_graph_checkpoints"]
    assert preflight["identity"]["status"] == "READY"
    assert ops.upgrade_databases(**paths)["status"] == "READY"
    assert paths["identity"].read_bytes() == identity_before
    upgraded = contents(paths)
    for role in paths:
        assert set(old[role]) - {"BEGIN TRANSACTION;", "COMMIT;"} <= set(upgraded[role])
    assert ops.upgrade_databases(**paths)["status"] == "READY"
    assert contents(paths) == upgraded
    with pytest.raises(sqlite3.IntegrityError, match="keep"):
        sql(paths["workflow"], "DELETE FROM tasks")


@pytest.mark.parametrize("role,version", [("workflow", 8), ("checkpoint", 1), ("identity", 4), ("identity", 2)])
def test_incompatible_version_rejects_all_targets_before_writes(paths, role, version):
    base(paths)
    sql(paths[role], f"PRAGMA user_version={version}")
    before = contents(paths)
    with pytest.raises(ops.SchemaUpgradeError, match="unsupported user_version"):
        ops.upgrade_databases(**paths, initialize_empty=True)
    assert contents(paths) == before


@pytest.mark.parametrize("marker", ["mission_semantic_schema", *ops.GROUPS])
def test_incompatible_component_marker_rejected(paths, marker):
    ops.upgrade_databases(**paths, initialize_empty=True)
    sql(paths["workflow"], f"UPDATE {marker} SET version=9")
    before = contents(paths)
    with pytest.raises(ops.SchemaUpgradeError, match="unsupported"):
        ops.upgrade_databases(**paths)
    assert contents(paths) == before


@pytest.mark.parametrize("role,object_name", [("workflow", "runs"), ("workflow", "mission_semantic_state"), ("checkpoint", "acg_execution_checkpoints"), ("identity", "attempts_require_same_mission")])
def test_missing_prerequisites_never_repaired(paths, role, object_name):
    base(paths)
    kind = "TRIGGER" if object_name.endswith("same_mission") else "TABLE"
    sql(paths[role], f"DROP {kind} {object_name}")
    before = contents(paths)
    with pytest.raises(ops.SchemaUpgradeError, match="missing prerequisite"):
        ops.upgrade_databases(**paths)
    assert contents(paths) == before


@pytest.mark.parametrize("fault", ["wrong_index", "wrong_table", "wrong_trigger", "complete_but_missing_table"])
def test_malformed_schema_refused_without_destructive_repair(paths, fault):
    ops.upgrade_databases(**paths, initialize_empty=True)
    w, i = paths["workflow"], paths["identity"]
    if fault == "wrong_index":
        sql(w, "DROP INDEX graph_materialization_source_unique")
        sql(w, "CREATE INDEX graph_materialization_source_unique ON graph_materializations(payload)")
    elif fault == "wrong_table":
        sql(w, "DROP TABLE graph_handoffs")
        sql(w, "CREATE TABLE graph_handoffs(payload TEXT)")
    elif fault == "wrong_trigger":
        sql(i, "DROP TRIGGER artifact_immutable_update")
        sql(i, "CREATE TRIGGER artifact_immutable_update AFTER UPDATE ON artifacts BEGIN SELECT 1; END")
    else:
        sql(w, "DROP TABLE graph_materializations")
    before = contents(paths)
    with pytest.raises(ops.SchemaUpgradeError, match="incompatible definition|declares completion"):
        ops.upgrade_databases(**paths)
    assert contents(paths) == before


def test_check_literal_case_is_not_normalized_into_false_compatibility(paths):
    base(paths)
    w = paths["workflow"]
    ddl = sql(w, "SELECT sql FROM sqlite_master WHERE name='task_copilot_permissions'")[0][0]
    sql(w, "DROP TABLE task_copilot_permissions")
    sql(w, ddl.replace("'read_only'", "'READ_ONLY'"))
    before = contents(paths)
    with pytest.raises(ops.SchemaUpgradeError, match="incompatible definition"):
        ops.upgrade_databases(**paths)
    assert contents(paths) == before


def test_missing_unique_index_added_only_without_historical_conflicts(paths):
    ops.upgrade_databases(**paths, initialize_empty=True)
    w = paths["workflow"]
    sql(w, "DROP INDEX graph_materialization_source_unique")
    assert "graph_materialization_source_unique" in ops.inspect_databases(**paths)["workflow"]["missing"]
    ops.upgrade_databases(**paths)
    sql(w, "DROP INDEX graph_materialization_source_unique")
    for n in (1, 2):
        sql(w, "INSERT INTO graph_materializations VALUES(?,?,?,?,?)", (f"mat{n}", f"key{n}", "same", "{}", "checksum"))
    before = contents(paths)
    with pytest.raises(ops.SchemaUpgradeError, match="historical duplicates"):
        ops.upgrade_databases(**paths)
    assert contents(paths) == before


@pytest.mark.parametrize("column,value", [("idempotency_key", "key"), ("source_commit_id", "source")])
def test_original_unique_indexes_and_inline_constraints_are_enforced(paths, column, value):
    ops.upgrade_databases(**paths, initialize_empty=True)
    w = paths["workflow"]
    sql(w, "INSERT INTO graph_materializations VALUES('m1','key','source','{}','c')")
    second = dict(idempotency_key="new-key", source_commit_id="new-source")
    second[column] = value
    with pytest.raises(sqlite3.IntegrityError):
        sql(w, "INSERT INTO graph_materializations VALUES('m2',?,?, '{}','c')", (second["idempotency_key"], second["source_commit_id"]))
    sql(w, "INSERT INTO graph_execution_permits VALUES('p1','k','h','a','r','PREPARING','{}','c')")
    with pytest.raises(sqlite3.IntegrityError):
        sql(w, "INSERT INTO graph_execution_permits VALUES('p2','k2','h','a2','r','PREPARING','{}','c')")
    sql(paths["checkpoint"], "INSERT INTO staged_graph_checkpoints VALUES('c1','h','r','{}','c')")
    with pytest.raises(sqlite3.IntegrityError):
        sql(paths["checkpoint"], "INSERT INTO staged_graph_checkpoints VALUES('c2','h','r','{}','c')")


def test_graph_revision_partial_unique_index_preserves_initial_semantics(paths):
    ops.upgrade_databases(**paths, initialize_empty=True)
    payload = json.dumps({"proposalType": "graph_revision", "proposalPayload": {"sourceCommitId": "source"}})
    sql(paths["workflow"], "INSERT INTO planning_commit_records VALUES('c1','m1',1,'k1',?)", (payload,))
    with pytest.raises(sqlite3.IntegrityError):
        sql(paths["workflow"], "INSERT INTO planning_commit_records VALUES('c2','m2',1,'k2',?)", (payload,))
    initial = json.dumps({"proposalType": "initial_plan", "proposalPayload": {}})
    for n in (3, 4):
        sql(paths["workflow"], "INSERT INTO planning_commit_records VALUES(?,?,?,?,?)", (f"c{n}", f"m{n}", 1, f"k{n}", initial))
    assert sql(paths["workflow"], "SELECT count(*) FROM planning_commit_records") == [(3,)]


def test_identity_cross_mission_trigger_and_foreign_keys_remain_authoritative(paths):
    ops.upgrade_databases(**paths, initialize_empty=True)
    i = paths["identity"]
    for m in ("m1", "m2"):
        sql(i, "INSERT INTO missions(mission_id,user_id,goal,status,created_at,updated_at) VALUES(?,'u','goal','created','now','now')", (m,))
    sql(i, "INSERT INTO semantic_tasks(task_id,mission_id,title,objective,status) VALUES('t','m1','title','goal','pending')")
    sql(i, "INSERT INTO acg_blueprints(blueprint_id,mission_id,version,graph_id,graph_json,created_at) VALUES('bp','m2',1,'g','{}','now')")
    sql(i, "INSERT INTO workflow_runs_v2(run_id,mission_id,blueprint_id,status,graph_version,created_at,updated_at) VALUES('r','m2','bp','pending',1,'now','now')")
    with pytest.raises(sqlite3.IntegrityError):
        sql(i, "INSERT INTO attempts(attempt_id,run_id,task_id,attempt_number,status) VALUES('a','r','t',1,'pending')")
    with pytest.raises(sqlite3.IntegrityError):
        sql(i, "DELETE FROM missions WHERE mission_id='m2'")
    assert sql(i, "SELECT count(*) FROM attempts") == [(0,)]
    assert len(sql(i, "SELECT name FROM sqlite_master WHERE type='trigger'")) == 8


def test_existing_identity_foreign_key_corruption_blocks_all_upgrades(paths):
    base(paths)
    # Simulate pre-existing legacy corruption with the old writer's FK checks
    # disabled. The operator entry must detect it, not legitimize/backfill it.
    with closing(sqlite3.connect(paths["identity"])) as conn, conn:
        conn.execute("INSERT INTO workflow_runs_v2(run_id,mission_id,blueprint_id,status,graph_version,created_at,updated_at) VALUES('bad','absent','absent','pending',1,'now','now')")
    before = contents(paths)
    with pytest.raises(ops.SchemaUpgradeError, match="foreign-key violations"):
        ops.upgrade_databases(**paths)
    assert contents(paths) == before


@pytest.mark.parametrize("cut", ["materialization", "checkpoint", "checkpoint_ack"])
def test_partial_commits_detected_and_original_upgrades_resume(paths, monkeypatch, cut):
    base(paths)
    ops._reference()  # faults concern TARGET upgrades, not reference construction
    factory = ops.SQLiteGraphMaterializationStore if cut == "materialization" else ops.SQLiteStagedGraphCheckpointStore
    original = factory.upgrade_schema
    def broken(path):
        if cut == "checkpoint_ack":
            original(path)  # real SQLite COMMIT, then lost caller acknowledgement
        raise RuntimeError("target upgrade fault")
    with monkeypatch.context() as patch:
        patch.setattr(factory, "upgrade_schema", staticmethod(broken))
        with pytest.raises(RuntimeError, match="target upgrade fault"):
            ops.upgrade_databases(**paths)
    state = ops.inspect_databases(**paths)
    assert state["identity"]["status"] == "READY"
    assert "planning_commit_records" in state["workflow"]["present"]
    if cut == "materialization":
        assert "graph_materializations" in state["workflow"]["missing"]
    else:
        assert state["workflow"]["status"] == "READY"
        assert state["checkpoint"]["status"] == ("READY" if cut == "checkpoint_ack" else "UPGRADE_REQUIRED")
    assert ops.upgrade_databases(**paths)["status"] == "READY"
    checked(paths)


@pytest.mark.parametrize("cut", ["workflow", "checkpoint", "identity"])
def test_fresh_database_initializer_ack_loss_is_detected_and_resumable(paths, monkeypatch, cut):
    ops._reference()
    original = ops._initialize
    def initialized_but_ack_lost(role, path):
        original(role, path)
        if role == cut:
            raise RuntimeError("initializer COMMIT acknowledgement lost")
    with monkeypatch.context() as patch:
        patch.setattr(ops, "_initialize", initialized_but_ack_lost)
        with pytest.raises(RuntimeError, match="acknowledgement lost"):
            ops.upgrade_databases(**paths, initialize_empty=True)
    state = ops.inspect_databases(**paths, initialize_empty=True)
    assert all(item["status"] != "INVALID" for item in state.values()), state
    assert paths[cut].is_file()
    completed = contents(paths)
    ops.upgrade_databases(**paths, initialize_empty=True)
    checked(paths)
    final = contents(paths)
    for role in paths:
        if completed[role] is not None:
            assert set(completed[role]) <= set(final[role])


def test_existing_upgrader_transaction_rolls_back_failed_ddl(paths, monkeypatch):
    base(paths)
    ops._reference()
    # Real incompatible index SQL fails after table creation within the original
    # upgrade transaction. No fake database or mocked successful COMMIT.
    import support.stores.graph_materialization_store as materialization
    with monkeypatch.context() as patch:
        patch.setitem(materialization.INDEXES, "injected_failure", "CREATE UNIQUE INDEX injected_failure ON graph_materializations(no_column)")
        with pytest.raises(sqlite3.OperationalError, match="no such column"):
            ops.upgrade_databases(**paths)
    objects = sql(paths["workflow"], "SELECT name FROM sqlite_master")
    assert ("planning_commit_records",) in objects
    assert ("graph_materializations",) not in objects
    assert ("graph_materialization_schema",) not in objects
    assert ops.upgrade_databases(**paths)["status"] == "READY"


def test_invalid_path_roles_and_orphan_sidecars_make_no_files(paths, tmp_path):
    with pytest.raises(ops.SchemaUpgradeError, match="absolute"):
        ops.upgrade_databases(Path("relative.sqlite"), paths["checkpoint"], paths["identity"], initialize_empty=True)
    with pytest.raises(ops.SchemaUpgradeError, match="distinct"):
        ops.upgrade_databases(paths["workflow"], paths["workflow"], paths["identity"], initialize_empty=True)
    assert list(tmp_path.iterdir()) == []
    Path(str(paths["checkpoint"]) + "-wal").write_bytes(b"unknown")
    with pytest.raises(ops.SchemaUpgradeError, match="orphan"):
        ops.upgrade_databases(**paths, initialize_empty=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["checkpoint.sqlite-wal"]


def test_cli_default_inspection_apply_and_new_process_replay(paths):
    base(paths)
    flags = [flag for role, path in paths.items() for flag in (f"--{role}-db", str(path))]
    def run(*extra):
        return subprocess.run([sys.executable, str(CLI), *flags, *extra], capture_output=True, text=True, encoding="utf-8", timeout=45)
    before = contents(paths)
    inspected = run()
    assert inspected.returncode == 2, inspected.stderr
    assert json.loads(inspected.stdout)["status"] == "NOT_READY"
    assert contents(paths) == before
    applied = run("--apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    committed = contents(paths)
    assert run("--apply").returncode == 0
    assert run().returncode == 0
    assert contents(paths) == committed


def test_gate_mapping_includes_upgrade_module_and_cli():
    gate = runpy.run_path(str(ROOT / "scripts/freeze_gate.py"))
    sources = ["apps/agentOS/src/support/stores/c2_schema_upgrade.py", "scripts/upgrade_agentos_c2_schema.py"]
    selected, uncovered = gate["resolve_tests"](sources)
    assert uncovered == []
    assert "tests/storage/test_c2_schema_upgrade.py" in selected


def test_default_application_construction_does_not_upgrade_c2(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "apps" / "agent"))
    from app.execution.wiring import build_default_runtime, close_runtime
    def denied(*args, **kwargs):
        pytest.fail("implicit C2 upgrade during application composition")
    for factory in (*ops.UPGRADERS, ops.SQLiteStagedGraphCheckpointStore):
        monkeypatch.setattr(factory, "upgrade_schema", staticmethod(denied))
    monkeypatch.setattr(ops, "upgrade_databases", denied)
    keys = ("AGENTOS_WORKFLOW_DB_PATH", "AGENTOS_LANGGRAPH_CHECKPOINT_DB", "AGENTOS_EXECUTION_VALUE_DB",
            "AGENTOS_CONTENT_MANIFEST_DB", "AGENTOS_EXECUTION_MEMORY_DB", "AGENTOS_PROVENANCE_DB",
            "AGENTOS_AUDIT_DB", "AGENTOS_RESOURCE_DB", "AGENTOS_NODE_DB", "AGENTOS_AGENT_DB",
            "AGENTOS_RESOURCE_HEALTH_DB", "AGENTOS_EVOLUTION_DB", "AGENTOS_IDENTITY_DB")
    env = {key: str(tmp_path / f"{key}.sqlite") for key in keys}
    env["AGENTOS_MISSION_SEMANTIC_CONVERGENCE"] = "false"
    class Tools:
        def scoped(self, allowed_tools):
            return self
    runtime = build_default_runtime(environment=env, tool_runtime=Tools(), model_runtime=object(), intent_llm=object())
    try:
        for attribute in ("planning_commit_authority", "graph_materialization_authority", "graph_activation_authority",
                          "graph_handoff_authority", "execution_permit_authority"):
            assert getattr(runtime, attribute) is None
        workflow = Path(env["AGENTOS_WORKFLOW_DB_PATH"])
        assert not set(name for name, in sql(workflow, "SELECT name FROM sqlite_master")) & ops.C2_TABLES
        cp = Path(env["AGENTOS_LANGGRAPH_CHECKPOINT_DB"])
        assert sql(cp, "SELECT name FROM sqlite_master WHERE name='staged_graph_checkpoints'") == []
        # Ordinary legacy read/request paths do not install the missing schemas.
        assert runtime.workflow_store.list_missions().total == 0
        assert runtime.checkpoint_store.latest_version(run_id="absent") == 0
        assert not set(name for name, in sql(workflow, "SELECT name FROM sqlite_master")) & ops.C2_TABLES
    finally:
        close_runtime(runtime)
