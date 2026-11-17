"""Execution evidence returns to Planner and gates every terminal entry path."""

import asyncio
from types import SimpleNamespace

import pytest

from components.planner.runtime_decision import decide_runtime
from contracts.planning import PlannedTask, TaskPlan, TaskPlanPatch, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningDecision, RuntimePlanningObservation, RuntimeToolOutcome
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from runtime.planning_observation import RuntimePlanningObservationBuilder
from runtime.planning_loop import RuntimePlanningCoordinator
from service.agents.base import AgentOutput
from test_planning_loop import Agent, ArtifactAgent, Planner, artifact_workflow, attach, prepared


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "denied"])
def test_tool_commit_reobserves_success_and_failure_once_before_next_node(tmp_path, outcome):
    class InspectingAgent(Agent):
        async def run(self, context):
            output = await super().run(context)
            if context.step.step_id == "A":
                # This is a committed call report, not independently verified
                # evidence. It can cause review but cannot satisfy an obligation.
                output.tool_executions = [{"tool": "fs.read", "status": outcome,
                    "errorCode": "READ_FAILED" if outcome != "succeeded" else None,
                    "receiptRef": "x" * 300,
                    "arguments": {"path": "must-not-enter-the-observation"}}]
            return output
    runtime, agent, run = prepared(tmp_path, InspectingAgent())
    planner = Planner()
    attach(runtime, planner)
    async def boundary(current_run, state, reason):
        result = await runtime.runtime_planning_coordinator.boundary(current_run, state, reason)
        if result == "continue" and reason == "progress":
            # An unchanged committed frontier must not spend another round.
            assert await runtime.runtime_planning_coordinator.boundary(current_run, state, reason) == "continue"
        return result
    runtime.acg_execution_service._observe_boundary = boundary
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.COMPLETED
    assert agent.calls == ["A", "B"]
    assert [o.wake_reason for o in planner.observations] == ["resume", "exhausted"]
    observed = planner.observations[0].steps[0].tool_outcomes
    assert len(observed) == 1 and observed[0].status == outcome
    assert observed[0].receipt_ref is None
    assert "must-not-enter" not in planner.observations[0].model_dump_json()


@pytest.mark.parametrize("offline_policy", [False, True])
def test_failed_check_can_continue_through_declared_revision_and_passed_recheck(tmp_path, offline_policy):
    keys = ("understand", "draft", "check", "revision", "recheck", "final")
    capabilities = ("task_understanding", "artifact_generation", "verification", "artifact_generation",
                    "verification", "artifact_generation")
    workflow = WorkflowDefinition(workflowId="seq", name="refinement", domain="general", runtimeEngine="acg",
        planningNodes=tuple(PlannedTask(key=f"step:{key}", title=key, objective=f"execute {key}",
            capabilityRequirements=(capability,),
            logicalRole="final_synthesis" if key == "final" else "task")
            for key, capability in zip(keys, capabilities)),
        planningRelations=tuple(TaskPlanRelation(sourceKey=f"step:{source}", targetKey=f"step:{target}",
            relationType="depends_on") for source, target in zip(keys, keys[1:])),
        steps=tuple(WorkflowStepDefinition(stepId=key, name=key, agentName="runner", capability=capability,
            logicalRole="final_synthesis" if key == "final" else "task")
            for key, capability in zip(keys, capabilities)))
    class RefiningAgent(ArtifactAgent):
        async def run(self, context):
            if context.step.capability == "verification":
                self.calls.append(context.step.step_id)
                return AgentOutput(output={"verification": {
                    "status": "failed" if context.step.step_id == "check" else "passed"}})
            return await super().run(context)
    runtime, agent, run = prepared(tmp_path, RefiningAgent("# Actual report"), workflow)
    planner = Planner(lambda observation, plan: decide_runtime(observation=observation, task_plan=plan)
        if offline_policy else RuntimePlanningDecision(observationId=observation.fingerprint(),
            action="continue" if observation.remaining_step_ids else "complete",
            reason="finish the declared corrective path"))
    attach(runtime, planner)
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.COMPLETED
    assert agent.calls == list(keys)
    assert "verification_failed:check" in next(
        observation.completion_blockers for observation in planner.observations
        if observation.wake_reason == "verification")
    assert not planner.observations[-1].completion_blockers


def test_unrelated_pass_cannot_erase_a_failed_check_or_verify_a_new_revision():
    def step(key, capability, role="task"):
        return SimpleNamespace(step_id=key, capability=capability, logical_role=role)
    def fact(key, report=None):
        return SimpleNamespace(step_id=key, output_ref="output:" + key, verification_report=report)
    run = SimpleNamespace(steps=[step("old", "verification"), step("unrelated", "verification"),
        step("revision", "artifact_generation"), step("final", "artifact_generation", "final_synthesis")],
        acg_blueprint={"edges": [{"sourceId": "old", "targetId": "revision"},
            {"sourceId": "revision", "targetId": "final"},
            {"sourceId": "unrelated", "targetId": "final"}]})
    blockers = RuntimePlanningObservationBuilder._verification_blockers(run,
        [fact("old", "failed"), fact("unrelated", "passed"), fact("revision"), fact("final")], exhausted=True)
    assert "verification_failed:old" in blockers
    assert "final_verification_missing:final:revision" in blockers


@pytest.mark.parametrize("causal,passed", [(False, False), (False, True), (True, True)])
def test_committed_verifier_without_status_requires_a_causal_pass(causal, passed):
    run = SimpleNamespace(steps=[SimpleNamespace(step_id=key, capability="verification")
        for key in ("old", "recheck", "pending")], acg_blueprint={"edges": (
            [{"sourceId": "old", "targetId": "recheck"}] if causal else [])})
    facts = [SimpleNamespace(step_id="old", output_ref="output:old", verification_report=None),
        SimpleNamespace(step_id="recheck", output_ref="output:recheck" if passed else None,
            verification_report="passed" if passed else None),
        SimpleNamespace(step_id="pending", output_ref=None, verification_report=None)]
    blockers = RuntimePlanningObservationBuilder._verification_blockers(run, facts, exhausted=True)
    assert blockers == ([] if causal and passed else ["verification_unverified:old"])


def test_tool_observation_requests_revision_through_the_existing_graph_authority(tmp_path):
    class InspectingAgent(Agent):
        async def run(self, context):
            output = await super().run(context)
            if context.step.step_id == "A":
                output.tool_executions = [{"tool": "fs.read", "status": "failed", "errorCode": "NOT_FOUND"}]
            return output
    runtime, agent, run = prepared(tmp_path, InspectingAgent())
    def choose(observation, plan):
        if plan.plan_version == 1:
            assert observation.steps[0].tool_outcomes[0].status == "failed"
            patch = TaskPlanPatch(missionId=plan.mission_id, basePlanVersion=1, planVersion=2,
                addNodes=(PlannedTask(key="step:C", title="inspect again", objective="resolve observed source gap",
                    capabilityRequirements=("task_understanding",)),),
                relations=(TaskPlanRelation(sourceKey="step:A", targetKey="step:C", relationType="depends_on"),
                    TaskPlanRelation(sourceKey="step:C", targetKey="step:B", relationType="depends_on")))
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="revise",
                reason="new tool facts require a corrective task", taskPlanPatch=patch)
        return RuntimePlanningDecision(observationId=observation.fingerprint(),
            action="continue" if observation.remaining_step_ids else "complete", reason="use accepted revised graph")
    planner = Planner(choose)
    attach(runtime, planner)
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.COMPLETED and result.run_id != run.run_id
    source = runtime.get_status(run.run_id)
    assert source.status == WorkflowStatus.SUPERSEDED
    assert source.execution_state["planningLoop"]["current"]["decision"]["action"] == "revise"
    assert result.execution_state["taskPlanVersion"] == 2
    assert "C" in agent.calls and planner.observations[0].remaining_step_ids == ("B",)


@pytest.mark.parametrize("defect", ["failed_verification", "empty_artifact"])
def test_disabling_optional_planner_boundary_does_not_disable_completion_checks(tmp_path, defect):
    runtime, _, run = (prepared(tmp_path, Agent(verify="failed")) if defect == "failed_verification"
        else prepared(tmp_path, ArtifactAgent(" \n\t"), artifact_workflow()))
    runtime.acg_execution_service._observe_boundary = None
    with pytest.raises(ValueError, match="cannot complete unresolved work"):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert runtime.get_status(run.run_id).status != WorkflowStatus.COMPLETED


@pytest.mark.parametrize("report", ["failed", None])
def test_legacy_graph_without_planning_loop_still_checks_unresolved_verification(tmp_path, report):
    class LegacyVerifier(Agent):
        async def run(self, context):
            output = await super().run(context)
            if context.step.step_id == "A" and report is None:
                output.output = {"verification": {}}
            return output
    runtime, _, run = prepared(tmp_path, LegacyVerifier(verify="failed"))
    # Simulate a stored legacy executable graph: it has real run/step identities
    # and commits, but predates optional semantic planning projections.
    for key in ("taskPlan", "taskPlanVersion", "taskBindings", "planningLoop"):
        run.execution_state.pop(key, None)
    runtime.workflow_store.save_run(run)
    assert "taskPlan" not in run.execution_state and "planningLoop" not in run.execution_state
    runtime.acg_execution_service._observe_boundary = None
    with pytest.raises(ValueError, match="cannot complete unresolved work"):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert runtime.get_status(run.run_id).status != WorkflowStatus.COMPLETED
    commits = runtime.execution_value_store.list_node_commits(run_id=run.run_id)
    committed = next(commit for commit in commits
        if commit.get("stage") == "committed" and commit.get("nodeExecution", {}).get("stepId") == "A")
    payload = runtime.execution_value_store.get_output(run_id=run.run_id, output_ref=committed["outputRef"])
    assert payload["verification"].get("status") == report


def test_missing_frozen_workspace_evidence_blocks_completion_without_planner_hook(tmp_path, monkeypatch):
    runtime, _, run = prepared(tmp_path)
    runtime.acg_execution_service._observe_boundary = None
    monkeypatch.setattr("contracts.execution_evidence.evaluate_run_workspace_observations",
        lambda _run, _store: ("workspace_observation_incomplete:0",))
    with pytest.raises(ValueError, match="cannot complete unresolved work"):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert runtime.get_status(run.run_id).status != WorkflowStatus.COMPLETED


@pytest.mark.parametrize("changes,expected", [
    ({"completionBlockers": ("verification_failed:check",)}, "continue"),
    ({"completionBlockers": ("verification_partial:check",)}, "continue"),
    ({"completionBlockers": ("verification_unverified:check",)}, "continue"),
    ({"completionBlockers": ("artifact_nonempty_content:old",)}, "continue"),
    ({"completionBlockers": ("review_unresolved:check",)}, "wait"),
    ({"completionBlockers": ("artifact_unsealed:old",)}, "wait"),
    ({"completionBlockers": ("artifact_content_integrity:old",)}, "wait"),
    ({"failureType": "policy"}, "wait"),
    ({"failureType": "storage"}, "wait"),
    ({"completionBlockers": ("unknown_integrity_boundary:old",)}, "wait"),
    ({"failedStepIds": ("repair",)}, "abort"),
    ({"wakeReason": "failure"}, "abort"),
    ({"remainingStepIds": (), "completionBlockers": ("verification_failed:check",)}, "wait"),
    ({"remainingStepIds": ()}, "complete"),
])
def test_offline_policy_and_runtime_share_continuation_authority(changes, expected):
    observation = RuntimePlanningObservation.model_validate({
        "missionId": "mission_000000000001", "runId": "run", "graphId": "graph", "graphVersion": 1,
        "planVersion": 1, "wakeReason": "verification", "goal": "repair then recheck",
        "steps": ({"stepId": "check", "taskKey": "check", "status": "completed"},
                  {"stepId": "repair", "taskKey": "repair", "status": "pending"}),
        "remainingStepIds": ("repair",), **changes,
    })
    plan = TaskPlan(missionId=observation.mission_id, nodes=(
        PlannedTask(key="check", title="check", objective="verify"),
        PlannedTask(key="repair", title="repair", objective="correct failed check")))
    decision = decide_runtime(observation=observation, task_plan=plan)
    assert decision.action == expected
    RuntimePlanningCoordinator.validate_decision(observation, decision)
    if expected in {"wait", "abort"}:
        with pytest.raises(ValueError):
            RuntimePlanningCoordinator.validate_decision(observation, RuntimePlanningDecision(
                observationId=observation.fingerprint(), action="continue", reason="cannot bypass the gate"))


def test_planning_fingerprint_binds_tool_outcomes_and_workspace_progress():
    observation = RuntimePlanningObservation(missionId="mission", runId="run", graphId="graph",
        graphVersion=1, planVersion=1, wakeReason="resume", goal="inspect files",
        steps=({"stepId": "A", "taskKey": "A", "status": "completed"},), remainingStepIds=("B",))
    tool_observation = observation.model_copy(update={"steps": (
        observation.steps[0].model_copy(update={"tool_outcomes": (RuntimeToolOutcome(tool="fs.read", status="failed"),)}),)})
    workspace_observation = observation.model_copy(update={
        "workspace_observations": ({"kind": "file", "path": "brief.md", "complete": False},)})
    assert len({observation.fingerprint(), tool_observation.fingerprint(), workspace_observation.fingerprint()}) == 3
