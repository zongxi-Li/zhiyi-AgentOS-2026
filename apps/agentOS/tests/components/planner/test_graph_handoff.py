"""Real completed A, durable no-permit state handoff and crash reconciliation."""
import asyncio
import json
import multiprocessing
import os
import sqlite3
from pathlib import Path
import pytest
from contracts import stable_checksum
from support.stores.graph_activation_store import SQLiteGraphActivationStore
from support.stores.graph_handoff_store import SQLiteGraphHandoffStore, SQLiteStagedGraphCheckpointStore


def attach(runtime, workflow):
    SQLiteGraphHandoffStore.upgrade_schema(workflow.db_path)
    SQLiteStagedGraphCheckpointStore.upgrade_schema(runtime.checkpoint_store.db_path)
    ledger = SQLiteGraphHandoffStore(workflow.db_path)
    staged = SQLiteStagedGraphCheckpointStore(runtime.checkpoint_store.db_path)
    runtime.enable_graph_handoff(ledger, staged)
    return ledger, staged


def _build_prefix(tmp_path, monkeypatch, *, before_accept=None):
    import test_react_loop
    from test_graph_materialization_audit import test_real_executed_A_pending_BC_materialized_D_survives_process_restart
    from runtime.planning_commit import RuntimePlanningCommitAuthority
    from contracts.planning import TaskPlanRelation
    captured = []
    original = test_react_loop.runtime_at
    def capture(path):
        value = original(path)
        captured.append(value)
        return value
    monkeypatch.setattr(test_react_loop, "runtime_at", capture)
    accept = RuntimePlanningCommitAuthority.accept_patch_locked
    def chain(authority, run_id, patch, **kwargs):
        run = authority.runtime.workflow_store.get_run(run_id)
        if before_accept is not None:
            before_accept(authority, run_id)
        relations = tuple(TaskPlanRelation.model_validate(r) for r in run.execution_state["taskPlan"]["relations"])
        patch = patch.model_copy(update={"relations": (*relations,
            TaskPlanRelation(sourceKey="step:C", targetKey="step:D", relationType="depends_on"))})
        return accept(authority, run_id, patch, **kwargs)
    monkeypatch.setattr(RuntimePlanningCommitAuthority, "accept_patch_locked", chain)
    test_real_executed_A_pending_BC_materialized_D_survives_process_restart(tmp_path, True)
    runtime, workflow, agent = captured[0]
    run = workflow.list_all_runs(limit=10)[0]
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    journal = SQLiteGraphActivationStore(workflow.db_path)
    runtime.enable_graph_activation(journal)
    with journal.connection() as conn:
        mat = conn.execute("SELECT materialization_id FROM graph_materializations").fetchone()[0]
    assert runtime.prepare_graph_activation(mat, idempotency_key="act").status == "ACTIVATION_PREPARED"
    result = runtime.commit_graph_activation(mat, idempotency_key="act")
    assert result.status == "ACTIVATED_PAUSED", result
    ledger, staged = attach(runtime, workflow)
    return runtime, workflow, agent, run.run_id, result.activation_id, ledger, staged


@pytest.fixture
def prefix(tmp_path, monkeypatch):
    return _build_prefix(tmp_path, monkeypatch)


def test_real_prefix_handoff_preserves_all_existing_facts(prefix):
    from test_planning_commit_runtime import dump_databases
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    before = dump_databases(workflow, include_ledger=True)
    run = workflow.get_run(run_id)
    old_cp = rt.checkpoint_store.load_latest(run_id=run_id)
    version = rt.checkpoint_store.latest_version(run_id=run_id)
    evidence_receipt = rt.execution_value_store.list_node_commits(run_id=run_id)[0]
    evidence_attempt = evidence_receipt["nodeExecution"]["attemptId"]
    with sqlite3.connect(rt.checkpoint_store.db_path) as conn:
        raw_checkpoints = conn.execute("SELECT * FROM acg_execution_checkpoints").fetchall()
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "STATE_PREPARED", result.model_dump()
    record = ledger.get_handoff(result.handoff_id)
    assert record.status == "STATE_PREPARED" and staged.get(record.candidate.checkpoint_id) == record.candidate
    assert record.candidate.state["completedStepIds"] == ["A"]
    assert record.candidate.state["graphVersion"] == 2
    assert record.candidate.state["outputRefs"] == run.execution_state["outputRefs"]
    assert record.identity_link.prefix_attempt_ids
    assert rt.checkpoint_store.load_latest(run_id=run_id) == old_cp
    assert rt.checkpoint_store.latest_version(run_id=run_id) == version
    with sqlite3.connect(rt.checkpoint_store.db_path) as conn:
        assert conn.execute("SELECT * FROM acg_execution_checkpoints").fetchall() == raw_checkpoints
    assert rt.checkpoint_store.load(run_id=run_id, checkpoint_id=record.candidate.checkpoint_id) is None
    assert workflow.get_run(run_id) == run
    after = dump_databases(workflow, include_ledger=True)
    for name, body in before.items():
        if name not in {workflow.db_path.name, rt.checkpoint_store.db_path.name}:
            assert after[name] == body
    assert rt.prepare_graph_handoff(act, idempotency_key="handoff").status == "IDEMPOTENT_REPLAY"
    assert rt.prepare_graph_handoff(act, idempotency_key="other").code == "DUPLICATE_CONFLICT"
    assert agent.calls == ["A"]


@pytest.mark.parametrize("damage", ["receipt_missing", "receipt_prepared", "receipt_unknown", "execution", "output",
    "context", "memory", "provenance", "identity", "attempt", "checkpoint", "unacknowledged_checkpoint",
    "scope", "permission", "basis", "head", "operator", "cancel", "catalog", "workflow", "profile"])
def test_independent_sources_cannot_be_replaced_by_run_projection(prefix, monkeypatch, damage):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    run = workflow.get_run(run_id)
    receipt = rt.execution_value_store.list_node_commits(run_id=run_id)[0]
    if damage.startswith("receipt_"):
        with sqlite3.connect(rt.execution_value_store.db_path) as conn:
            if damage == "receipt_missing": conn.execute("DELETE FROM acg_node_commits")
            else:
                receipt["stage"] = damage.removeprefix("receipt_")
                conn.execute("UPDATE acg_node_commits SET stage=?,payload_json=?", (receipt["stage"], json.dumps(receipt)))
    elif damage == "execution":
        with sqlite3.connect(rt.execution_value_store.db_path) as conn:
            conn.execute("DELETE FROM acg_node_executions")
    elif damage in {"output", "context"}:
        reference = receipt[damage + "Ref"]
        with sqlite3.connect(rt.execution_value_store.db_path) as conn:
            conn.execute("UPDATE execution_values SET payload_json=? WHERE reference=?", (json.dumps({"forged": True}), reference))
    elif damage == "memory":
        assert receipt["memoryRef"] != "memory:none"
        monkeypatch.setattr(rt.memory_store, "get", lambda _: None)
    elif damage == "provenance":
        with sqlite3.connect(rt.provenance_store.db_path) as conn:
            conn.execute("DELETE FROM acg_provenance_events")
    elif damage in {"identity", "attempt"}:
        repo = rt.identity_lifecycle.repositories.runs if damage == "identity" else rt.identity_lifecycle.repositories.attempts
        monkeypatch.setattr(repo, "get", lambda _: None)
    elif damage in {"checkpoint", "unacknowledged_checkpoint"}:
        if damage == "checkpoint":
            with sqlite3.connect(rt.checkpoint_store.db_path) as conn:
                conn.execute("UPDATE acg_execution_checkpoints SET state_json='{}'")
        else:
            rt.checkpoint_store.save(run_id=run_id, checkpoint_id="unacknowledged", state=rt.checkpoint_store.load_latest(run_id=run_id)[1])
    elif damage == "permission":
        rt.mission_semantic_service.authorize = lambda *a: False
    elif damage == "basis":
        with workflow._connect() as conn:
            conn.execute("UPDATE mission_semantic_state SET revision=revision+1")
    elif damage == "head":
        with workflow._connect() as conn:
            conn.execute("UPDATE graph_activation_heads SET active_graph_version=3")
    elif damage == "operator":
        run.input["operatorChange"] = "new request"
        workflow.save_run(run)
    elif damage == "cancel":
        rt._signal_run_cancellation(run_id)
    elif damage == "scope":
        # Simulate a damaged durable scope; normal save already rejects it.
        run.execution_scope = run.execution_scope.model_copy(update={"capability_ids": ()})
        with workflow._connect() as conn:
            conn.execute("UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run_id))
    elif damage == "catalog":
        descriptor = rt.capability_catalog.available()[0]
        monkeypatch.setattr(rt.capability_catalog, "available", lambda: (descriptor.model_copy(update={"description": "changed"}),))
    elif damage == "workflow":
        definition = rt._workflow_for_run(run).model_copy(update={"domain": "different"})
        rt.workflow_registry.register(definition)
    else:
        rt.agent_registry.all()[0].profile.description = "changed profile"
    before = workflow.get_run(run_id)
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "REJECTED", (damage, result)
    assert ledger.handoff_for(act) is None and workflow.get_run(run_id) == before
    assert agent.calls == ["A"]


def _reopen(folder, definition):
    from test_graph_activation_audit import _reopen as runtime_at
    rt, workflow, agent = runtime_at(folder, definition)
    ledger = SQLiteGraphHandoffStore(workflow.db_path)
    staged = SQLiteStagedGraphCheckpointStore(rt.checkpoint_store.db_path)
    rt.enable_graph_handoff(ledger, staged)
    return rt, workflow, agent, ledger, staged


def _crash(folder, definition, act, cut):
    rt, _, _, ledger, staged = _reopen(folder, definition)
    original_stage, original_confirm = staged.stage, ledger._confirm_handoff
    def stage(record):
        if cut == "before_stage": os._exit(31)
        original_stage(record)
        if cut == "after_stage": os._exit(32)
    def confirm(record):
        if cut == "before_confirm": os._exit(33)
        original_confirm(record)
        if cut == "after_confirm_uncommitted": os._exit(34)
    staged.stage, ledger._confirm_handoff = stage, confirm
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "STATE_PREPARED", result
    os._exit(35)


@pytest.mark.parametrize("cut", ["before_stage", "after_stage", "before_confirm", "after_confirm_uncommitted", "after_commit"])
@pytest.mark.slow_multiprocess
@pytest.mark.slow_fault_injection
def test_real_process_crash_reconciles_without_reexecution(prefix, cut):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    before = workflow.get_run(run_id)
    definition = rt._workflow_for_run(before).model_dump(mode="json", by_alias=True)
    worker = multiprocessing.get_context("spawn").Process(target=_crash,
        args=(str(workflow.db_path.parent), definition, act, cut))
    worker.start()
    worker.join(60)
    if worker.is_alive(): worker.terminate(); worker.join(10)
    assert worker.exitcode == {"before_stage":31,"after_stage":32,"before_confirm":33,"after_confirm_uncommitted":34,"after_commit":35}[cut]
    intent = ledger.handoff_by_key("handoff")
    assert intent is not None
    assert intent.status == ("STATE_PREPARED" if cut == "after_commit" else "STAGING")
    assert (staged.get(intent.candidate.checkpoint_id) is not None) == (cut != "before_stage")
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == ("IDEMPOTENT_REPLAY" if cut == "after_commit" else "STATE_PREPARED"), result
    assert workflow.get_run(run_id) == before and agent.calls == ["A"]


@pytest.mark.parametrize("point", ["stage", "staged_read", "intent_commit"])
def test_source_progress_between_databases_never_confirms(prefix, monkeypatch, point):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    def change():
        run = workflow.get_run(run_id)
        run.input["newOperatorInput"] = "keep paused"
        workflow.save_run(run)
    original = staged.stage if point == "stage" else staged.get
    if point == "intent_commit":
        original_append = ledger._append_handoff
        def append(record):
            original_append(record)
            rt._signal_run_cancellation(run_id)
        monkeypatch.setattr(ledger, "_append_handoff", append)
    else:
        def blocked(*args):
            result = original(*args)
            if point == "staged_read":
                monkeypatch.setattr(rt.mission_semantic_service, "authorize", lambda *a: False)
            else:
                change()
            return result
        monkeypatch.setattr(staged, "stage" if point == "stage" else "get", blocked)
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "REJECTED", result
    assert ledger.handoff_for(act).status == "STAGING" and agent.calls == ["A"]


def test_normal_save_cannot_adopt_candidate_checkpoint_or_fake_handoff(prefix):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "STATE_PREPARED", result
    record = ledger.get_handoff(result.handoff_id)
    for field, value in (("checkpointId", record.candidate.checkpoint_id),
                         ("graphHandoff", record.model_dump(mode="json", by_alias=True))):
        run = workflow.get_run(run_id)
        run.execution_state[field] = value
        with pytest.raises(ValueError, match="activation head"):
            workflow.save_run(run)
    assert agent.calls == ["A"]


def test_restart_reconstructs_same_preparation_but_cannot_execute(prefix):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "STATE_PREPARED", result
    before = workflow.get_run(run_id)
    definition = rt._workflow_for_run(before).model_dump(mode="json", by_alias=True)
    fresh, reopened, fresh_agent, _, _ = _reopen(str(workflow.db_path.parent), definition)
    def forbidden(*a, **kw): pytest.fail("handoff recovery called Planner or Binder")
    fresh.runtime_planning_coordinator.planner_for_run = forbidden
    fresh.runtime_binding_service.prepare = forbidden
    asyncio.run(fresh.close_orphaned_runs(limit=10))
    replay = fresh.prepare_graph_handoff(act, idempotency_key="handoff")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.handoff_id == result.handoff_id, replay
    with pytest.raises(ValueError, match="execution permit"):
        asyncio.run(fresh.execute_prepared_run(run_id))
    assert reopened.get_run(run_id) == before and fresh_agent.calls == [] and agent.calls == ["A"]
    for authority in (rt.graph_handoff_authority, None):
        rt.graph_handoff_authority = authority
        with pytest.raises(ValueError, match="execution permit"):
            asyncio.run(rt.execute_prepared_run(run_id))
    assert agent.calls == ["A"]
