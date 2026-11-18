"""Restart repair closes local task identity without settling external effects."""
import asyncio

import pytest

from adapters.model.native import NativeGeneralAgent
from components.resource.runtime.embedded_runtime import EMBEDDED_AGENTS_RUNTIME_ID
from contracts.resource import ExecutionBinding, RuntimeKind
from contracts.workflow import StepStatus, WorkflowStatus, WorkflowStep
from domain.models import AttemptStatus, RunStatus, StepExecutionStatus
from runtime import IdentityProjectionReconciler
from support.run_execution_fence import acquire_run_fence
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from test_identity_projection_lifecycle import _runtime


def _interrupted_native(tmp_path, *, terminal=False, remote=False):
    runtime, identity, bridge, mission = _runtime(workflow_store=SQLiteWorkflowStore(tmp_path / "workflows.sqlite3"))
    agent = NativeGeneralAgent()
    runtime.agent_registry.register(agent)
    _, run = runtime.prepare_run(mission.mission_id)
    task = identity.repositories.semantic_tasks.list_for_mission(mission.mission_id)[0]
    attempt = identity.create_attempt(run_id=run.run_id, task_id=task.task_id)
    binding = ExecutionBinding(bindingId="binding:restart", runId=run.run_id, stepId="analyse",
        attemptId=attempt.attempt_id, resourceId="remote-runtime" if remote else EMBEDDED_AGENTS_RUNTIME_ID,
        runtimeKind=RuntimeKind.EXECUTION_BACKEND, snapshotVersion=1, leaseId="lease:restart",
        agentRegistration=runtime.agent_registry.registration_for(agent),
        agentLeaseId="lease:restart:agent", agentLeaseVersion=1)
    bridge.record_scheduling_binding(attempt_id=attempt.attempt_id, runtime_binding=binding,
        agent_id="native_general_agent", model_id="restart-test")
    execution = bridge.start_execution(identity.create_context(run.run_id), input={"nodeId": "analyse"})
    run.get_step("analyse").capability = "analysis"
    run.get_step("analyse").agent_name = agent.profile.agent_name
    run.get_step("analyse").status = StepStatus.FAILED if terminal else StepStatus.RUNNING
    run.status = WorkflowStatus.FAILED if terminal else WorkflowStatus.RUNNING
    run.execution_state["executionBindings"] = {"analyse": binding.model_dump(by_alias=True, mode="json")}
    run.execution_state.pop("planningLoop", None)
    run.active_step_ids = [] if terminal else ["analyse"]
    run.execution_state["activeStepIds"] = ["analyse"]
    # Existing completed references are opaque and must survive cleanup exactly.
    run.execution_state["outputRefs"] = {"kept": "output:already-committed"}
    run.execution_state["contextRefs"] = {"kept": "context:already-committed"}
    run.completed_step_ids = ["kept"]
    run.error = {"code": "dispatch_recovery_blocked", "message": "Previous process interrupted"} if terminal else None
    runtime.workflow_store.save_run(run)
    if terminal:
        identity.repositories.runs.update_status(run.run_id, RunStatus.FAILED)
    return runtime, identity, bridge, run, attempt, execution


@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("capability", ["analysis", "requirement_analysis", "architecture_design", "artifact_generation"])
def test_restart_closes_native_session_and_repeated_startup_is_idempotent(tmp_path, terminal, capability):
    runtime, identity, bridge, run, attempt, execution = _interrupted_native(tmp_path, terminal=terminal)
    try:
        run.get_step("analyse").capability = capability
        runtime.workflow_store.save_run(run)
        if terminal:
            report = IdentityProjectionReconciler(bridge).reconcile_workflow_store(runtime.workflow_store, audit_existing=False)
            assert report.failures == []
            assert report.examined_runs == 1  # Run itself was already failed.
        asyncio.run(runtime.close_orphaned_runs(limit=1))
        saved = runtime.get_status(run.run_id)
        assert saved.status is WorkflowStatus.FAILED
        assert identity.repositories.attempts.get(attempt.attempt_id).status is AttemptStatus.FAILED
        assert identity.repositories.step_executions.get(execution.step_execution_id).status is StepExecutionStatus.FAILED
        assert saved.execution_state["taskSettlement"][attempt.attempt_id] == {
            "taskState": "ended", "outcome": "failed", "leaseState": "not_owned",
            "leaseId": "lease:restart", "agentLeaseId": "lease:restart:agent",
            "trigger": "interrupted_after_restart", "source": "run-execution-fence.v1",
        }
        assert not saved.active_step_ids and not saved.execution_state["activeStepIds"]
        assert saved.completed_step_ids == ["kept"]
        assert saved.execution_state["outputRefs"] == run.execution_state["outputRefs"]
        assert saved.execution_state["contextRefs"] == run.execution_state["contextRefs"]
        assert saved.acg_blueprint == run.acg_blueprint
        assert runtime.workflow_store.list_outbox() == []
        asyncio.run(runtime.close_orphaned_runs(limit=1))
        assert runtime.get_status(run.run_id) == saved
    finally:
        identity.close()


@pytest.mark.parametrize("path", ["information_retrieval", "industrial_capacity_analysis", "workset", "unregistered_capability"])
def test_restart_does_not_apply_single_session_settlement_to_other_native_paths(tmp_path, path):
    runtime, identity, _, run, attempt, _ = _interrupted_native(tmp_path, terminal=True)
    try:
        step = run.get_step("analyse")
        if path == "workset":
            step.input["workset"] = {"sourceManifestRefs": ["material"]}
        else:
            step.capability = path
        runtime.workflow_store.save_run(run)
        asyncio.run(runtime.close_orphaned_runs())
        saved = runtime.get_status(run.run_id)
        assert attempt.attempt_id not in saved.execution_state.get("taskSettlement", {})
        assert identity.repositories.attempts.get(attempt.attempt_id).status is AttemptStatus.RUNNING
    finally:
        identity.close()


@pytest.mark.parametrize("terminal", [False, True])
def test_live_executor_fence_blocks_restart_identity_and_settlement_repair(tmp_path, terminal):
    runtime, identity, bridge, run, attempt, execution = _interrupted_native(tmp_path, terminal=terminal)
    try:
        with acquire_run_fence(runtime.workflow_store.db_path, run.run_id):
            if terminal:
                report = IdentityProjectionReconciler(bridge).reconcile_workflow_store(runtime.workflow_store, audit_existing=False)
                assert report.failures == []
            assert asyncio.run(runtime.close_orphaned_runs()) == []
            saved = runtime.get_status(run.run_id)
            assert saved.status is run.status
            assert attempt.attempt_id not in saved.execution_state.get("taskSettlement", {})
            assert identity.repositories.attempts.get(attempt.attempt_id).status is AttemptStatus.RUNNING
            assert identity.repositories.step_executions.get(execution.step_execution_id).status is StepExecutionStatus.RUNNING
    finally:
        identity.close()


def test_restart_never_claims_a_remote_session_has_exited(tmp_path):
    runtime, identity, _, run, attempt, _ = _interrupted_native(tmp_path, terminal=True, remote=True)
    try:
        asyncio.run(runtime.close_orphaned_runs())
        saved = runtime.get_status(run.run_id)
        assert attempt.attempt_id not in saved.execution_state.get("taskSettlement", {})
        assert identity.repositories.attempts.get(attempt.attempt_id).status is AttemptStatus.RUNNING
    finally:
        identity.close()


def test_restart_preserves_existing_unknown_settlement(tmp_path):
    runtime, identity, _, run, attempt, _ = _interrupted_native(tmp_path, terminal=True)
    try:
        existing = {"taskState": "ended", "outcome": "unknown", "leaseState": "retained_unknown"}
        run.execution_state["taskSettlement"] = {attempt.attempt_id: existing}
        runtime.workflow_store.save_run(run)
        asyncio.run(runtime.close_orphaned_runs())
        assert runtime.get_status(run.run_id).execution_state["taskSettlement"][attempt.attempt_id] == existing
    finally:
        identity.close()


@pytest.mark.parametrize("terminal", [False, True])
def test_failure_convergence_closes_task_but_preserves_unsettled_tool_wal(tmp_path, terminal):
    runtime, identity, _, run, attempt, execution = _interrupted_native(tmp_path, terminal=terminal)
    try:
        key = "interrupted:shell:request"
        request = {"request": {"invocationId": "interrupted:shell", "capabilityId": "shell.exec"}}
        runtime.execution_value_store.put_tool_value(run_id=run.run_id, step_id="analyse", key=key, payload=request)
        saved = asyncio.run(runtime.fail_run_safely(run.run_id,
            error_code="dispatch_recovery_blocked", error_message="Cannot resume previous process"))
        assert saved.status is WorkflowStatus.FAILED
        assert saved.execution_state["taskSettlement"][attempt.attempt_id]["outcome"] == "failed"
        assert identity.repositories.step_executions.get(execution.step_execution_id).status is StepExecutionStatus.FAILED
        assert runtime.execution_value_store.get_tool_value(run_id=run.run_id, key=key) == request
        assert runtime.execution_value_store.get_tool_value(run_id=run.run_id, key="interrupted:shell:receipt") is None
        assert runtime.execution_value_store.get_tool_value(run_id=run.run_id, key="interrupted:shell:result") is None
    finally:
        identity.close()


@pytest.mark.parametrize("queued_status", [StepStatus.PENDING, StepStatus.RETRYING])
@pytest.mark.parametrize("remote", [False, True])
def test_restart_cancels_only_resource_waits_before_settling_executed_siblings(tmp_path, queued_status, remote):
    from runtime.permit_recovery import interrupted_step_ids

    runtime, identity, _, run, attempt, execution = _interrupted_native(tmp_path, remote=remote)
    try:
        run.steps.append(WorkflowStep(stepId="queued", name="queued", capability="analysis",
            agentName="native_general_agent", status=queued_status))
        run.current_step_id = "queued"
        run.active_step_ids = run.execution_state["activeStepIds"] = ["analyse", "queued"]
        run.execution_state["schedulingStates"] = {"queued": {
            "status": "queued", "attemptId": "not-yet-admitted", "reason": "NO_CAPACITY"}}
        run.execution_state.setdefault("attemptIds", {})["queued:1:root"] = "not-yet-admitted"
        runtime.workflow_store.save_run(run)
        request = {"request": {"invocationId": "unsettled:read", "capabilityId": "fs.read"}}
        runtime.execution_value_store.put_tool_value(run_id=run.run_id, step_id="analyse",
            key="unsettled:read:request", payload=request)

        asyncio.run(runtime.close_orphaned_runs())

        saved = runtime.get_status(run.run_id)
        queued = saved.get_step("queued")
        assert queued.status is StepStatus.CANCELLED and queued.started_at is None
        assert "resource wait interrupted" in queued.error
        assert not saved.execution_state.get("schedulingStates")
        assert not saved.active_step_ids
        assert saved.execution_state["activeStepIds"] == (["analyse"] if remote else [])
        assert set(interrupted_step_ids(saved)) == {"analyse", "queued"}
        assert [item.attempt_id for item in identity.repositories.attempts.list_for_run(run.run_id)] == [attempt.attempt_id]
        assert [item.step_execution_id for item in identity.repositories.step_executions.list_for_attempt(attempt.attempt_id)] == [execution.step_execution_id]
        assert runtime.execution_value_store.get_tool_value(run_id=run.run_id, key="unsettled:read:request") == request
        assert not runtime.execution_value_store.list_node_commits(run_id=run.run_id)
        assert identity.repositories.attempts.get("not-yet-admitted") is None
    finally:
        identity.close()


def test_restart_of_queue_only_run_preserves_non_execution_and_can_enter_recovery_scope(tmp_path):
    from runtime.permit_recovery import interrupted_step_ids

    runtime, identity, _, mission = _runtime(workflow_store=SQLiteWorkflowStore(tmp_path / "workflows.sqlite3"))
    try:
        _, run = runtime.prepare_run(mission.mission_id)
        run.status, run.current_step_id = WorkflowStatus.RUNNING, "analyse"
        run.get_step("analyse").status = StepStatus.PENDING
        run.active_step_ids = run.execution_state["activeStepIds"] = ["analyse"]
        run.execution_state["schedulingStates"] = {"analyse": {
            "status": "queued", "attemptId": "not-yet-admitted", "reason": "NO_CAPACITY"}}
        run.execution_state.setdefault("attemptIds", {})["analyse:1:root"] = "not-yet-admitted"
        run.execution_state.pop("planningLoop", None)
        runtime.workflow_store.save_run(run)
        assert identity.repositories.attempts.list_for_run(run.run_id) == []

        asyncio.run(runtime.close_orphaned_runs())

        saved = runtime.get_status(run.run_id)
        assert saved.status is WorkflowStatus.FAILED
        assert saved.get_step("analyse").status is StepStatus.CANCELLED
        assert saved.get_step("analyse").started_at is None
        assert interrupted_step_ids(saved) == ["analyse"]
        assert not saved.active_step_ids and not saved.execution_state["activeStepIds"]
        assert not saved.execution_state.get("schedulingStates")
        assert not saved.execution_state.get("executionBindings")
        assert not saved.execution_state.get("taskSettlement")
        assert identity.repositories.attempts.list_for_run(run.run_id) == []
        assert not runtime.execution_value_store.list_node_commits(run_id=run.run_id)
    finally:
        identity.close()
