"""Initial materialization and pause through real Runtime/SQLite authorities."""
import asyncio
import multiprocessing
import os
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest

from test_initial_planning_sources import initial_run, accept
from test_horizon import ready_boundary, runtime_boundary
from test_planning_commit_runtime import dump_databases
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from support.stores.graph_activation_store import SQLiteGraphActivationStore, validate_activation_run
from components.executor.compiler import ACGGraphCompiler
from contracts import stable_checksum
from test_graph_materialization import unchanged_except_journal


def setup_initial(initial_run):
    runtime, workflow, agent, run, ledger = initial_run
    record = accept(initial_run)
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    materializations = SQLiteGraphMaterializationStore(workflow.db_path)
    activations = SQLiteGraphActivationStore(workflow.db_path)
    runtime.enable_graph_materialization(materializations)
    runtime.enable_graph_activation(activations)
    return runtime, workflow, agent, run, record, materializations, activations


def materialize(context):
    runtime, _, _, _, record, journal, _ = context
    receipt = runtime.materialize_initial_commit(record.commit_id, idempotency_key="initial-materialize")
    assert receipt.status == "MATERIALIZED_INACTIVE", receipt
    return journal.get_materialization(receipt.materialization_id)


def activate(context, record):
    runtime = context[0]
    prepared = runtime.prepare_graph_activation(record.materialization_id, idempotency_key="initial-activate")
    assert prepared.status == "ACTIVATION_PREPARED", prepared
    receipt = runtime.commit_graph_activation(record.materialization_id, idempotency_key="initial-activate")
    assert receipt.status == "ACTIVATED_PAUSED", receipt
    return receipt


def test_initial_v1_paused_and_real_claim_denied(initial_run, monkeypatch):
    context = setup_initial(initial_run)
    runtime, workflow, agent, run, commit, journal, heads = context
    from test_graph_handoff import attach as attach_handoff
    from support.stores.execution_permit_store import SQLiteExecutionPermitStore
    attach_handoff(runtime, workflow)
    SQLiteExecutionPermitStore.upgrade_schema(workflow.db_path)
    runtime.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
    monkeypatch.setattr(runtime.graph_handoff_authority, "prepare", lambda *a, **kw: pytest.fail("implicit handoff"))
    monkeypatch.setattr(runtime.execution_permit_authority, "issue", lambda *a, **kw: pytest.fail("implicit permit"))
    before = unchanged_except_journal(workflow)
    monkeypatch.setattr(runtime.semantic_revision_service, "prepare", lambda **kw: pytest.fail("replacement"))
    monkeypatch.setattr(runtime.runtime_binding_service, "prepare", lambda **kw: pytest.fail("resource allocation"))
    record = materialize(context)
    assert record.source_graph_version is None and record.candidate_graph_version == 1
    assert record.initial_content.plan == commit.proposal_payload
    assert record.package.blueprint_hash == stable_checksum(record.initial_content.blueprint.model_dump(mode="json", by_alias=True))
    assert unchanged_except_journal(workflow) == before
    stale = workflow.get_run(run.run_id)
    receipt = activate(context, record)
    latest = workflow.get_run(run.run_id)
    assert latest.acg_blueprint["version"] == 1
    assert latest.execution_state["graphActivation"]["executionPermit"] is None
    assert not latest.execution_state["planningDeferred"]
    assert not latest.completed_step_ids and not latest.active_step_ids and not agent.calls
    assert not runtime.execution_value_store.list_node_commits(run_id=run.run_id)
    assert all(step.attempt == 0 and step.status.value == "pending" for step in latest.steps)
    with heads.connection() as conn:
        assert validate_activation_run(conn, latest).active_graph_version == 1
    with pytest.raises(ValueError):
        runtime._claim_acg_execution(latest)
    with pytest.raises(ValueError):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    with pytest.raises(ValueError):
        workflow.save_run(stale)
    replay = runtime.commit_graph_activation(record.materialization_id, idempotency_key="initial-activate")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.activation_id == receipt.activation_id
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", lambda *a, **kw: pytest.fail("recompiled"))
    replay = runtime.materialize_initial_commit(commit.commit_id, idempotency_key="initial-materialize")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.materialization_id == record.materialization_id
    assert runtime.materialize_graph_revision(commit.commit_id, idempotency_key="wrong-source").status == "REJECTED"


@pytest.mark.parametrize("change", ["profile", "workflow", "permission", "input", "cancel", "authority", "head"])
def test_initial_compile_window_fences(initial_run, monkeypatch, change):
    context = setup_initial(initial_run)
    runtime, workflow, agent, run, commit, journal, _ = context
    original = ACGGraphCompiler.compile_package
    def compile_then_change(compiler, *args, **kwargs):
        assert getattr(journal._local, "connection", None) is None
        package = original(compiler, *args, **kwargs)
        if change == "profile": agent.profile.capabilities = []
        elif change == "workflow": runtime._workflow_for_run(run).domain = "drift"
        elif change == "permission": monkeypatch.setattr(runtime.mission_semantic_service, "authorize", lambda *a: False)
        elif change == "input":
            latest = workflow.get_run(run.run_id)
            latest.input["operatorInput"] = "changed"
            workflow.save_run(latest)
        elif change == "cancel": runtime._cancellation_event(run.run_id).set()
        elif change == "authority": runtime.graph_materialization_authority = None
        else:
            # Another accepted Initial for the same Mission advances its head.
            _, other = runtime.prepare_run(run.mission_id, workflow_id=run.workflow_id)
            assert runtime.planning_commit_authority.accept_initial(other.run_id).status == "ACCEPTED"
        return package
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", compile_then_change)
    receipt = runtime.materialize_initial_commit(commit.commit_id, idempotency_key="initial-materialize")
    assert receipt.status == "REJECTED", receipt
    assert journal.materialization_for(commit.commit_id) is None
    assert not agent.calls and not workflow.get_run(run.run_id).acg_blueprint


@pytest.mark.parametrize("same_key", [True, False])
def test_initial_cross_connection_unique_materialization(initial_run, same_key):
    context = setup_initial(initial_run)
    runtime, workflow, _, _, commit, journal, _ = context
    authority = runtime.graph_materialization_authority
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda i: authority.materialize(commit.commit_id,
            idempotency_key="same" if same_key else f"different:{i}"), range(2)))
    assert sum(r.status == "MATERIALIZED_INACTIVE" for r in receipts) == 1, receipts
    assert {r.status for r in receipts} == ({"MATERIALIZED_INACTIVE", "IDEMPOTENT_REPLAY"} if same_key else {"MATERIALIZED_INACTIVE", "REJECTED"})
    assert SQLiteGraphMaterializationStore(workflow.db_path).materialization_for(commit.commit_id)


def test_initial_compile_failure_and_ordinary_graph_forgery_rejected(initial_run, monkeypatch):
    context = setup_initial(initial_run)
    runtime, workflow, _, run, commit, journal, heads = context
    forged = workflow.get_run(run.run_id)
    forged.execution_state["graphVersion"] = 1
    with pytest.raises(ValueError):
        workflow.save_run(forged)
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", lambda *a, **kw: (_ for _ in ()).throw(ValueError("failure")))
    receipt = runtime.materialize_initial_commit(commit.commit_id, idempotency_key="failed")
    assert receipt.status == "REJECTED"
    assert journal.materialization_for(commit.commit_id) is None and heads.head(run.run_id) is None


def reopen(folder, commit_id):
    """Independent host assembly over the same temporary persistent databases."""
    from test_react_loop import runtime_at
    from components.mission_manager.semantic_service import MissionSemanticService
    from contracts.mission_semantic import SemanticPrincipal
    from support.stores.planning_commit_store import SQLitePlanningCommitStore
    runtime, workflow, agent = runtime_at(Path(folder))
    ledger = SQLitePlanningCommitStore(workflow.db_path)
    record = ledger.get(commit_id)
    runtime.workflow_registry.register(record.source_provenance.workflow.model_copy(deep=True))
    owner = SemanticPrincipal(actorId="owner", tenantId="tenant")
    runtime.mission_semantic_service = MissionSemanticService(store=workflow, authorize=lambda p, m, a: p == owner)
    runtime.semantic_principal_provider = lambda: owner
    runtime.allow_legacy_mission_intent = False
    runtime.enable_planning_commit(ledger)
    runtime.enable_graph_materialization(SQLiteGraphMaterializationStore(workflow.db_path))
    runtime.enable_graph_activation(SQLiteGraphActivationStore(workflow.db_path))
    return runtime, workflow, agent


def _durable_cut(folder, commit_id, cut):
    runtime, _, _ = reopen(folder, commit_id)
    if cut == "compiled":
        original_compile = ACGGraphCompiler.compile_package
        def exit_before_journal(*args, **kwargs):
            original_compile(*args, **kwargs)
            os._exit(80)
        ACGGraphCompiler.compile_package = exit_before_journal
    result = runtime.materialize_initial_commit(commit_id, idempotency_key="initial-materialize")
    if result.status not in {"MATERIALIZED_INACTIVE", "IDEMPOTENT_REPLAY"}:
        os._exit(90)
    from runtime.initial_graph_compilation import compile_initial_content
    persisted = runtime.graph_materialization_authority.store.get_materialization(result.materialization_id)
    rebuilt = compile_initial_content(runtime.planning_commit_authority.store.get(commit_id),
                                      timestamp=persisted.initial_content.blueprint.created_at)
    assert rebuilt == persisted.initial_content
    assert ACGGraphCompiler().compile_package(rebuilt.blueprint,
        run_id=persisted.source_run_id) == persisted.package
    if cut == "journal":
        os._exit(81)  # Real process death after the durable package, before Head.
    prepared = runtime.prepare_graph_activation(result.materialization_id, idempotency_key="initial-activate")
    if prepared.status != "ACTIVATION_PREPARED":
        os._exit(91)
    if cut == "prepared":
        os._exit(82)
    store = runtime.graph_activation_authority.store
    original = store._connect
    class ExitAfterCommit:
        def __init__(self): self.inner = original()
        def __getattr__(self, key): return getattr(self.inner, key)
        def commit(self):
            self.inner.commit()
            os._exit(83)  # The authority cannot return an ACK to this caller.
    store._connect = ExitAfterCommit
    runtime.commit_graph_activation(result.materialization_id, idempotency_key="initial-activate")
    os._exit(92)


@pytest.mark.parametrize("cut,exit_code", [("compiled", 80), ("journal", 81), ("prepared", 82), ("head", 83)])
def test_real_process_exit_recovers_same_initial_fact(initial_run, cut, exit_code):
    context = setup_initial(initial_run)
    _, workflow, _, run, commit, journal, heads = context
    child = multiprocessing.get_context("spawn").Process(target=_durable_cut,
        args=(str(workflow.db_path.parent), commit.commit_id, cut))
    child.start()
    child.join(25)
    if child.is_alive():
        child.terminate(); child.join()
        pytest.fail("materialization child exceeded process experiment limit")
    assert child.exitcode == exit_code
    stored = journal.materialization_for(commit.commit_id)
    runtime, restarted_store, agent = reopen(workflow.db_path.parent, commit.commit_id)
    receipt = runtime.materialize_initial_commit(commit.commit_id, idempotency_key="initial-materialize")
    if cut == "compiled":
        assert stored is None and receipt.status == "MATERIALIZED_INACTIVE"
        stored = journal.materialization_for(commit.commit_id)
    else:
        assert receipt.status == "IDEMPOTENT_REPLAY"
    assert stored and stored.candidate_graph_version == 1
    assert receipt.package_checksum == stored.package_checksum
    if cut in {"compiled", "journal"}:
        assert not heads.head(run.run_id)
        assert not restarted_store.get_run(run.run_id).acg_blueprint
        assert runtime.prepare_graph_activation(stored.materialization_id, idempotency_key="initial-activate").status == "ACTIVATION_PREPARED"
    receipt = runtime.commit_graph_activation(stored.materialization_id, idempotency_key="initial-activate")
    assert receipt.status == ("IDEMPOTENT_REPLAY" if cut == "head" else "ACTIVATED_PAUSED"), receipt
    current = restarted_store.get_run(run.run_id)
    with pytest.raises(ValueError):
        runtime._claim_acg_execution(current)
    assert not agent.calls and not runtime.execution_value_store.list_node_commits(run_id=run.run_id)
    assert journal.materialization_for(commit.commit_id) == stored
    assert heads.head(run.run_id).active_graph_version == 1


@pytest.mark.parametrize("failure", ["run_cas", "run_write", "head_write"])
def test_activation_transaction_rolls_back_or_rejects_stale_run(initial_run, monkeypatch, failure):
    context = setup_initial(initial_run)
    runtime, workflow, _, run, _, _, heads = context
    record = materialize(context)
    assert runtime.prepare_graph_activation(record.materialization_id, idempotency_key="act").status == "ACTIVATION_PREPARED"
    if failure == "run_cas":
        original = runtime.graph_activation_authority._activated_run
        def change(*args):
            candidate = original(*args)
            latest = workflow.get_run(run.run_id)
            latest.runtime_revision += 1
            workflow.save_run(latest)
            return candidate
        monkeypatch.setattr(runtime.graph_activation_authority, "_activated_run", change)
    else:
        with sqlite3.connect(workflow.db_path) as conn:
            table = "runs" if failure == "run_write" else "graph_activation_heads"
            operation = "UPDATE" if table == "runs" else "INSERT"
            conn.execute(f"CREATE TRIGGER deny_activation BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'fault'); END")
    receipt = runtime.commit_graph_activation(record.materialization_id, idempotency_key="act")
    assert receipt.status == "REJECTED", receipt
    assert heads.head(run.run_id) is None
    assert heads.activation_for(record.materialization_id).status == "ACTIVATION_PREPARED"
    assert workflow.get_run(run.run_id).acg_blueprint is None


def test_replay_lookup_survives_drift_but_cannot_activate(initial_run, monkeypatch):
    context = setup_initial(initial_run)
    runtime, workflow, agent, run, commit, journal, heads = context
    record = materialize(context)
    agent.profile.capabilities = []
    assert runtime.planning_commit_authority.accept_initial(run.run_id).code.value == "STALE_STRATEGY"
    # Recover the accepted identity from the formal key; never create another.
    recovered = journal.get_by_idempotency_key("initial-planning:" + run.run_id)
    assert recovered == commit
    assert runtime.materialize_initial_commit(recovered.commit_id, idempotency_key="initial-materialize").status == "IDEMPOTENT_REPLAY"
    assert runtime.prepare_graph_activation(record.materialization_id, idempotency_key="act").status == "REJECTED"
    assert not heads.head(run.run_id) and not workflow.get_run(run.run_id).acg_blueprint


def test_legacy_initial_cannot_materialize_and_corrupt_package_cannot_activate(initial_run):
    import json
    context = setup_initial(initial_run)
    runtime, workflow, _, _, commit, journal, _ = context
    record = materialize(context)
    with sqlite3.connect(workflow.db_path) as conn:
        body = json.loads(conn.execute("SELECT payload FROM graph_materializations WHERE materialization_id=?",
                                     (record.materialization_id,)).fetchone()[0])
        body["package"]["checksum"] = "0" * 64
        conn.execute("UPDATE graph_materializations SET payload=? WHERE materialization_id=?", (json.dumps(body), record.materialization_id))
    assert runtime.prepare_graph_activation(record.materialization_id, idempotency_key="corrupt").status == "REJECTED"
    with sqlite3.connect(workflow.db_path) as conn:
        body = json.loads(conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (commit.commit_id,)).fetchone()[0])
        body["sourceProvenance"] = None
        conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?", (json.dumps(body), commit.commit_id))
    assert journal.get(commit.commit_id).source_provenance is None
    assert runtime.materialize_initial_commit(commit.commit_id, idempotency_key="legacy").status == "REJECTED"


def test_frozen_compilation_does_not_read_runtime_and_native_source_lowers(initial_run):
    from runtime.initial_graph_compilation import compile_initial_content
    from contracts.workflow import WorkflowDefinition, WorkflowDefinitionType
    from contracts.mission_semantic import MissionSemanticRequest
    runtime, workflow, agent, _, ledger = initial_run
    agent.profile.capabilities.extend(["analysis", "artifact_generation"])
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="initial-native", name="native",
        domain="general", runtimeEngine="acg", definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP))
    mission = runtime.create_mission("Analyze input", workflow_id="initial-native")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="native-source", expectedMissionRevision=0,
        objective="Analyze supplied input", constraints=[], sourceRefs=[]))
    _, run = runtime.prepare_run(mission.mission_id, workflow_id="initial-native", input_override={"deterministicIntent": True})
    receipt = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert receipt.status == "ACCEPTED", receipt
    commit = ledger.get(receipt.commit_id)
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    journal, heads = SQLiteGraphMaterializationStore(workflow.db_path), SQLiteGraphActivationStore(workflow.db_path)
    runtime.enable_graph_materialization(journal)
    runtime.enable_graph_activation(heads)
    context = runtime, workflow, agent, run, commit, journal, heads
    materialized = materialize(context)
    activate(context, materialized)
    first = compile_initial_content(commit, timestamp=materialized.initial_content.blueprint.created_at)
    assert first == materialized.initial_content
    # Pure compile cannot access this mutated host; repeated frozen bytes win.
    runtime.capability_catalog = None
    runtime.agent_registry = None
    runtime.identity_lifecycle = None
    second = compile_initial_content(commit, timestamp=first.blueprint.created_at)
    assert first == second and first.plan == commit.proposal_payload
    assert first.blueprint.version == 1 and len(first.blueprint.step_nodes()) > 0


@pytest.mark.parametrize("same_key", [True, False])
def test_initial_concurrent_activation_cannot_replace_head(initial_run, same_key):
    context = setup_initial(initial_run)
    runtime, workflow, _, run, _, _, heads = context
    record = materialize(context)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: runtime.prepare_graph_activation(record.materialization_id,
            idempotency_key="same" if same_key else f"different:{i}"), range(2)))
    assert sum(result.status == "ACTIVATION_PREPARED" for result in results) == 1
    prepared = heads.activation_for(record.materialization_id)
    receipt = runtime.commit_graph_activation(record.materialization_id, idempotency_key=prepared.idempotency_key)
    assert receipt.status == "ACTIVATED_PAUSED", receipt
    assert heads.head(run.run_id).activation_id == receipt.activation_id
    # Replaying a prepare after ACK loss recovers the same activation fact.
    assert runtime.prepare_graph_activation(record.materialization_id,
        idempotency_key=prepared.idempotency_key).status == "IDEMPOTENT_REPLAY"
    with sqlite3.connect(workflow.db_path) as conn:
        conn.execute("UPDATE graph_activation_heads SET active_graph_version=2 WHERE run_id=?", (run.run_id,))
    assert runtime.commit_graph_activation(record.materialization_id,
        idempotency_key=prepared.idempotency_key).status == "REJECTED"


def test_initial_journal_ack_loss_is_recoverable_without_recompile(initial_run, monkeypatch):
    context = setup_initial(initial_run)
    runtime, _, _, _, commit, journal, _ = context
    original = journal._connect
    class LostACK:
        def __init__(self): self.inner = original()
        def __getattr__(self, key): return getattr(self.inner, key)
        def commit(self):
            self.inner.commit()
            raise sqlite3.OperationalError("lost materialization ACK")
    monkeypatch.setattr(journal, "_connect", LostACK)
    receipt = runtime.materialize_initial_commit(commit.commit_id, idempotency_key="initial-materialize")
    assert receipt.status == "REJECTED" and receipt.code.value == "STORAGE_UNAVAILABLE"
    monkeypatch.setattr(journal, "_connect", original)
    stored = journal.materialization_for(commit.commit_id)
    assert stored is not None
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", lambda *a, **kw: pytest.fail("recompile after uncertain ACK"))
    receipt = runtime.materialize_initial_commit(commit.commit_id, idempotency_key="initial-materialize")
    assert receipt.status == "IDEMPOTENT_REPLAY" and receipt.materialization_id == stored.materialization_id


def _competing_initial_materializer(folder, commit_id, key, barrier, output):
    runtime, _, _ = reopen(folder, commit_id)
    original = ACGGraphCompiler.compile_package
    def synchronize(*args, **kwargs):
        package = original(*args, **kwargs)
        barrier.wait(20)  # Both independent processes compiled before either writes.
        return package
    ACGGraphCompiler.compile_package = synchronize
    receipt = runtime.materialize_initial_commit(commit_id, idempotency_key=key)
    output.put((receipt.status, receipt.materialization_id, receipt.package_checksum))


@pytest.mark.parametrize("same_key", [True, False])
def test_spawn_competition_has_one_initial_version(initial_run, same_key):
    context = setup_initial(initial_run)
    _, workflow, _, run, commit, journal, heads = context
    spawn = multiprocessing.get_context("spawn")
    barrier, output = spawn.Barrier(2), spawn.Queue()
    children = [spawn.Process(target=_competing_initial_materializer, args=(str(workflow.db_path.parent),
        commit.commit_id, "same" if same_key else f"different:{i}", barrier, output)) for i in range(2)]
    for child in children: child.start()
    try:
        for child in children:
            child.join(25)
            assert not child.is_alive() and child.exitcode == 0
        receipts = [output.get(timeout=3) for _ in children]
    finally:
        for child in children:
            if child.is_alive(): child.terminate(); child.join()
        output.close()
    assert sum(r[0] == "MATERIALIZED_INACTIVE" for r in receipts) == 1
    assert {r[0] for r in receipts} == ({"MATERIALIZED_INACTIVE", "IDEMPOTENT_REPLAY"} if same_key
                                     else {"MATERIALIZED_INACTIVE", "REJECTED"})
    stored = journal.materialization_for(commit.commit_id)
    if same_key:
        assert len({(r[1], r[2]) for r in receipts}) == 1
    assert stored and not heads.head(run.run_id)
    assert workflow.get_run(run.run_id).acg_blueprint is None


def test_initial_step_projection_uses_blueprint_without_run_input_overrides(initial_run):
    runtime, workflow, _, run, _ = initial_run
    current = workflow.get_run(run.run_id)
    current.input["reasoningEffort"] = "high"
    workflow.save_run(current)
    context = setup_initial(initial_run)
    record = materialize(context)
    activate(context, record)
    persisted = workflow.get_run(run.run_id)
    assert persisted.input["reasoningEffort"] == "high"
    for step in persisted.steps:
        node = record.initial_content.blueprint.get_node(step.step_id)
        assert step.input.get("reasoningEffort") == node.input_spec.get("reasoningEffort", node.metadata.get("reasoningEffort"))


@pytest.mark.parametrize("phase", ["compile", "activation"])
def test_initial_recipe_identity_is_fenced(initial_run, monkeypatch, phase):
    import runtime.initial_graph_compilation as compilation
    context = setup_initial(initial_run)
    runtime, workflow, _, run, commit, journal, heads = context
    if phase == "compile":
        original = compilation.initial_recipe_fingerprint()
        calls = iter([original, "f" * 64])
        monkeypatch.setattr(compilation, "initial_recipe_fingerprint", lambda: next(calls))
        receipt = runtime.materialize_initial_commit(commit.commit_id, idempotency_key="initial-materialize")
        assert receipt.status == "REJECTED" and receipt.code.value == "STALE_STRATEGY"
        assert journal.materialization_for(commit.commit_id) is None
    else:
        record = materialize(context)
        monkeypatch.setattr(compilation, "initial_recipe_fingerprint", lambda: "f" * 64)
        receipt = runtime.prepare_graph_activation(record.materialization_id, idempotency_key="recipe-changed")
        assert receipt.status == "REJECTED" and receipt.code.value == "STALE_STRATEGY"
    assert not workflow.get_run(run.run_id).acg_blueprint and not heads.head(run.run_id)
