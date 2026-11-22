"""Planner repairs exhausted actions without inventing successful acceptance."""
import json

import pytest

from adapters.model.protocols import StructuredGenerationError
from components.planner.runtime_decision import decide_runtime
from contracts.planning import PlannedTask, TaskPlan
from contracts.runtime_planning import RuntimePlanningDecision, RuntimePlanningObservation
from runtime.orchestration.planning_loop import RuntimePlanningCoordinator
from TEST.tests.components.planner.test_runtime_decision_correction import CandidateModel
from TEST.tests.components.planner.test_react_loop import (ReActFakeLLM, decide_payload, make_loop, persisted_facts,
                             waiting_boundary)


def exhausted(*, blockers=()):
    plan = TaskPlan(missionId="mission_0123456789ab", nodes=(
        PlannedTask(key="report", title="Report", objective="Deliver findings"),))
    observation = RuntimePlanningObservation(missionId=plan.mission_id, runId="run", graphId="graph",
        graphVersion=1, planVersion=1, wakeReason="exhausted", goal="Deliver findings",
        steps=({"stepId": "report", "taskKey": "report", "status": "completed"},),
        remainingStepIds=(), completionBlockers=blockers)
    return plan, observation


def candidate(observation, action, reason="Choose the action from current evidence"):
    return {"observationId": observation.fingerprint(), "action": action, "reason": reason}


def test_exhausted_continue_is_corrected_to_completion_in_same_model_round():
    plan, observation = exhausted()
    before = observation.model_dump(mode="json")
    llm = CandidateModel([candidate(observation, "continue"), candidate(observation, "complete")])
    result = decide_runtime(observation=observation, task_plan=plan, llm=llm)
    assert result.action == "complete" and len(llm.requests) == 2
    RuntimePlanningCoordinator.validate_decision(observation, result)
    feedback = llm.requests[1]["validationCorrection"]
    assert feedback["validationErrors"][0]["loc"] == ["action"]
    assert "exhausted" in feedback["validationErrors"][0]["msg"]
    assert llm.requests[0]["observation"] == llm.requests[1]["observation"]
    assert observation.model_dump(mode="json") == before


def test_integrity_does_not_turn_unverified_report_into_success():
    plan, observation = exhausted(blockers=("verification_unverified:report",))
    llm = CandidateModel([candidate(observation, "continue"), candidate(observation, "complete"),
        candidate(observation, "wait", "Report exists; business verification remains unresolved")])
    result = decide_runtime(observation=observation, task_plan=plan, llm=llm)
    assert result.action == "wait" and len(llm.requests) == 3
    assert "unresolved work" in llm.requests[2]["validationCorrection"]["validationErrors"][0]["msg"]
    assert observation.completion_blockers == ("verification_unverified:report",)
    RuntimePlanningCoordinator.validate_decision(observation, result)


def test_missing_acceptance_result_is_corrected_even_without_completion_blocker():
    from contracts.task_acceptance import TaskAcceptanceSpec

    plan, observation = exhausted()
    observation = observation.model_copy(update={"task_acceptance": TaskAcceptanceSpec(criteria=(
        {"criterionId": "evidence", "pointer": "/evidence", "operator": "exists"},))})
    invalid = RuntimePlanningDecision.model_validate(candidate(observation, "complete"))
    with pytest.raises(ValueError, match="unverified task acceptance"):
        RuntimePlanningCoordinator.validate_decision(observation, invalid)
    llm = CandidateModel([candidate(observation, "complete"), candidate(observation, "wait")])
    result = decide_runtime(observation=observation, task_plan=plan, llm=llm)
    assert result.action == "wait"
    assert "unverified task acceptance" in llm.requests[1]["validationCorrection"]["validationErrors"][0]["msg"]
    assert observation.task_acceptance_results == ()


def test_repeated_exhausted_continue_is_no_progress_even_with_new_reason():
    plan, observation = exhausted()
    llm = CandidateModel([candidate(observation, "continue", "first"), candidate(observation, "continue", "second")])
    with pytest.raises(StructuredGenerationError) as caught:
        decide_runtime(observation=observation, task_plan=plan, llm=llm)
    assert caught.value.code == "PLANNER_DECISION_NO_PROGRESS"
    assert caught.value.metadata["validationFailures"][0]["fieldPath"] == ["action"]


@pytest.mark.parametrize("blocked", [False, True])
def test_react_planner_uses_the_same_action_correction_and_frozen_evidence(waiting_boundary, blocked):
    _, store, agent, run_id = waiting_boundary
    observation, plan = persisted_facts(store, run_id)
    if blocked:
        observation = observation.model_copy(update={"completion_blockers": ("verification_unverified:B",)})
    action = "wait" if blocked else "complete"
    before = json.dumps(store.get_run(run_id).model_dump(mode="json"), sort_keys=True)
    llm = ReActFakeLLM([
        lambda payload: decide_payload(payload["observationId"], "continue"),
        lambda payload: decide_payload(payload["observationId"], action),
    ])
    result = make_loop(store, llm, []).decide(observation=observation, task_plan=plan)
    assert result.action == action and len(llm.prompts) == 2
    assert llm.prompts[1]["validationCorrection"]["validationErrors"][0]["loc"] == ["action"]
    assert json.dumps(store.get_run(run_id).model_dump(mode="json"), sort_keys=True) == before
    assert agent.calls == ["A", "B"]
    RuntimePlanningCoordinator.validate_decision(observation, result)
