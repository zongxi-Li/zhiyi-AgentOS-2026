"""Independent authority counterexamples and controlled process interleavings."""
import asyncio
from contextlib import contextmanager
import multiprocessing
import os
import json
from types import SimpleNamespace

import pytest

from adapters.agent_invocation import AgentInvocationError
from contracts.workflow import WorkflowStatus
from runtime.permit_recovery import assert_settled_operations
from test_permit_recovery import ready_handoff, recovery_seed, _open, _dead_worker


@pytest.mark.freeze_gate
def test_not_invoked_proof_is_adapter_context_bound_and_single_use():
    from adapters.agent_invocation import AgentInvocationAdapter
    from service.agents.registry import AgentNotFound
    class Missing:
        def resolve_by_id(self, agent_id):
            raise AgentNotFound(agent_id)
    adapter, other = AgentInvocationAdapter(registry=Missing()), AgentInvocationAdapter(registry=Missing())
    context = SimpleNamespace(step=SimpleNamespace(step_id="B", agent_name="agent", capability="analysis"))
    agent = SimpleNamespace(profile=SimpleNamespace(agent_id="agent", agent_name="agent"))
    with pytest.raises(AgentInvocationError) as captured:
        asyncio.run(adapter.invoke(context=context, agent=agent))
    error = captured.value
    assert not other.consume_not_invoked(error, context)
    assert adapter.consume_not_invoked(error, context)
    assert not adapter.consume_not_invoked(error, context)
    with pytest.raises(AgentInvocationError) as second:
        asyncio.run(adapter.invoke(context=context, agent=agent))
    assert not adapter.consume_not_invoked(second.value, SimpleNamespace(step=context.step))


@pytest.mark.freeze_gate
@pytest.mark.slow_multiprocess
def test_missing_forged_or_old_generation_execution_record_rejects(ready_handoff):
    rt, workflow, agent = _dead_worker(ready_handoff)
    run_id = ready_handoff[3]
    before = workflow.get_run(run_id)
    conn = rt.execution_value_store._connection
    key, original = conn.execute("SELECT operation_id,payload_json FROM acg_node_executions WHERE run_id=? AND json_extract(payload_json,'$.stepId')='B'", (run_id,)).fetchone()
    receipt = conn.execute("SELECT payload_json FROM acg_node_commits WHERE commit_id=?", (key,)).fetchone()[0]
    for mutation in ("missing", "attempt", "generation"):
        with conn:
            if mutation == "missing":
                conn.execute("DELETE FROM acg_node_executions WHERE operation_id=?", (key,))
            else:
                node = json.loads(original)
                node["attemptId" if mutation == "attempt" else "executionInstanceId"] = (
                    "attempt_000000000000" if mutation == "attempt" else "agen_old:" + node["executionInstanceId"])
                conn.execute("UPDATE acg_node_executions SET payload_json=? WHERE operation_id=?", (json.dumps(node), key))
                if mutation == "generation":
                    changed = json.loads(receipt)
                    changed["nodeExecution"] = node
                    conn.execute("UPDATE acg_node_commits SET payload_json=? WHERE commit_id=?", (json.dumps(changed), key))
        with pytest.raises(ValueError):
            rt.reconcile_execution_checkpoint(run_id)
        assert workflow.get_run(run_id) == before and agent.calls == []
        with conn:
            if mutation == "missing":
                # Restore the original row through its original full schema.
                columns = {row[1] for row in conn.execute("PRAGMA table_info(acg_node_executions)")}
                assert "payload_json" in columns
                from contracts.execution import NodeExecutionRecord
                rt.execution_value_store.transition_node_execution(NodeExecutionRecord.model_validate_json(original))
            else:
                conn.execute("UPDATE acg_node_executions SET payload_json=? WHERE operation_id=?", (original, key))
            conn.execute("UPDATE acg_node_commits SET payload_json=? WHERE commit_id=?", (receipt, key))


@pytest.mark.freeze_gate
@pytest.mark.parametrize("kind", ["forged", "forged_retryable", "plain_retryable"])
def test_agent_cannot_mint_not_invoked_evidence(ready_handoff, monkeypatch, kind):
    rt, workflow, agent, run_id, _, _, _, _, handoff = ready_handoff
    assert rt.issue_execution_permit(handoff, idempotency_key="forged-proof").status == "ISSUED"
    original = agent.run
    async def invoked(context):
        await original(context)  # Agent has actually been entered.
        error = (RuntimeError("unsettled Agent exception") if kind == "plain_retryable" else
                 AgentInvocationError("AGENT_NOT_IN_SCOPE", context.step.step_id, "untrusted exception"))
        error.not_invoked = True
        error.retryable = kind != "forged"
        raise error
    monkeypatch.setattr(agent, "run", invoked)
    result = asyncio.run(rt.execute_prepared_run(run_id))
    assert agent.calls == ["B"]
    assert result.status == WorkflowStatus.WAITING_REVIEW
    with pytest.raises(ValueError):
        assert_settled_operations(rt, workflow.get_run(run_id))


def _receipt_crash(folder, definition, run_id):
    from runtime.live_events import runtime_event_broker
    rt, _, _ = _open(folder, definition)
    original = runtime_event_broker.publish
    async def die(run_id, event):
        if event.event_type == "node.completed" and event.node_id == "B":
            os._exit(73)  # Receipt committed, no wrapper success/Run projection.
        await original(run_id, event)
    runtime_event_broker.publish = die
    asyncio.run(rt.execute_prepared_run(run_id))
    os._exit(79)


def _join(child, expected):
    child.join(30)
    if child.is_alive():
        child.terminate(); child.join(5)
        pytest.fail("audit worker exceeded 30 seconds")
    assert child.exitcode == expected


@pytest.mark.freeze_gate
@pytest.mark.slow_multiprocess
def test_receipt_without_workflow_completion_is_an_explicit_barrier(ready_handoff):
    rt, workflow, _, run_id, _, _, _, _, handoff = ready_handoff
    assert rt.issue_execution_permit(handoff, idempotency_key="receipt-cut").status == "ISSUED"
    definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
    child = multiprocessing.get_context("spawn").Process(target=_receipt_crash,
        args=(str(workflow.db_path.parent), definition, run_id))
    child.start(); _join(child, 73)
    reopened, store, agent = _open(workflow.db_path.parent, definition)
    before = store.get_run(run_id)
    assert "B" not in before.completed_step_ids
    assert any(":B:" in item["commitId"] and item["stage"] == "committed"
               for item in reopened.execution_value_store.list_node_commits(run_id=run_id))
    with pytest.raises(ValueError):
        reopened.reconcile_execution_checkpoint(run_id)
    assert store.get_run(run_id) == before and agent.calls == []


def _reconcile_worker(folder, definition, run_id, entered, release, committed, results, cut):
    import runtime.permit_recovery as recovery
    rt, workflow, _ = _open(folder, definition)
    original_evidence = recovery._evidence
    paused = False
    def pause(*args, **kwargs):
        nonlocal paused
        value = original_evidence(*args, **kwargs)
        if not paused:
            paused = True
            entered.set()
            assert release.wait(20)
        return value
    recovery._evidence = pause
    if cut == "ack":
        original_transaction = rt.execution_permit_authority.store._transaction
        @contextmanager
        def lose_ack():
            with original_transaction():
                yield
            assert workflow.get_run(run_id).execution_state["checkpointId"] == rt.checkpoint_store.load_latest(run_id=run_id)[0]
            committed.set()
            os._exit(74)
        rt.execution_permit_authority.store._transaction = lose_ack
    try:
        rt.reconcile_execution_checkpoint(run_id)
        results.put("unexpected success")
    except ValueError as exc:
        results.put(str(exc))


@pytest.mark.freeze_gate
@pytest.mark.slow_multiprocess
@pytest.mark.parametrize("cut", ["ack", "input", "cancel"])
def test_reconciliation_real_fence_cas_and_commit_ack_window(ready_handoff, cut):
    rt, workflow, agent = _dead_worker(ready_handoff)
    run_id = ready_handoff[3]
    before = workflow.get_run(run_id)
    definition = rt._workflow_for_run(before).model_dump(mode="json", by_alias=True)
    head = rt.checkpoint_store.load_latest(run_id=run_id)[0]
    ctx = multiprocessing.get_context("spawn")
    entered, release, committed, results = ctx.Event(), ctx.Event(), ctx.Event(), ctx.Queue()
    child = ctx.Process(target=_reconcile_worker,
        args=(str(workflow.db_path.parent), definition, run_id, entered, release, committed, results, cut))
    child.start()
    try:
        assert entered.wait(20), "worker did not consume source evidence"
        # A real independent process currently holds the same normalized OS fence.
        with pytest.raises(ValueError, match="active execution|activation"):
            rt.reconcile_execution_checkpoint(run_id)
        if cut == "input":
            changed = workflow.get_run(run_id)
            changed.input["operatorNote"] = "changed after evidence read"
            workflow.save_run(changed)
        elif cut == "cancel":
            rt.cancel(run_id)
    finally:
        release.set()
        _join(child, 74 if cut == "ack" else 0)
    after = workflow.get_run(run_id)
    if cut == "ack":
        assert committed.is_set() and after.execution_state["checkpointId"] == head
        assert after.runtime_revision == before.runtime_revision + 1
        assert rt.reconcile_execution_checkpoint(run_id) == after  # no duplicate acknowledgement
        from contracts.mission_semantic import SemanticPrincipal
        owner = rt.semantic_principal_provider
        rt.semantic_principal_provider = lambda: SemanticPrincipal(actorId="revoked", tenantId="tenant")
        with pytest.raises(ValueError):
            asyncio.run(rt.execute_prepared_run(run_id))
        rt.semantic_principal_provider = owner
        rt.cancel(run_id)
        assert asyncio.run(rt.execute_prepared_run(run_id)).status == WorkflowStatus.CANCELLED
    else:
        assert "Run changed" in results.get(timeout=3)
        assert after.execution_state["checkpointId"] == before.execution_state["checkpointId"]
        if cut == "input":
            assert after.input["operatorNote"] == "changed after evidence read"
        else:
            assert after.status == WorkflowStatus.CANCELLED
    assert agent.calls == []
