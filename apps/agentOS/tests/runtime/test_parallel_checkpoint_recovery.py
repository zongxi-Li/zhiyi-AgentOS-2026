"""Recover an interrupted parallel frontier without replaying its prefix."""
import asyncio
from collections import Counter

import pytest

from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningDecision, RuntimePlanningState
from contracts.workflow import StepStatus, WorkflowStatus, TraceEventType, RuntimeRunRecord, WorkflowStep
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode
from support.acg.planning import ACGResourcePlan, AgentBindingSpec
from test_single_step_retry import _retry_runtime
from runtime.runtime_recovery import pending_retry_dispatch
from components.executor import ACGExecutionState


class ParallelRetryAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentProfile(agentName="retry-agent", domain="general", capabilities=["analysis"], capacity=4))
        self.calls = Counter()
        self.entered = 0
        self.frontier = asyncio.Event()

    async def run(self, context):
        step = context.step.step_id
        self.calls[step] += 1
        if step in {"left", "middle", "right"} and self.calls[step] == 1:
            self.entered += 1
            if self.entered == 3:
                self.frontier.set()
            await self.frontier.wait()
            raise RuntimeError("parallel frontier interrupted")
        return AgentOutput(output={step: step + " output"}, summary=step + " complete")


@pytest.mark.parametrize("barrier", ["review", "continuation", "user_input", "condition", "new_result"])
def test_retry_dispatch_preserves_new_review_and_operator_boundaries(barrier):
    run = RuntimeRunRecord(runId="run", missionId="mission", workflowId="workflow", domain="general",
        runtimeEngine="acg", status=WorkflowStatus.RUNNING, recoveryCount=1,
        completedStepIds=["prefix"], steps=[WorkflowStep(stepId="reader", name="reader", agentName="reader", status=StepStatus.PENDING)],
        executionState={"singleStepRetry": {"sourceRunId": "run", "targetStepId": "reader", "reusedStepIds": ["prefix"]},
            "checkpointResume": {"mode": "current_run", "failedStepId": "reader", "resumeStepIds": ["reader"]},
            "inPlaceRetry": {"failedStepId": "reader"}})
    state = ACGExecutionState(runId="run", completedStepIds=["prefix"])
    assert pending_retry_dispatch(run, state)
    if barrier == "review":
        state.review_payload = {"subjectType": "planner"}
    elif barrier == "continuation":
        run.execution_state["workspaceReviewContinuation"] = {"observationId": "current"}
    elif barrier == "user_input":
        run.execution_state["planningLoop"] = {"userInputPending": True}
    elif barrier == "condition":
        run.execution_state["planningLoop"] = {"waiting": {"observationId": "current"}}
    else:
        state.completed_step_ids.append("reader")
    assert not pending_retry_dispatch(run, state)


@pytest.mark.parametrize("with_identity", [False, True])
@pytest.mark.parametrize("review_frontier", [False, True])
@pytest.mark.parametrize("cancelled_frontier", [False, True])
def test_same_run_retry_reopens_all_interrupted_siblings_with_new_attempts(tmp_path, with_identity, review_frontier, cancelled_frontier):
    agent = ParallelRetryAgent()
    runtime, _ = _retry_runtime(tmp_path, agent, with_identity=with_identity)
    step_ids = ("source", "left", "middle", "right", "final")
    edges = [("source", step) for step in step_ids[1:4]] + [(step, "final") for step in step_ids[1:4]]
    blueprint = ACGBlueprint(graphId="parallel-retry", nodes=[StepNode(nodeId=step, name=step,
        capability="analysis", outputSpec={"type": "object", "required": [step],
            "properties": {step: {"type": "string"}}}) for step in step_ids],
        edges=[ACGEdge(sourceId=source, targetId=target, edgeType=EdgeType.DEPENDENCY) for source, target in edges],
        resourcePlan=ACGResourcePlan(bindings=tuple(AgentBindingSpec(stepId=step, plannedAgentId="retry-agent") for step in step_ids)))
    try:
        mission = runtime.create_mission("recover parallel frontier", workflow_id="single-step-retry")
        plan = TaskPlan(missionId=mission.mission_id,
            nodes=tuple(PlannedTask(key="step:" + step, title=step, objective=step,
                capabilityRequirements=("analysis",)) for step in step_ids),
            relations=tuple(TaskPlanRelation(sourceKey="step:" + source, targetKey="step:" + target,
                relationType="depends_on") for source, target in edges))
        mission.input.update(acgBlueprint=blueprint.model_dump(by_alias=True, mode="json"),
            taskPlan=plan.model_dump(by_alias=True, mode="json"), taskBindings=[
                TaskImplementationBinding(planNodeKey="step:" + step, acgNodeId=step).model_dump(by_alias=True, mode="json")
                for step in step_ids])
        runtime.workflow_store.save_mission(mission)
        _, run = runtime.prepare_run(mission.mission_id)
        with pytest.raises(RuntimeError, match="ACG superstep failed"):
            asyncio.run(runtime.execute_prepared_run(run.run_id))
        failed = runtime.get_status(run.run_id)
        assert failed.status == WorkflowStatus.FAILED
        assert {step.step_id for step in failed.steps if step.status in {StepStatus.FAILED, StepStatus.CANCELLED}} == {"left", "middle", "right"}
        anchor = next(step.step_id for step in failed.steps if step.status == StepStatus.FAILED)
        if cancelled_frontier:
            for step in failed.steps:
                if step.step_id in {"left", "middle", "right"}:
                    step.status = StepStatus.CANCELLED
        assert failed.completed_step_ids == ["source"]
        assert failed.get_step("final").status == StepStatus.PENDING
        prefix = failed.execution_state["outputRefs"]["source"]
        graph = failed.acg_blueprint
        generation = failed.execution_state.get("executionGeneration")
        # Shutdown can leave frontier markers after each local task has ended.
        failed.execution_state["activeStepIds"] = ["left", "middle", "right"]
        stale_revision = {"blocked": True, "observationId": "superseded-observation", "sourceGraphVersion": 1,
            "errorType": "ValueError", "reason": "historical native session proof unavailable",
            "patch": {"basePlanVersion": 1, "reason": "historical unaccepted proposal"}}
        failed.execution_state["workspaceReviewContinuation"] = stale_revision
        runtime.workflow_store.save_run(failed)
        prepared = runtime.prepare_single_step_retry(run.run_id, anchor, reuse_source_run=True,
            expected_runtime_revision=failed.runtime_revision, idempotency_key="parallel-recover",
            idempotency_fingerprint="parallel-fingerprint")
        assert prepared.run_id == run.run_id and prepared.status == WorkflowStatus.RETRYING
        assert prepared.acg_blueprint == graph
        assert prepared.execution_state.get("executionGeneration") == generation
        assert prepared.completed_step_ids == ["source"] and prepared.execution_state["outputRefs"]["source"] == prefix
        assert not prepared.active_step_ids and not prepared.execution_state["activeStepIds"]
        assert prepared.execution_state["singleStepRetry"]["interruptedStepIds"] == ["left", "middle", "right"]
        assert "workspaceReviewContinuation" not in prepared.execution_state
        recovered_event = next(event for event in reversed(prepared.trace) if event.event_type is TraceEventType.RUN_RECOVERED)
        retired = recovered_event.payload["retiredWorkspaceReview"]
        assert retired["observationId"] == "superseded-observation"
        archive = runtime.execution_value_store.get_graph_patch(run_id=prepared.run_id, patch_ref=retired["proposalRef"])
        assert archive["continuation"] == stale_revision
        for step in ("left", "middle", "right"):
            assert prepared.get_step(step).status == StepStatus.PENDING
            assert prepared.get_step(step).attempt == prepared.get_step(step).retry_count == 1
        assert prepared.get_step("final").attempt == 0
        observations = []
        if review_frontier:
            prepared.execution_state["planningLoop"] = RuntimePlanningState().model_dump(by_alias=True, mode="json")
            runtime.workflow_store.save_run(prepared)
            def review(*, observation, task_plan):
                observations.append(observation)
                # Initial resume must dispatch the already admitted frontier.
                # Its first review sees new results from all three Attempts.
                assert all(agent.calls[step] == 2 for step in ("left", "middle", "right"))
                return RuntimePlanningDecision(observationId=observation.fingerprint(), action="wait",
                    reason="review the recovered frontier before its final descendant")
            from types import SimpleNamespace
            runtime.runtime_planning_coordinator.planner_for_run = lambda _: SimpleNamespace(decide_runtime=review)
            runtime.runtime_planning_coordinator.observe_progress = lambda *_: True
        result = asyncio.run(runtime.execute_prepared_run(run.run_id))
        assert result.status == (WorkflowStatus.WAITING_REVIEW if review_frontier else WorkflowStatus.COMPLETED)
        assert agent.calls == ({"source": 1, "left": 2, "middle": 2, "right": 2} if review_frontier else
            {"source": 1, "left": 2, "middle": 2, "right": 2, "final": 1})
        if review_frontier:
            assert len(observations) == 1 and observations[0].wake_reason == "resume"
            assert observations[0].remaining_step_ids == ("final",)
        assert result.execution_state["outputRefs"]["source"] == prefix
        assert result.recovery_count == 1
    finally:
        if runtime.identity_lifecycle is not None:
            runtime.identity_lifecycle.lifecycle_service.close()
