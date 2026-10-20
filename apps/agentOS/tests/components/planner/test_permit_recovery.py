"""Permit recovery through real durable evidence and process death."""
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from contracts.workflow import WorkflowStatus
from contracts.runtime_planning import RuntimePlanningDecision
from support.stores.execution_permit_store import SQLiteExecutionPermitStore
from test_graph_handoff import _reopen


@pytest.fixture(scope="module")
def recovery_seed(tmp_path_factory):
    from test_graph_handoff import _build_prefix
    folder = tmp_path_factory.mktemp("permit-recovery-seed")
    with pytest.MonkeyPatch.context() as patch:
        rt, workflow, _, run_id, activation, _, _ = _build_prefix(folder, patch)
        prepared = rt.prepare_graph_handoff(activation, idempotency_key="recovery-seed")
        assert prepared.status == "STATE_PREPARED", prepared
        SQLiteExecutionPermitStore.upgrade_schema(workflow.db_path)
        definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
        yield folder, definition, run_id, activation, prepared.handoff_id


@pytest.fixture
def ready_handoff(recovery_seed, tmp_path):
    folder, definition, run_id, activation, handoff_id = recovery_seed
    _copy_databases(folder, tmp_path)
    rt, workflow, agent = _open(tmp_path, definition)
    return rt, workflow, agent, run_id, activation, None, None, SQLiteExecutionPermitStore(workflow.db_path), handoff_id


def _copy_databases(folder, tmp_path):
    # Copy committed databases through SQLite backup, never copy an open WAL
    # or a Run OS lock. Each test still opens independent real Runtime stores.
    for source in folder.rglob("*"):
        if not source.is_file() or source.name.startswith(".run-fence-") or source.name.endswith(("-wal", "-shm")):
            continue
        target = tmp_path / source.relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as stream:
            is_sqlite = stream.read(16) == b"SQLite format 3\x00"
        if is_sqlite:
            with sqlite3.connect(source) as original, sqlite3.connect(target) as copied:
                original.backup(copied)
        else:
            shutil.copy2(source, target)


def _open(folder, definition):
    rt, workflow, agent, _, _ = _reopen(folder, definition)
    rt.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
    class Planner:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="continue" if observation.remaining_step_ids else "complete", reason="recovery test")
    rt.runtime_planning_coordinator.planner_for_run = lambda _: Planner()
    return rt, workflow, agent


def _crash(folder, definition, run_id, cut):
    rt, _, agent = _open(folder, definition)
    original = agent.run
    async def effect(context):
        with (Path(folder) / "permit-effects.jsonl").open("a", encoding="utf8") as stream:
            stream.write(json.dumps({"step": context.step.step_id}) + "\n")
        if cut == "uncertain":
            os._exit(72)
        return await original(context)
    agent.run = effect
    def after_checkpoint():
        _, state = rt.checkpoint_store.load_latest(run_id=run_id)
        if "B" in state["completedStepIds"]:
            os._exit(71)
    rt.acg_state_persistence.after_checkpoint_hook = after_checkpoint
    asyncio.run(rt.execute_prepared_run(run_id))
    os._exit(79)


def _dead_worker(ready, cut="checkpoint"):
    rt, workflow, _, run_id, _, _, _, _, handoff_id = ready
    receipt = rt.issue_execution_permit(handoff_id, idempotency_key="recover-permit")
    assert receipt.status == "ISSUED", receipt
    definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
    child = multiprocessing.get_context("spawn").Process(
        target=_crash, args=(str(workflow.db_path.parent), definition, run_id, cut))
    child.start()
    child.join(30)
    if child.is_alive():
        child.terminate(); child.join(5)
        pytest.fail("Permit crash worker exceeded 30 seconds")
    assert child.exitcode == (71 if cut == "checkpoint" else 72)
    return _open(workflow.db_path.parent, definition)


@pytest.mark.freeze_gate
@pytest.mark.slow_multiprocess
def test_committed_checkpoint_before_run_ack_recovers_without_repeating_B(ready_handoff):
    rt, workflow, agent = _dead_worker(ready_handoff)
    run_id = ready_handoff[3]
    before = workflow.get_run(run_id)
    head, state = rt.checkpoint_store.load_latest(run_id=run_id)
    assert head != before.execution_state["checkpointId"]
    assert state["completedStepIds"] == ["A", "B"]
    with pytest.raises(ValueError):
        rt.execution_permit_authority.assert_dispatchable(before)
    reconciled = rt.reconcile_execution_checkpoint(run_id)
    assert reconciled.execution_state["checkpointId"] == head
    assert rt.reconcile_execution_checkpoint(run_id) == reconciled
    with pytest.raises(ValueError):
        workflow.save_run(before)
    result = asyncio.run(rt.execute_prepared_run(run_id))
    assert result.status == WorkflowStatus.COMPLETED, (result.error, result.execution_state.get("planningLoop"), agent.calls)
    assert agent.calls == ["C", "D"]
    effects = workflow.db_path.parent / "permit-effects.jsonl"
    assert [json.loads(line)["step"] for line in effects.read_text(encoding="utf8").splitlines()] == ["B"]


@pytest.mark.freeze_gate
@pytest.mark.slow_multiprocess
@pytest.mark.parametrize("cut", ["uncertain", "receipt", "checkpoint", "revoked", "cancel", "operator_input"])
def test_uncertain_or_damaged_recovery_has_no_execution_right(ready_handoff, monkeypatch, cut):
    rt, workflow, agent = _dead_worker(ready_handoff, "uncertain" if cut == "uncertain" else "checkpoint")
    run_id = ready_handoff[3]
    before = workflow.get_run(run_id)
    if cut == "receipt":
        with rt.execution_value_store._connection:
            rt.execution_value_store._connection.execute(
                "DELETE FROM acg_node_executions WHERE run_id=? AND json_extract(payload_json,'$.stepId')='B'", (run_id,))
    elif cut == "checkpoint":
        head, state = rt.checkpoint_store.load_latest(run_id=run_id)
        state["completedStepIds"].append("D")
        with rt.checkpoint_store._connection:
            rt.checkpoint_store._connection.execute("UPDATE acg_execution_checkpoints SET state_json=? WHERE checkpoint_id=?", (json.dumps(state), head))
    elif cut == "revoked":
        from contracts.mission_semantic import SemanticPrincipal
        rt.semantic_principal_provider = lambda: SemanticPrincipal(actorId="revoked", tenantId="tenant")
    elif cut == "cancel":
        rt.cancel(run_id)
        before = workflow.get_run(run_id)
    elif cut == "operator_input":
        import runtime.permit_recovery as recovery
        original = recovery._evidence
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            current = workflow.get_run(run_id)
            current.input["operatorNote"] = "arrived during reconciliation"
            workflow.save_run(current)
            return result
        monkeypatch.setattr(recovery, "_evidence", changed)
    with pytest.raises(ValueError):
        rt.reconcile_execution_checkpoint(run_id)
    if cut == "uncertain":
        with pytest.raises(ValueError):
            rt._claim_acg_execution(before)
    after = workflow.get_run(run_id)
    if cut == "operator_input":
        assert after.execution_state["checkpointId"] == before.execution_state["checkpointId"]
        assert after.input["operatorNote"] == "arrived during reconciliation"
    else:
        assert after == before
    assert agent.calls == []


@pytest.mark.freeze_gate
@pytest.mark.parametrize("revoked", [False, True])
def test_permit_failure_review_retry_uses_new_attempt_after_reopen(ready_handoff, monkeypatch, revoked):
    from adapters.agent_invocation import AgentInvocationAdapter
    from service.agents.registry import AgentNotFound
    from contracts.workflow import ReviewDecision
    from contracts.mission_semantic import SemanticPrincipal
    rt, workflow, agent, run_id, _, _, _, permits, handoff_id = ready_handoff
    issued = rt.issue_execution_permit(handoff_id, idempotency_key="retry-permit")
    assert issued.status == "ISSUED"
    record = permits.get_permit(issued.permit_id)
    class Planner:
        def decide_runtime(self, *, observation, task_plan):
            action = "wait" if observation.failed_step_ids else "continue" if observation.remaining_step_ids else "complete"
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action=action, reason="retry review")
    rt.runtime_planning_coordinator.planner_for_run = lambda _: Planner()
    original = AgentInvocationAdapter.invoke
    failed = []
    async def missing_registry(self, *, context, agent=None):
        if context.step.step_id == "B" and not failed:
            failed.append(True)
            registry = self.registry
            class Missing:
                def resolve_by_id(self, agent_id):
                    raise AgentNotFound(agent_id)
            self.registry = Missing()
            try:
                return await original(self, context=context, agent=agent)
            finally:
                self.registry = registry
        return await original(self, context=context, agent=agent)
    monkeypatch.setattr(AgentInvocationAdapter, "invoke", missing_registry)
    paused = asyncio.run(rt.execute_prepared_run(run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW, paused.error
    assert agent.calls == []
    receipts = rt.execution_value_store.list_node_commits(run_id=run_id)
    assert all(item["stage"] == "prepared" for item in receipts if ":B:" in item["commitId"])
    old_attempts = [item for item in rt.identity_lifecycle.repositories.attempts.list_for_run(run_id)
                    if item.status.value == "failed"]
    assert len(old_attempts) == 1
    old_execution = rt.identity_lifecycle.repositories.step_executions.list_for_attempt(old_attempts[0].attempt_id)[0]
    from contracts.execution import NodeExecutionRecord, NodeExecutionPhase
    row = rt.execution_value_store._connection.execute(
        "SELECT payload_json FROM acg_node_executions WHERE json_extract(payload_json,'$.attemptId')=?",
        (old_attempts[0].attempt_id,)).fetchone()
    failed_operation = NodeExecutionRecord.model_validate_json(row[0])
    # Reject the failed strategic barrier; retry is a separate existing operator
    # command, not a Review approval that grants another Permit.
    rejected = asyncio.run(rt.apply_review(ReviewDecision(runId=run_id, stepId=paused.current_step_id,
                                                       decision="rejected", operationId="reject-failed-plan")))
    assert rejected.status == WorkflowStatus.FAILED
    assert permits.get_permit(issued.permit_id) == record
    retry = rt.prepare_single_step_retry(run_id, "B", reuse_source_run=True,
                                        idempotency_key="operator-retry", idempotency_fingerprint="retry-B")
    assert retry.execution_state["executionPermitId"] == record.permit_id
    assert retry.execution_state["executionGeneration"] == record.attempt_generation
    definition = rt._workflow_for_run(retry).model_dump(mode="json", by_alias=True)
    reopened, saved, new_agent = _open(workflow.db_path.parent, definition)
    if revoked:
        reopened.semantic_principal_provider = lambda: SemanticPrincipal(actorId="revoked", tenantId="tenant")
        with pytest.raises(ValueError):
            asyncio.run(reopened.execute_prepared_run(run_id))
        assert new_agent.calls == []
        return
    result = asyncio.run(reopened.execute_prepared_run(run_id))
    assert result.status == WorkflowStatus.COMPLETED, (result.error, result.execution_state.get("planningLoop"))
    assert new_agent.calls == ["B", "C", "D"]
    repos = reopened.identity_lifecycle.repositories
    assert repos.attempts.get(old_attempts[0].attempt_id) == old_attempts[0]
    assert repos.step_executions.get(old_execution.step_execution_id) == old_execution
    with pytest.raises(ValueError, match="terminal"):
        reopened.execution_value_store.transition_node_execution(failed_operation.model_copy(update={
            "phase": NodeExecutionPhase.COMMITTED, "commit_id": failed_operation.operation_id}))
    new_attempts = [a for a in repos.attempts.list_for_run(run_id) if a.task_id == old_attempts[0].task_id and a.status.value == "succeeded"]
    assert len(new_attempts) == 1 and new_attempts[0].attempt_id != old_attempts[0].attempt_id
    assert repos.step_executions.list_for_attempt(new_attempts[0].attempt_id)[0].step_execution_id != old_execution.step_execution_id


@pytest.mark.freeze_gate
def test_existing_node_review_approval_preserves_permit_and_deferred_memory(ready_handoff, monkeypatch):
    from contracts.workflow import ReviewDecision
    rt, workflow, agent, run_id, _, _, _, permits, handoff_id = ready_handoff
    issued = rt.issue_execution_permit(handoff_id, idempotency_key="node-review")
    assert issued.status == "ISSUED", issued
    record = permits.get_permit(issued.permit_id)
    original = agent.run
    async def high_risk(context):
        output = await original(context)
        return output.model_copy(update={"risk_level": "high"}) if context.step.step_id == "B" else output
    monkeypatch.setattr(agent, "run", high_risk)
    paused = asyncio.run(rt.execute_prepared_run(run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW
    assert agent.calls == ["B"]
    result = asyncio.run(rt.apply_review(ReviewDecision(runId=run_id, stepId="B", decision="approved", operationId="approve-B")))
    assert result.status == WorkflowStatus.COMPLETED, result.error
    assert agent.calls == ["B", "C", "D"]
    assert permits.get_permit(issued.permit_id) == record
