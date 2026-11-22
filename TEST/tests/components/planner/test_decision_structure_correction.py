"""Schema ownership feedback repairs generated data without weakening the contract."""
import copy
import json

import pytest
from pydantic import ValidationError

from adapters.model.protocols import StructuredGenerationError
from components.planner.runtime_decision import decide_runtime, decision_validation_feedback
from contracts.planning import PlannedTask, TaskPlan
from contracts.planning_results import PlanningModelTurn
from contracts.runtime_planning import RuntimePlanningDecision, RuntimePlanningObservation


def snapshot():
    mission = "mission_0123456789ab"
    plan = TaskPlan(missionId=mission,
        nodes=(PlannedTask(key="task:a", title="Inspect", objective="Inspect the source"),))
    observation = RuntimePlanningObservation(missionId=mission, runId="run_schema_ownership",
        graphId="graph", graphVersion=1, planVersion=1, wakeReason="resume", goal="Inspect the source",
        steps=({"stepId": "a", "taskKey": "task:a", "status": "pending"},), remainingStepIds=("a",))
    return observation, plan


def revision(observation):
    return {"observationId": observation.fingerprint(), "action": "revise", "reason": "Review the remaining gap",
        "taskPlanPatch": {"missionId": observation.mission_id, "basePlanVersion": 1, "planVersion": 2,
            "addNodes": [{"key": "task:b", "title": "Verify", "objective": "Verify remaining evidence"}]}}


def test_default_planner_regenerates_misnested_controls_from_exact_schema_ownership():
    observation, plan = snapshot()
    valid = revision(observation)
    invalid = copy.deepcopy(valid)
    invalid["taskPlanPatch"].update(waitFor=None, question=None, unknownControl={"private": "generated-data"})
    before = copy.deepcopy(invalid)

    class Model:
        requests = []

        def generate_json(self, prompt, schema, **kwargs):
            request = json.loads(prompt)
            self.requests.append(request)
            if len(self.requests) == 1:
                assert request["outputContract"]["fields"] == sorted(schema["properties"])
                return {"data": invalid}
            feedback = request["validationCorrection"]
            fields = {tuple(item["fieldPath"]): item for item in feedback["fieldOwnership"]}
            for field in ("waitFor", "question"):
                error = fields[("taskPlanPatch", field)]
                assert error["declaredAtAncestorPaths"] == [[field]]
                assert field not in error["allowedFieldsAtParent"]
            assert fields[("taskPlanPatch", "unknownControl")]["declaredAtAncestorPaths"] == []
            assert feedback["previousCandidate"] == invalid
            assert "null" in feedback["outputContract"]["instructions"]
            return {"data": valid}

    model = Model()
    decision = decide_runtime(observation=observation, task_plan=plan, llm=model)
    assert decision.action == "revise"
    assert decision.task_plan_patch.add_nodes[0].objective == "Verify remaining evidence"
    assert invalid == before
    assert len(model.requests) == 2
    assert model.requests[0]["observation"] == model.requests[1]["observation"]


@pytest.mark.parametrize("model", [RuntimePlanningDecision, PlanningModelTurn])
def test_nested_array_field_ownership_is_derived_from_refs_and_not_control_name_exceptions(model):
    observation, _ = snapshot()
    invalid = revision(observation)
    invalid["taskPlanPatch"]["addNodes"][0]["basePlanVersion"] = 1
    with pytest.raises(ValidationError) as caught:
        model.model_validate(invalid)
    _, _, feedback = decision_validation_feedback(invalid, caught.value,
        schema=model.model_json_schema(by_alias=True))
    error = feedback["fieldOwnership"][0]
    assert error["fieldPath"] == ["taskPlanPatch", "addNodes", 0, "basePlanVersion"]
    assert error["declaredAtAncestorPaths"] == [["taskPlanPatch", "basePlanVersion"]]
    assert "objective" in error["allowedFieldsAtParent"]
    assert "basePlanVersion" not in error["allowedFieldsAtParent"]


def test_identical_invalid_payload_still_stops_without_host_field_relocation():
    observation, plan = snapshot()
    invalid = revision(observation)
    invalid["taskPlanPatch"].update(waitFor=None, question=None)

    class RepeatingModel:
        calls = 0

        def generate_json(self, prompt, schema, **kwargs):
            self.calls += 1
            return {"data": {**invalid, "reason": f"Changed explanation {self.calls}"}}

    model = RepeatingModel()
    with pytest.raises(StructuredGenerationError) as caught:
        decide_runtime(observation=observation, task_plan=plan, llm=model)
    assert caught.value.code == "PLANNER_DECISION_NO_PROGRESS"
    assert model.calls == 2
    assert {tuple(item["fieldPath"]) for item in caught.value.metadata["validationFailures"]} == {
        ("taskPlanPatch", "waitFor"), ("taskPlanPatch", "question")}
    assert "previousCandidate" not in caught.value.metadata
    assert "fieldOwnership" not in caught.value.metadata


def test_optional_controls_remain_strict_objects_and_action_specific():
    observation, _ = snapshot()
    candidate = {"observationId": observation.fingerprint(), "action": "continue", "reason": "Continue work"}
    assert RuntimePlanningDecision.model_validate({**candidate, "taskPlanPatch": None,
        "waitFor": None, "question": None}).action == "continue"
    for controls in ({"taskPlanPatch": {}}, {"waitFor": {}}, {"question": {}}, {"unexpected": None}):
        with pytest.raises(ValidationError):
            RuntimePlanningDecision.model_validate({**candidate, **controls})
