"""Independent P1 counterexamples: real Runtime, journals and Workflow SQLite."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

import pytest
from contracts.workflow import RuntimeRunRecord
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from test_graph_activation import activated, chain, materialized_chain_with_checkpoint
from test_horizon import ready_boundary, runtime_boundary


def durable(workflow):
    with workflow._connect() as conn:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("runs", "graph_activation_heads", "graph_activations", "graph_materializations")}


def attack(run, kind):
    state = run.execution_state
    if kind == "blueprint":
        run.acg_blueprint["nodes"][0]["description"] = "forged node semantics"
    elif kind == "package":
        state["compiledACGPackage"]["packageId"] = "forged-package"
    elif kind.startswith("compiled"):
        state[kind] = "forged" if kind != "compiledPackageVersion" else 3
    elif kind == "remove":
        del state["graphActivation"]
    elif kind == "graphVersion":
        state["graphVersion"] = 1
    elif kind.startswith("permit:"):
        state["graphActivation"]["executionPermit"] = {
            "string": "permit", "bool": True, "receipt": {"permitId": "fake"}}[kind.split(":")[1]]
    else:
        field = kind.split(":")[1]
        state["graphActivation"][field] = {
            "activationId": "other", "materializationId": "other", "sourceCommitId": "other",
            "status": "ACTIVE", "graphId": "other", "activeGraphVersion": 3,
            "sourceGraphVersion": 2, "supersededCheckpointId": "other", "extra": True}[field]


@pytest.mark.parametrize("kind", ["blueprint", "package", "compiledPackageId", "compiledPackageChecksum",
    "compiledPackageBlueprintHash", "compiledPackageVersion", "remove", "graphVersion",
    "permit:string", "permit:bool", "permit:receipt", "projection:activationId",
    "projection:materializationId", "projection:sourceCommitId", "projection:status",
    "projection:graphId", "projection:activeGraphVersion", "projection:sourceGraphVersion",
    "projection:supersededCheckpointId", "projection:extra"])
def test_valid_typed_attack_snapshot_rejected(ready_boundary, kind):
    runtime, workflow, journal, run_id, _, agent, _ = activated(ready_boundary)
    before = durable(workflow)
    run = workflow.get_run(run_id)
    attack(run, kind)
    run = RuntimeRunRecord.model_validate_json(run.model_dump_json(by_alias=True))
    from contracts.compiled_acg import load_compiled_acg_package
    from support.acg.schema import ACGBlueprint
    # These attacks also remain valid compiled-package contracts; rejection
    # must come from the durable activation binding, not package syntax.
    load_compiled_acg_package(run.execution_state["compiledACGPackage"])
    ACGBlueprint.model_validate(run.acg_blueprint)
    with pytest.raises(ValueError, match="activation head"):
        SQLiteWorkflowStore(workflow.db_path).save_run(run)
    assert durable(workflow) == before
    assert agent.calls == []


@pytest.mark.parametrize("damage", ["projection", "journal", "materialization", "head"])
def test_commit_replay_detects_durable_corruption(ready_boundary, damage):
    runtime, workflow, journal, run_id, mat_id, agent, _ = activated(ready_boundary)
    with workflow._connect() as conn:
        if damage == "projection":
            run = workflow.get_run(run_id)
            del run.execution_state["graphActivation"]
            conn.execute("UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run_id))
        elif damage == "head":
            conn.execute("UPDATE graph_activation_heads SET graph_id='wrong'")
        else:
            table = "graph_activations" if damage == "journal" else "graph_materializations"
            conn.execute(f"UPDATE {table} SET checksum=?", ("0" * 64,))
    before = durable(workflow)
    result = runtime.commit_graph_activation(mat_id, idempotency_key="act")
    assert result.status == "REJECTED", result.model_dump()
    assert durable(workflow) == before and agent.calls == []


def test_execution_head_survives_projection_removal_and_authority_detachment(ready_boundary):
    runtime, workflow, _, run_id, _, agent, _ = activated(ready_boundary)
    run = workflow.get_run(run_id)
    del run.execution_state["graphActivation"]
    with workflow._connect() as conn:
        conn.execute("UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run_id))
    runtime.graph_activation_authority = None
    before = durable(workflow)
    with pytest.raises(ValueError, match="activation|execution permit"):
        asyncio.run(runtime._execute_acg(run))
    assert durable(workflow) == before and agent.calls == []


def test_valid_post_activation_save_and_validation_cost(ready_boundary):
    _, workflow, journal, run_id, _, agent, _ = activated(ready_boundary)
    head = journal.head(run_id)
    run = workflow.get_run(run_id)
    start = perf_counter()
    for i in range(10):
        run.lifecycle_message = f"paused diagnostic {i}"
        workflow.save_run(run)
    elapsed = perf_counter() - start
    print(f"10 validated save_run calls: {elapsed:.6f}s")
    assert workflow.get_run(run_id).lifecycle_message == "paused diagnostic 9"
    assert journal.head(run_id) == head and agent.calls == []


def test_checkpoint_reference_is_pinned_on_first_activation(ready_boundary):
    from support.stores.graph_activation_store import SQLiteGraphActivationStore
    runtime, workflow, _, run_id, mat_id, _ = materialized_chain_with_checkpoint(ready_boundary)
    checkpoint = workflow.get_run(run_id).execution_state["checkpointId"]
    runtime.enable_graph_activation(SQLiteGraphActivationStore(workflow.db_path))
    assert runtime.prepare_graph_activation(mat_id, idempotency_key="act").status == "ACTIVATION_PREPARED"
    assert runtime.commit_graph_activation(mat_id, idempotency_key="act").status == "ACTIVATED_PAUSED"
    assert workflow.get_run(run_id).execution_state["graphActivation"]["supersededCheckpointId"] == checkpoint


def test_execute_slot_blocks_activation_after_old_run_read(ready_boundary, monkeypatch):
    runtime, workflow, journal, run_id, mat_id, agent = chain(ready_boundary, prepare_key="act")
    old_run = workflow.get_run(run_id)
    entered, release = threading.Event(), threading.Event()

    async def execution(run, **kwargs):
        entered.set()
        assert release.wait(20)
        return run

    monkeypatch.setattr(runtime.acg_execution_service, "execute", execution)
    with ThreadPoolExecutor(1) as pool:
        worker = pool.submit(lambda: asyncio.run(runtime._execute_acg(old_run)))
        try:
            assert entered.wait(20)
            result = runtime.commit_graph_activation(mat_id, idempotency_key="act")
            assert result.status == "REJECTED", result.model_dump()
            assert journal.head(run_id) is None
        finally:
            release.set()
        worker.result(20)
    assert agent.calls == []


def test_old_snapshot_cross_connection_rejected(ready_boundary):
    runtime, workflow, journal, run_id, mat_id, agent = chain(ready_boundary, prepare_key="act")
    old = workflow.get_run(run_id)
    assert runtime.commit_graph_activation(mat_id, idempotency_key="act").status == "ACTIVATED_PAUSED"
    before = durable(workflow)
    with pytest.raises(ValueError, match="activation head"):
        SQLiteWorkflowStore(workflow.db_path).save_run(old)
    assert durable(workflow) == before and agent.calls == []


@pytest.mark.parametrize("damage", ["missing_journal", "missing_materialization", "forged_permit", "wrong_graph"])
def test_execution_reads_authoritative_evidence(ready_boundary, damage):
    runtime, workflow, _, run_id, _, agent, _ = activated(ready_boundary)
    with workflow._connect() as conn:
        if damage.startswith("missing"):
            table = "graph_activations" if damage == "missing_journal" else "graph_materializations"
            conn.execute(f"DELETE FROM {table}")
        else:
            run = workflow.get_run(run_id)
            if damage == "forged_permit":
                run.execution_state["graphActivation"]["executionPermit"] = True
            else:
                run.acg_blueprint["metadata"]["forged"] = True
            conn.execute("UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run_id))
    before = durable(workflow)
    with pytest.raises(ValueError, match="activation head"):
        asyncio.run(runtime._execute_acg(workflow.get_run(run_id)))
    assert durable(workflow) == before and agent.calls == []


@pytest.mark.parametrize("schema", [False, True])
def test_pre_activation_legacy_unaffected(ready_boundary, schema, monkeypatch):
    if schema:
        runtime, workflow, _, run_id, _, agent = chain(ready_boundary)
    else:
        runtime, workflow, agent, run_id, _ = ready_boundary
    run = workflow.get_run(run_id)
    run.lifecycle_message = "legacy write"
    workflow.save_run(run)
    entered = []

    async def execution(run, **kwargs):
        entered.append(run.run_id)
        return run

    monkeypatch.setattr(runtime.acg_execution_service, "execute", execution)
    asyncio.run(runtime._execute_acg(run))
    assert entered == [run_id] and agent.calls == []


def test_activation_wins_before_old_snapshot_execution(ready_boundary):
    runtime, workflow, _, run_id, mat_id, agent = chain(ready_boundary, prepare_key="act")
    old = workflow.get_run(run_id)
    assert runtime.commit_graph_activation(mat_id, idempotency_key="act").status == "ACTIVATED_PAUSED"
    before = durable(workflow)
    with pytest.raises(ValueError, match="no execution permit"):
        asyncio.run(runtime._execute_acg(old))
    assert durable(workflow) == before and agent.calls == []


def test_retry_loop_rechecks_head_after_releasing_slot(ready_boundary, monkeypatch):
    from contracts.workflow import WorkflowStatus
    runtime, workflow, _, run_id, mat_id, agent = chain(ready_boundary, prepare_key="act")
    calls = []
    original = runtime._release_execution_slot

    async def execution(run, **kwargs):
        calls.append(run.run_id)
        result = run.model_copy(deep=True)
        result.status = WorkflowStatus.RETRYING
        return result

    def release(run_id):
        original(run_id)
        assert runtime.commit_graph_activation(mat_id, idempotency_key="act").status == "ACTIVATED_PAUSED"

    monkeypatch.setattr(runtime.acg_execution_service, "execute", execution)
    monkeypatch.setattr(runtime, "_release_execution_slot", release)
    with pytest.raises(ValueError, match="no execution permit"):
        asyncio.run(runtime._execute_acg(workflow.get_run(run_id)))
    assert calls == [run_id] and agent.calls == []


@pytest.mark.parametrize("mode", ["legacy", "projection", "attached_authority"])
def test_memory_backend_compatibility_without_activation_downgrade(ready_boundary, mode, monkeypatch):
    from support.stores.memory_workflow_store import MemoryWorkflowStore
    runtime, workflow, agent, run_id, _ = ready_boundary
    memory = MemoryWorkflowStore()
    memory.save_mission(workflow.get_mission(workflow.get_run(run_id).mission_id))
    run = workflow.get_run(run_id)
    if mode == "projection":
        run.execution_state["graphActivation"] = {"status": "ACTIVATED_PAUSED", "executionPermit": None}
    if mode == "attached_authority":
        runtime.graph_activation_authority = object()
    memory.save_run(run)
    runtime.workflow_store = memory
    entered = []

    async def execution(run, **kwargs):
        entered.append(run.run_id)
        return run

    monkeypatch.setattr(runtime.acg_execution_service, "execute", execution)
    if mode == "legacy":
        asyncio.run(runtime._execute_acg(run))
        assert entered == [run_id]
    else:
        with pytest.raises(ValueError, match="activation"):
            asyncio.run(runtime._execute_acg(run))
        assert entered == []
    assert agent.calls == []
