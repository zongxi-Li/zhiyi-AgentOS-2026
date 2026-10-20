"""Independent adversarial checks for the B2 execution boundary."""
import asyncio
from contextlib import contextmanager
import json
import multiprocessing

import pytest

from contracts.mission_semantic import SemanticPrincipal
from contracts.runtime_planning import RuntimePlanningDecision
from runtime.live_events import runtime_event_broker
from test_execution_permit import ready_handoff
from support.stores.execution_permit_store import SQLiteExecutionPermitStore


def _replay_child(folder, definition, handoff_id, queue):
    from test_graph_handoff import _reopen
    rt, workflow, agent, _, _ = _reopen(folder, definition)
    rt.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
    receipt = rt.issue_execution_permit(handoff_id, idempotency_key="audit-saga")
    queue.put((receipt.model_dump(mode="json"), agent.calls))


def _continue(rt):
    class Planner:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="continue", reason="audit")
    rt.runtime_planning_coordinator.planner_for_run = lambda _: Planner()


@pytest.mark.freeze_gate
def test_dispatch_rejects_unacknowledged_checkpoint_head(ready_handoff):
    rt, workflow, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    assert rt.issue_execution_permit(handoff_id, idempotency_key="audit-head").status == "ISSUED"
    _, state = rt.checkpoint_store.load_latest(run_id=run_id)
    rt.checkpoint_store.save(run_id=run_id, checkpoint_id="foreign-head", state=state,
                             expected_version=rt.checkpoint_store.latest_version(run_id=run_id))
    with pytest.raises(ValueError):
        rt.execution_permit_authority.assert_dispatchable(workflow.get_run(run_id))
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
@pytest.mark.parametrize("mutation", ["pointer", "missing", "corrupt", "generation", "projection"])
def test_checkpoint_and_projection_damage_fail_closed(ready_handoff, mutation):
    rt, workflow, agent, run_id, _, _, _, permits, handoff_id = ready_handoff
    issued = rt.issue_execution_permit(handoff_id, idempotency_key="audit-damage")
    assert issued.status == "ISSUED"
    record = permits.get_permit(issued.permit_id)
    run = workflow.get_run(run_id)
    if mutation in {"pointer", "projection"}:
        if mutation == "pointer":
            run.execution_state["checkpointId"] = record.source_checkpoint_id
        else:
            run.execution_state["graphActivation"]["executionPermit"]["checkpointVersion"] += 1
        try:
            workflow.save_run(run)
        except ValueError:
            assert agent.calls == ["A"]
            return
    else:
        conn = rt.checkpoint_store._connection
        if mutation == "missing":
            conn.execute("DELETE FROM acg_execution_checkpoints WHERE checkpoint_id=?", (record.promoted_checkpoint_id,))
        else:
            payload = rt.checkpoint_store.load(run_id=run_id, checkpoint_id=record.promoted_checkpoint_id)
            payload["executionGeneration" if mutation == "generation" else "completedStepIds"] = (
                "old-generation" if mutation == "generation" else ["A", "B"])
            conn.execute("UPDATE acg_execution_checkpoints SET state_json=? WHERE checkpoint_id=?",
                         (json.dumps(payload), record.promoted_checkpoint_id))
        conn.commit()
    with pytest.raises((ValueError, KeyError)):
        rt.execution_permit_authority.assert_dispatchable(workflow.get_run(run_id))
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
@pytest.mark.parametrize("cut", ["identity_partial", pytest.param("workflow_rollback", marks=pytest.mark.slow_multiprocess), "ack_lost", "revoked"])
def test_saga_reopens_with_original_key_without_execution(ready_handoff, monkeypatch, cut):
    rt, workflow, agent, run_id, _, _, _, permits, handoff_id = ready_handoff
    if cut == "identity_partial":
        original = rt.identity_lifecycle._ensure_blueprint
        def fail(*args, **kwargs):
            raise RuntimeError("audit after TaskPlan persisted")
        monkeypatch.setattr(rt.identity_lifecycle, "_ensure_blueprint", fail)
    elif cut == "workflow_rollback":
        original = permits._issue
        def fail(record):
            original(record)
            raise RuntimeError("audit rollback after ISSUED update")
        monkeypatch.setattr(permits, "_issue", fail)
    elif cut == "ack_lost":
        original = permits._transaction
        @contextmanager
        def fail():
            with original():
                yield
            if permits.permit_by_key("audit-saga").status == "ISSUED":
                raise RuntimeError("audit committed but ACK lost")
        monkeypatch.setattr(permits, "_transaction", fail)
    else:
        original = rt.identity_lifecycle.on_execution_permit_blueprint_promoted
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            rt.semantic_principal_provider = lambda: SemanticPrincipal(actorId="revoked", tenantId="tenant")
        monkeypatch.setattr(rt.identity_lifecycle, "on_execution_permit_blueprint_promoted", fail)
    first = rt.issue_execution_permit(handoff_id, idempotency_key="audit-saga")
    assert first.status == "REJECTED", first
    preparing = permits.permit_by_key("audit-saga")
    assert preparing.status == ("ISSUED" if cut == "ack_lost" else "PREPARING")
    assert agent.calls == ["A"]
    if cut != "ack_lost":
        with pytest.raises(ValueError):
            rt._claim_acg_execution(workflow.get_run(run_id))
    assert rt.issue_execution_permit(handoff_id, idempotency_key="different-key").code == "DUPLICATE_CONFLICT"
    if cut == "revoked":
        assert rt.issue_execution_permit(handoff_id, idempotency_key="audit-saga").status == "REJECTED"
        return
    from test_graph_handoff import _reopen
    definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
    if cut == "workflow_rollback":
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        child = ctx.Process(target=_replay_child, args=(str(workflow.db_path.parent), definition, handoff_id, queue))
        child.start()
        child.join(30)
        if child.is_alive():
            child.terminate()
            child.join(5)
            pytest.fail("independent Permit recovery process exceeded 30 seconds")
        assert child.exitcode == 0
        receipt, calls = queue.get(timeout=3)
        assert receipt["status"] == "ISSUED" and calls == []
    reopened, reopened_workflow, _, _, _ = _reopen(workflow.db_path.parent, definition)
    reopened.enable_execution_permit(SQLiteExecutionPermitStore(reopened_workflow.db_path))
    result = reopened.issue_execution_permit(handoff_id, idempotency_key="audit-saga")
    assert result.status == ("IDEMPOTENT_REPLAY" if cut in {"ack_lost", "workflow_rollback"} else "ISSUED"), result
    reopened.execution_permit_authority.assert_dispatchable(reopened_workflow.get_run(run_id))
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
def test_revocation_after_node_started_prevents_agent_call(ready_handoff, monkeypatch):
    rt, _, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    assert rt.issue_execution_permit(handoff_id, idempotency_key="audit-last-check").status == "ISSUED"
    _continue(rt)
    original = runtime_event_broker.publish

    async def revoke(run_id, event):
        await original(run_id, event)
        if event.event_type == "node.started":
            rt.semantic_principal_provider = lambda: SemanticPrincipal(actorId="revoked", tenantId="tenant")

    monkeypatch.setattr(runtime_event_broker, "publish", revoke)
    try:
        asyncio.run(rt.execute_prepared_run(run_id))
    except ValueError:
        pass
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
@pytest.mark.parametrize("mutation", ["head", "binding", "cancel", "identity"])
def test_late_durable_identity_change_prevents_invocation(ready_handoff, monkeypatch, mutation):
    rt, workflow, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    assert rt.issue_execution_permit(handoff_id, idempotency_key="audit-late").status == "ISSUED"
    _continue(rt)
    original = runtime_event_broker.publish

    async def change(run_id, event):
        await original(run_id, event)
        if event.event_type != "node.started":
            return
        if mutation == "head":
            with workflow._connect() as conn:
                conn.execute("UPDATE graph_activation_heads SET active_graph_version=99 WHERE run_id=?", (run_id,))
        elif mutation == "binding":
            run = workflow.get_run(run_id)
            run.execution_state["executionBindings"][event.node_id]["resourceId"] = "forged-resource"
            workflow.save_run(run)
        elif mutation == "cancel":
            rt._signal_run_cancellation(run_id)
        else:
            repos = rt.identity_lifecycle.repositories
            from domain.identity_graph.resolver import IdentityResolver
            current = repos.attempts.get(event.attempt_id)
            other = IdentityResolver(repos).resolve_semantic_task(
                blueprint_id=repos.runs.get(run_id).blueprint_id, acg_node_id="A")
            assert current.task_id != other.task_id
            with repos.storage.transaction() as conn:
                conn.execute("UPDATE attempts SET task_id=? WHERE attempt_id=?", (other.task_id, event.attempt_id))

    monkeypatch.setattr(runtime_event_broker, "publish", change)
    try:
        asyncio.run(rt.execute_prepared_run(run_id))
    except ValueError:
        pass
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
@pytest.mark.parametrize("revoke", [False, True])
def test_transport_retry_rechecks_authority_without_false_receipt(ready_handoff, monkeypatch, revoke):
    rt, _, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    assert rt.issue_execution_permit(handoff_id, idempotency_key="audit-retry").status == "ISSUED"
    _continue(rt)
    from adapters.agent_invocation import AgentInvocationAdapter, AgentInvocationError
    original = AgentInvocationAdapter.invoke
    calls = []
    class Missing:
        def resolve_by_id(self, agent_id):
            raise KeyError(agent_id)
    async def invoke(adapter, *, context, agent=None):
        calls.append(context.step.step_id)
        if len(calls) == 1:
            # A genuine adapter resolution failure proves no Agent invocation.
            # A generic exception from inside Agent.run is deliberately unsafe.
            registry = adapter.registry
            adapter.registry = Missing()
            try:
                return await original(adapter, context=context, agent=agent)
            except AgentInvocationError as exc:
                exc.retryable = True
                if revoke:
                    rt.semantic_principal_provider = lambda: SemanticPrincipal(actorId="revoked", tenantId="tenant")
                raise
            finally:
                adapter.registry = registry
        return await original(adapter, context=context, agent=agent)
    monkeypatch.setattr(AgentInvocationAdapter, "invoke", invoke)
    try:
        asyncio.run(rt.execute_prepared_run(run_id))
    except ValueError:
        pass
    if revoke:
        assert calls == ["B"] and agent.calls == ["A"]
        records = [item for item in rt.execution_value_store.list_node_commits(run_id=run_id) if ":B:" in item["commitId"]]
        assert records and all(item["stage"] == "prepared" and not item.get("outputRef") for item in records)
    else:
        assert calls[:2] == ["B", "B"]
        assert agent.calls == ["A", "B", "C", "D"]
