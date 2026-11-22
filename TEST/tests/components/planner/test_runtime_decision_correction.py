"""Planner contract corrections preserve evidence and stop semantic repetition."""
import json

import pytest

from adapters.model.protocols import StructuredGenerationError
from components.planner import runtime_decision
from contracts.planning import PlannedTask, TaskPlan
from contracts.runtime_planning import RuntimePlanningObservation


@pytest.fixture
def context():
    mission = "mission_0123456789ab"
    plan = TaskPlan(missionId=mission,
        nodes=(PlannedTask(key="task:a", title="Inspect", objective="Inspect source evidence"),))
    observation = RuntimePlanningObservation(missionId=mission, runId="run_runtime",
        graphId="graph", graphVersion=1, planVersion=1, wakeReason="resume", goal="Inspect source evidence",
        steps=({"stepId": "a", "taskKey": "task:a", "status": "pending"},), remainingStepIds=("a",))
    return observation, plan


class CandidateModel:
    def __init__(self, candidates):
        self.candidates = iter(candidates)
        self.requests = []
        self.schemas = []

    def generate_json(self, prompt, schema, **kwargs):
        self.requests.append(json.loads(prompt))
        self.schemas.append(schema)
        result = next(self.candidates)
        if isinstance(result, Exception):
            raise result
        return {"data": result, "provider": "fixture", "model": "planner"}


def decide(context, candidates):
    observation, plan = context
    llm = CandidateModel(candidates)
    result = runtime_decision.decide_runtime(observation=observation, task_plan=plan, llm=llm)
    return result, llm


def candidate(observation, **values):
    return {"observationId": observation.fingerprint(), "action": "continue",
        "reason": "Use the declared remaining task", **values}


def test_invalid_json_is_regenerated_with_unchanged_observation(context):
    observation, _ = context
    error = StructuredGenerationError("MODEL_OUTPUT_INVALID_JSON", "private malformed reply")
    result, llm = decide(context, [error, candidate(observation)])
    assert result.action == "continue"
    first, repair = llm.requests
    correction = repair.pop("validationCorrection")
    assert repair == first
    assert correction["validationErrors"][0]["code"] == "MODEL_OUTPUT_INVALID_JSON"
    assert "private malformed reply" not in json.dumps(correction)
    assert llm.schemas[0] == llm.schemas[1]


def test_repeated_invalid_json_preserves_the_error_without_applying_a_decision(context):
    observation, plan = context
    first, repeated = (StructuredGenerationError("MODEL_OUTPUT_INVALID_JSON", "malformed reply",
        audit={"candidateFingerprint": "same-response"}) for _ in range(2))
    llm = CandidateModel([first, repeated])
    with pytest.raises(StructuredGenerationError) as failure:
        runtime_decision.decide_runtime(observation=observation, task_plan=plan, llm=llm)
    assert failure.value.code == "MODEL_OUTPUT_INVALID_JSON"
    assert failure.value.attempts == 2
    assert failure.value.metadata["attemptCount"] == 2
    assert failure.value.metadata["validationFailures"][0]["callKey"] == "runtime_decision.repair"


def test_invalid_field_is_returned_to_model_without_changing_original_snapshot(context):
    observation, plan = context
    invalid = candidate(observation, action="replan")
    before = json.dumps(invalid, sort_keys=True)
    result, llm = decide(context, [invalid, candidate(observation)])
    assert result.action == "continue"
    first, corrected = llm.requests
    assert "validationCorrection" not in first
    feedback = corrected.pop("validationCorrection")
    assert corrected == first
    assert corrected["observation"] == observation.model_dump(by_alias=True, mode="json")
    assert corrected["taskPlan"] == plan.model_dump(by_alias=True, mode="json")
    assert feedback["previousCandidate"] == invalid
    assert feedback["validationErrors"][0]["loc"] == ["action"]
    assert feedback["validationErrors"][0]["type"] == "literal_error"
    assert json.dumps(invalid, sort_keys=True) == before
    assert llm.schemas[0] == llm.schemas[1]


def test_semantic_model_validator_feedback_corrects_revision_instead_of_stripping_patch(context):
    observation, _ = context
    invalid = candidate(observation, action="revise")
    patch = {"missionId": observation.mission_id, "basePlanVersion": 1, "planVersion": 2,
        "addNodes": [{"key": "task:b", "title": "Verify", "objective": "Verify inspected evidence"}]}
    result, llm = decide(context, [invalid, candidate(observation, action="revise", taskPlanPatch=patch)])
    assert result.task_plan_patch.add_nodes[0].key == "task:b"
    feedback = llm.requests[1]["validationCorrection"]
    assert feedback["validationErrors"][0]["loc"] == []
    assert "revise requires a TaskPlanPatch" in feedback["validationErrors"][0]["msg"]


def test_formal_planner_repairs_invalid_revision_before_handoff_to_recovery(context):
    observation, plan = context
    observation = observation.model_copy(update={
        "wake_reason": "failure", "failed_step_ids": ("a",), "recovery_action": "retry",
        "protected_task_keys": ("task:a",),
    })
    revision = {"missionId": plan.mission_id, "basePlanVersion": 1, "planVersion": 2}
    retires_failed = candidate(observation, action="revise", taskPlanPatch={**revision, "retireKeys": ["task:a"]})
    bypasses_failed = candidate(observation, action="revise", taskPlanPatch={**revision, "addNodes": [
        {"key": "task:b", "title": "Inspect", "objective": "Inspect the remaining workspace evidence"},
    ]})
    result, llm = decide((observation, plan), [retires_failed, bypasses_failed, candidate(observation, action="recover")])
    assert result.action == "recover" and result.task_plan_patch is None
    assert llm.requests[0]["observation"]["protectedTaskKeys"] == ["task:a"]
    errors = [request["validationCorrection"]["validationErrors"][0] for request in llm.requests[1:]]
    assert [error["loc"] for error in errors] == [["taskPlanPatch"], ["taskPlanPatch"]]
    assert "started or settled work" in errors[0]["msg"]
    assert "Resolve the failed execution" in errors[1]["msg"]


def test_changed_correction_candidates_have_no_attempt_count_ceiling(context):
    observation, _ = context
    candidates = [candidate(observation, action="revise", taskPlanPatch={
        "missionId": observation.mission_id, "basePlanVersion": 1, "planVersion": 2,
        "addNodes": [{"title": "Verify", "objective": f"Inspect changed scope {index}"}],
    }) for index in range(10)]
    result, llm = decide(context, [*candidates, candidate(observation)])
    assert result.action == "continue"
    assert len(llm.requests) == 11


@pytest.mark.parametrize("change_reason", [False, True])
def test_repeated_invalid_action_stops_even_when_explanatory_reason_changes(context, change_reason):
    observation, plan = context
    invalid = candidate(observation, action="revise")
    repeated = {**invalid, "reason": "Different explanation"} if change_reason else invalid
    llm = CandidateModel([invalid, repeated])
    with pytest.raises(StructuredGenerationError) as caught:
        runtime_decision.decide_runtime(observation=observation, task_plan=plan, llm=llm)
    error = caught.value
    assert error.code == "PLANNER_DECISION_NO_PROGRESS"
    assert error.attempts == 2 and not error.retryable
    assert error.metadata["validationFailures"] == [{
        "stage": "runtime_decision", "callKey": "runtime_decision", "code": "value_error", "fieldPath": [],
    }]


def test_deadline_is_shared_across_corrections_and_preserves_field_failure(context, monkeypatch):
    observation, plan = context
    clock = iter([100.0, 100.0, 101.0])
    monkeypatch.setattr(runtime_decision, "monotonic", lambda: next(clock))
    monkeypatch.setattr(runtime_decision, "PLANNING_TOTAL_TIMEOUT_SECONDS", 1.0)
    calls = []

    def generate(_llm, **kwargs):
        calls.append(kwargs)
        return {"data": candidate(observation, action="wrong")}

    monkeypatch.setattr(runtime_decision, "call_planning_model", generate)
    with pytest.raises(StructuredGenerationError) as caught:
        runtime_decision.decide_runtime(observation=observation, task_plan=plan, llm=object())
    assert caught.value.code == "MODEL_TIMEOUT" and caught.value.retryable
    assert caught.value.attempts == 1
    assert calls[0]["planning_deadline"] == 101.0
    assert caught.value.metadata["validationFailures"][0]["fieldPath"] == ["action"]


def test_failure_metadata_contains_schema_locations_without_candidate_values(context):
    observation, plan = context
    secret = "private-source-value"
    invalid = candidate(observation, taskPlanPatch={
        "missionId": observation.mission_id, "basePlanVersion": 1, "planVersion": 2,
        "addNodes": [{"key": "task:b", "title": "Verify", "objective": secret,
            "private-source-key": secret}],
    })
    llm = CandidateModel([invalid, invalid])
    with pytest.raises(StructuredGenerationError) as caught:
        runtime_decision.decide_runtime(observation=observation, task_plan=plan, llm=llm)
    report = {"message": str(caught.value), "metadata": caught.value.metadata, "audit": caught.value.audit}
    encoded = json.dumps(report)
    assert secret not in encoded and "private-source-key" not in encoded
    assert caught.value.metadata["validationFailures"][0]["fieldPath"] == ["taskPlanPatch", "addNodes", 0, "?"]
    assert caught.value.metadata["validationFailures"][0]["code"] == "extra_forbidden"


def test_transport_failure_during_correction_keeps_schema_diagnostic(context, monkeypatch):
    observation, plan = context
    calls = []

    def generate(_llm, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"data": candidate(observation, action="wrong")}
        raise StructuredGenerationError("MODEL_CONNECTION_INTERRUPTED", "Model connection interrupted", retryable=True)

    monkeypatch.setattr(runtime_decision, "call_planning_model", generate)
    with pytest.raises(StructuredGenerationError) as caught:
        runtime_decision.decide_runtime(observation=observation, task_plan=plan, llm=object())
    assert caught.value.code == "MODEL_CONNECTION_INTERRUPTED"
    assert caught.value.metadata["validationFailures"][0]["fieldPath"] == ["action"]
    assert calls[0]["planning_deadline"] == calls[1]["planning_deadline"]
