"""Offline real Hands receipts through formal multi-version graph execution."""
# ruff: noqa: F811
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "components" / "planner"))
from TEST.tests.components.planner.test_horizon import ready_boundary, runtime_boundary
from TEST.tests.components.planner.test_initial_planning_sources import initial_run
from TEST.tests.components.planner.test_initial_execution_permit import open_existing, prepared_initial
from TEST.tests.adapters.test_unified_tools import stack as hands_stack

from components.planner.runtime_decision import decide_runtime
from contracts.planning import TaskPlan
from contracts.workflow import WorkflowStatus
from adapters.agent.base import AgentOutput
from support.stores.execution_dispatch_store import DispatchCommand, SQLiteExecutionDispatchStore


def install_execution(runtime, agent, hands_stack, monkeypatch):
    agent.profile.capabilities.append("information_extraction")
    runtime.agent_registry.register(agent)
    runtime.runtime_binding_service.refresh_embedded_runtime()
    original = agent.run

    async def execute(context):
        if context.step.capability == "task_understanding":
            return await original(context)
        agent.calls.append(context.step.step_id)
        if context.step.capability == "verification":
            return AgentOutput(output={"verification": {"status": "passed", "checks": [
                {"criterion": "This batch has committed receipt-backed observations", "result": "passed",
                 "evidence": "Review the committed upstream source batch"}], "unresolved_gaps": []}})
        plan = TaskPlan.model_validate(context.run.execution_state["taskPlan"])
        key = next(item["planNodeKey"] for item in context.run.execution_state["taskBindings"]
                   if item["acgNodeId"] == context.step.step_id)
        task = next(item for item in plan.nodes if item.key == key)
        targets = next((item["workspaceReview"]["targets"] for item in task.constraints if "workspaceReview" in item), [])
        records = []
        for index, target in enumerate(targets):
            result = await context.tool_runtime.execute("fs." + target["operation"], {"path": target["path"]},
                operation_key=f"{context.commit_id}:workspace:{index}")
            records.append(result.record)
        return AgentOutput(output={"extracted_information": {"facts": [], "metrics": [], "entities": [], "unknowns": []}},
                           tool_executions=records)

    monkeypatch.setattr(agent, "run", execute)
    hands_stack.runtime.execution_value_store = runtime.execution_value_store
    runtime.tool_runtime = hands_stack.tools
    runtime.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=decide_runtime)


def configure(initial_run, hands_stack, monkeypatch):
    runtime, workflow, agent, run, _ = initial_run
    runtime.resource_plane.set_runtime_enabled("runtime:horizon-test", enabled=False)
    install_execution(runtime, agent, hands_stack, monkeypatch)
    definition = runtime._workflow_for_run(run).model_copy(deep=True)
    definition.steps[0].capability = "task_understanding"
    definition.steps[0].output_spec = runtime.capability_catalog.get("task_understanding").output_contract
    runtime.workflow_registry.register(definition)
    run.input.update(workspaceBinding={"workspaceId": "one", "grantId": "grant-one"},
        workspaceObservations=[{"path": ".", "kind": "directory", "operation": "read", "recursive": True}])
    workflow.save_run(run)
    rt, workflow, agent, run, _, handoff_id = prepared_initial(initial_run)
    permit = rt.issue_execution_permit(handoff_id, idempotency_key="workspace-initial-permit")
    assert permit.status == "ISSUED", permit
    SQLiteExecutionDispatchStore.upgrade_schema(workflow.db_path)
    rt.execution_dispatch_store = SQLiteExecutionDispatchStore(workflow.db_path)
    rt.execution_dispatch_enabled = True
    current = workflow.get_run(run.run_id)
    principal = rt.semantic_principal_provider()
    command = DispatchCommand(dispatch_id="dispatch:initial", operation_key="workspace-initial-dispatch",
        request_fingerprint="workspace-initial", mission_id=run.mission_id, run_id=run.run_id,
        permit_id=permit.permit_id, graph_id=current.execution_state["graphId"], graph_version=1,
        runtime_revision=current.runtime_revision, actor_id=principal.actor_id, tenant_id=principal.tenant_id)
    rt.execution_dispatch_store.accept(command, rt.execution_permit_authority.assert_dispatchable)
    return rt, workflow, agent, current


class SimulatedProcessExit(BaseException):
    """Escape ordinary failure handling after a durable authority ACK."""


@pytest.mark.asyncio
@pytest.mark.parametrize("cut", [None, "feedback_checkpoint"])
async def test_denied_revision_reenters_planner_and_keeps_completed_prefix(
        initial_run, hands_stack, monkeypatch, cut):
    from components.planner.workspace_review import workspace_review_decision
    from contracts.runtime_planning import RuntimePlanningDecision

    rt, workflow, agent, run = configure(initial_run, hands_stack, monkeypatch)
    proposed = False
    feedback = []

    def decide(*, observation, task_plan):
        nonlocal proposed
        if observation.planning_commit_rejection is not None:
            feedback.append(observation.planning_commit_rejection)
            assert feedback[-1]["code"] == "INVALID_PROPOSAL"
            assert "started or settled" in feedback[-1]["reason"]
            return workspace_review_decision(observation=observation, task_plan=task_plan)
        if not proposed and any(step.status == "completed" for step in observation.steps):
            proposed = True
            candidate = workspace_review_decision(observation=observation, task_plan=task_plan).task_plan_patch
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="revise",
                reason="Split acquisition while incorrectly retiring the completed prefix",
                taskPlanPatch=candidate.model_copy(update={"retire_keys": (task_plan.nodes[0].key,)}))
        return decide_runtime(observation=observation, task_plan=task_plan)

    rt.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=decide)
    if cut:
        save = rt.acg_state_persistence.save_checkpoint

        def interrupted(current, state, **kwargs):
            checkpoint_id = save(current, state, **kwargs)
            if current.execution_state.get("planningCommitRejection"):
                raise SimulatedProcessExit(cut)
            return checkpoint_id

        monkeypatch.setattr(rt.acg_state_persistence, "save_checkpoint", interrupted)
        with pytest.raises(SimulatedProcessExit, match=cut):
            await rt.execute_prepared_run(run.run_id)
        held = workflow.get_run(run.run_id)
        assert held.status == WorkflowStatus.WAITING_REVIEW
        assert held.execution_state.get("workspaceReviewContinuation")
        monkeypatch.setattr(rt.acg_state_persistence, "save_checkpoint", save)
        prepared = rt.workspace_review_continuation.resume(held)
        assert prepared.status == WorkflowStatus.RETRYING
        assert prepared.execution_state.get("reviewPayload") is None
        checkpoint = rt.checkpoint_store.load(run_id=run.run_id,
            checkpoint_id=prepared.execution_state["checkpointId"])
        assert checkpoint["reviewPayload"] is None

    result = await rt.execute_prepared_run(run.run_id)
    assert result.status == WorkflowStatus.COMPLETED, {
        "review": (result.execution_state.get("reviewPayload") or {}).get("reason"),
        "continuation": (result.execution_state.get("workspaceReviewContinuation") or {}).get("reason"),
        "rejection": result.execution_state.get("planningCommitRejection"),
    }
    assert feedback and result.run_id == run.run_id
    assert result.execution_state["graphVersion"] == 3
    assert agent.calls.count("A") == 1
    assert [item["capabilityId"] for item in hands_stack.service.requests] == ["fs.list", "fs.read"]


@pytest.mark.asyncio
async def test_answer_after_permit_restart_commits_cleared_review_and_resumes_once(initial_run, hands_stack, monkeypatch):
    from contracts.runtime_planning import RuntimePlanningDecision
    from runtime.orchestration.planning_interaction import PlannerAnswerRequest, RuntimePlanningInteraction

    rt, workflow, agent, run = configure(initial_run, hands_stack, monkeypatch)
    initial_commit = run.execution_state["graphActivation"]["sourceCommitId"]

    def ask(*, observation, task_plan):
        return RuntimePlanningDecision(observationId=observation.fingerprint(), action="wait",
            reason="clarify repository review", question={"prompt": "Continue reviewing repository files?"})

    rt.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=ask)
    paused = await rt.execute_prepared_run(run.run_id)
    assert paused.status == WorkflowStatus.WAITING_REVIEW and agent.calls == []
    reopened, durable, agent2 = open_existing(workflow.db_path.parent, initial_commit)
    install_execution(reopened, agent2, hands_stack, monkeypatch)
    request = PlannerAnswerRequest(operationId="workspace-answer", answer="Continue the review",
        questionId=paused.execution_state["planningLoop"]["current"]["observationId"],
        expectedRevision=paused.runtime_revision)
    interaction = RuntimePlanningInteraction(reopened)
    ready = await interaction.answer(run.run_id, request)
    assert (await interaction.answer(run.run_id, request)).runtime_revision == ready.runtime_revision
    head, checkpoint = reopened.checkpoint_store.load_latest(run_id=run.run_id)
    assert head == ready.execution_state["checkpointId"] and checkpoint["reviewPayload"] is None

    resumed, durable, agent3 = open_existing(workflow.db_path.parent, initial_commit)
    install_execution(resumed, agent3, hands_stack, monkeypatch)
    resumed.execution_dispatch_store = SQLiteExecutionDispatchStore(durable.db_path)
    resumed.execution_dispatch_enabled = True
    observations = []

    def decide(*, observation, task_plan):
        observations.append(observation)
        if observation.wake_reason == "user_input":
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="continue",
                reason="The answer confirms continuing the existing declared work")
        return decide_runtime(observation=observation, task_plan=task_plan)

    resumed.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=decide)
    assert await resumed.prepare_planning_wakeups() == [run.run_id]
    result = await resumed.execute_prepared_run(run.run_id)
    assert result.status == WorkflowStatus.COMPLETED, {
        "review": result.execution_state.get("reviewPayload"),
        "continuation": result.execution_state.get("workspaceReviewContinuation"),
        "planning": (result.execution_state.get("planningLoop") or {}).get("current", {}).get("rejection"),
        "observations": [(item.wake_reason, item.failed_step_ids, item.completion_blockers) for item in observations],
    }
    assert observations[0].wake_reason == "user_input"
    assert observations[0].human_answers[-1].answer == request.answer
    assert agent2.calls == [] and agent3.calls.count("A") == 1
    assert [item["capabilityId"] for item in hands_stack.service.requests] == ["fs.list", "fs.read"]


@pytest.mark.asyncio
@pytest.mark.parametrize("compiler_drift", [None, "recipe", "policy"])
async def test_application_coordinator_resumes_legacy_rejected_revision(
        initial_run, hands_stack, monkeypatch, compiler_drift):
    from app.execution.coordinator import RunExecutionCoordinator
    from app.security.internal_auth import current_semantic_principal
    from components.planner.workspace_review import workspace_review_decision
    from contracts.runtime_planning import RuntimePlanningDecision

    rt, workflow, agent, run = configure(initial_run, hands_stack, monkeypatch)
    initial_commit = run.execution_state["graphActivation"]["sourceCommitId"]
    old_agent = agent
    proposed = False
    observed_feedback = []

    def decide(*, observation, task_plan):
        nonlocal proposed
        if observation.planning_commit_rejection is not None:
            observed_feedback.append(observation.planning_commit_rejection)
            return workspace_review_decision(observation=observation, task_plan=task_plan)
        if not proposed and any(step.status == "completed" for step in observation.steps):
            proposed = True
            candidate = workspace_review_decision(observation=observation, task_plan=task_plan).task_plan_patch
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="revise",
                reason="Attempt to replace already completed work",
                taskPlanPatch=candidate.model_copy(update={"retire_keys": (task_plan.nodes[0].key,)}))
        return decide_runtime(observation=observation, task_plan=task_plan)

    rt.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=decide)
    prepare = rt.workspace_review_continuation._prepare_replan
    monkeypatch.setattr(rt.workspace_review_continuation, "_prepare_replan", lambda *args, **kwargs: None)
    held = await rt.execute_prepared_run(run.run_id)
    assert held.status == WorkflowStatus.WAITING_REVIEW
    pending = held.execution_state["workspaceReviewContinuation"]
    assert pending["blocked"] and pending["errorCode"] == "INVALID_PROPOSAL"
    # Model an old process's marker, before the diagnostic code was explicit.
    pending.pop("errorCode")
    workflow.save_run(held)
    monkeypatch.setattr(rt.workspace_review_continuation, "_prepare_replan", prepare)
    # Reopen every authority and SQLite store to exercise process-restart
    # assembly, instead of retaining the old Runtime's projection caches.
    rt, workflow, agent = open_existing(workflow.db_path.parent, initial_commit)
    install_execution(rt, agent, hands_stack, monkeypatch)
    rt.execution_dispatch_store = SQLiteExecutionDispatchStore(workflow.db_path)
    rt.execution_dispatch_enabled = True
    rt.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=decide)
    initial_materialization = rt.graph_materialization_authority.store.materialization_for(initial_commit)
    frozen_package = initial_materialization.package.model_dump(mode="json", by_alias=True)
    if compiler_drift == "recipe":
        import runtime.orchestration.initial_execution as execution
        import components.planner.initial_graph_compilation as compilation

        monkeypatch.setattr(compilation, "initial_recipe_fingerprint", lambda: "f" * 64)
        monkeypatch.setattr(execution, "initial_recipe_fingerprint", lambda: "f" * 64, raising=False)
    elif compiler_drift == "policy":
        import runtime.orchestration.initial_planning_sources as sources

        policy = sources.compilation_policy().model_copy(deep=True)
        policy = policy.model_copy(update={"versions": {**policy.versions, "lowerer": "new-host-policy"}})
        monkeypatch.setattr(sources, "compilation_policy", lambda: policy)
    # Match production: only the application coordinator can restore the
    # accepted actor. There is no ambient HTTP request identity on restart.
    monkeypatch.setattr(rt, "semantic_principal_provider", current_semantic_principal)
    coordinator = RunExecutionCoordinator(rt)
    monkeypatch.setattr(coordinator, "_ensure_wait_monitor", lambda: None)
    rejection = []
    reconcile = rt.reconcile_execution_checkpoint

    def reconcile_or_explain(run_id):
        try:
            return reconcile(run_id)
        except Exception as exc:
            rejection.append((type(exc).__name__, str(exc)))
            raise

    monkeypatch.setattr(rt, "reconcile_execution_checkpoint", reconcile_or_explain)
    try:
        scheduled = await coordinator.submit(run.run_id)
        assert scheduled, {"rejections": rejection, "error": workflow.get_run(run.run_id).error}
        task = coordinator._tasks[run.run_id]
        await task
        result = workflow.get_run(run.run_id)
        assert result.status == WorkflowStatus.COMPLETED, result.error
        assert observed_feedback and old_agent.calls.count("A") == 1 and "A" not in agent.calls
        assert rt.graph_materialization_authority.store.materialization_for(initial_commit).package.model_dump(
            mode="json", by_alias=True) == frozen_package
        assert [item["capabilityId"] for item in hands_stack.service.requests] == ["fs.list", "fs.read"]
    finally:
        await coordinator.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("cut", ["semantic", "activation", "permit", "dispatch"])
async def test_reopened_runtime_resumes_graph_journals_without_repeating_prefix(
        initial_run, hands_stack, monkeypatch, cut):
    from support.async_tasks import run_blocking

    rt, workflow, agent, run = configure(initial_run, hands_stack, monkeypatch)
    initial_commit = run.execution_state["graphActivation"]["sourceCommitId"]
    target, name = {
        "semantic": (rt.planning_commit_authority, "accept_patch_locked"),
        "activation": (rt, "commit_graph_activation"),
        "permit": (rt, "issue_execution_permit"),
        "dispatch": (rt.execution_dispatch_store, "accept_continuation"),
    }[cut]
    original = getattr(target, name)
    def exit_after_ack(*args, **kwargs):
        result = original(*args, **kwargs)
        assert getattr(result, "status", None) != "REJECTED", result
        raise SimulatedProcessExit(cut)
    monkeypatch.setattr(target, name, exit_after_ack)
    with pytest.raises(SimulatedProcessExit, match=cut):
        await rt.execute_prepared_run(run.run_id)
    assert agent.calls == ["A"] and not hands_stack.service.requests
    stopped = workflow.get_run(run.run_id)
    assert stopped.execution_state.get("workspaceReviewContinuation")

    # Construct a new Runtime and independent SQLite stores, rather than keeping
    # the old continuation's retry state or authority objects in memory.
    reopened, durable, resumed_agent = open_existing(workflow.db_path.parent, initial_commit)
    install_execution(reopened, resumed_agent, hands_stack, monkeypatch)
    reopened.execution_dispatch_store = SQLiteExecutionDispatchStore(durable.db_path)
    reopened.execution_dispatch_enabled = True
    continuation = await run_blocking(reopened.workspace_review_continuation.resume, durable.get_run(run.run_id))
    assert continuation is not None, durable.get_run(run.run_id).execution_state.get("workspaceReviewContinuation")
    result = await reopened.execute_prepared_run(run.run_id)
    assert result.status == WorkflowStatus.COMPLETED, result.execution_state.get("workspaceReview")
    assert result.run_id == run.run_id and result.execution_state["graphVersion"] == 3
    assert "A" not in resumed_agent.calls and len(resumed_agent.calls) == 4
    assert [item["capabilityId"] for item in hands_stack.service.requests] == ["fs.list", "fs.read"]
    with sqlite3.connect(durable.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM execution_dispatch_commands").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM execution_dispatch_continuations").fetchone()[0] == 2
    await reopened.execute_prepared_run(run.run_id)
    assert len(resumed_agent.calls) == 4 and len(hands_stack.service.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cut", ["decided", "reader_checkpoint"])
async def test_reopened_execution_reuses_committed_reads_and_unapplied_decision(
        initial_run, hands_stack, monkeypatch, cut):
    rt, workflow, agent, run = configure(initial_run, hands_stack, monkeypatch)
    initial_commit = run.execution_state["graphActivation"]["sourceCommitId"]
    if cut == "decided":
        save = workflow.save_run
        def save_then_exit(current, **kwargs):
            save(current, **kwargs)
            round_ = (current.execution_state.get("planningLoop") or {}).get("current") or {}
            if current.execution_state.get("workspaceReviewContinuation") and round_.get("status") == "decided":
                raise SimulatedProcessExit(cut)
        monkeypatch.setattr(workflow, "save_run", save_then_exit)
    else:
        save = rt.acg_state_persistence.save_checkpoint
        def checkpoint_then_exit(current, state, **kwargs):
            result = save(current, state, **kwargs)
            if len(state.completed_step_ids) == 2 and current.execution_state.get("graphVersion") == 2:
                raise SimulatedProcessExit(cut)
            return result
        monkeypatch.setattr(rt.acg_state_persistence, "save_checkpoint", checkpoint_then_exit)
    with pytest.raises(SimulatedProcessExit, match=cut):
        await rt.execute_prepared_run(run.run_id)
    expected_prefix = 1 if cut == "decided" else 2
    assert len(agent.calls) == expected_prefix and agent.calls.count("A") == 1
    assert len(hands_stack.service.requests) == (0 if cut == "decided" else 1)

    reopened, durable, resumed_agent = open_existing(workflow.db_path.parent, initial_commit)
    install_execution(reopened, resumed_agent, hands_stack, monkeypatch)
    reopened.execution_dispatch_store = SQLiteExecutionDispatchStore(durable.db_path)
    reopened.execution_dispatch_enabled = True
    result = await reopened.execute_prepared_run(run.run_id)
    assert result.status == WorkflowStatus.COMPLETED, result.execution_state.get("workspaceReview")
    assert result.run_id == run.run_id and result.execution_state["graphVersion"] == 3
    assert "A" not in resumed_agent.calls and len(resumed_agent.calls) == 5 - expected_prefix
    assert [item["capabilityId"] for item in hands_stack.service.requests] == ["fs.list", "fs.read"]
    with sqlite3.connect(durable.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM execution_dispatch_continuations").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_real_receipt_batches_revise_same_run_and_finish_only_after_review(initial_run, hands_stack, monkeypatch):
    rt, workflow, agent, run = configure(initial_run, hands_stack, monkeypatch)
    result = await rt.execute_prepared_run(run.run_id)
    assert result.status == WorkflowStatus.COMPLETED, result.execution_state.get("workspaceReview")
    assert result.run_id == run.run_id and result.execution_state["graphVersion"] == 3
    assert agent.calls.count("A") == 1 and len(agent.calls) == 5
    assert [item["capabilityId"] for item in hands_stack.service.requests] == ["fs.list", "fs.read"]
    assert rt.execution_dispatch_store.get(run.run_id).graph_version == 3
    with sqlite3.connect(workflow.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM execution_dispatch_commands").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM execution_dispatch_continuations").fetchone()[0] == 2
    progress = result.execution_state["workspaceReview"]
    assert progress["status"] == "completed" and progress["graphVersion"] == 3
    assert progress["gaps"]["missingReadCount"] == 0
    assert len([item for item in progress["rounds"] if item.get("addedStepIds")]) == 2
    assert not result.execution_state.get("workspaceReviewContinuation")
    await rt.execute_prepared_run(run.run_id)
    assert len(agent.calls) == 5 and len(hands_stack.service.requests) == 2
