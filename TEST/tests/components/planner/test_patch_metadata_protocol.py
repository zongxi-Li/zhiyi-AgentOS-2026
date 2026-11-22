"""The revision model and accepted plan share one metadata namespace."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError as SchemaError
from pydantic import ValidationError

from components.planner.runtime_decision import decide_runtime
from contracts.planning import PlannedTask, TaskPlan, TaskPlanPatch
from contracts.runtime_planning import RuntimePlanningDecision
from runtime.orchestration.planning_commit import semantic_validation_rejection
from TEST.tests.components.planner.test_decision_structure_correction import snapshot, revision


@pytest.mark.parametrize("kind", ["task", "plan", "patch"])
def test_advertised_metadata_namespace_matches_all_three_contracts(kind):
    observation, plan = snapshot()
    model, payload = {
        "task": (PlannedTask, plan.nodes[0].model_dump(by_alias=True, mode="json")),
        "plan": (TaskPlan, plan.model_dump(by_alias=True, mode="json")),
        "patch": (TaskPlanPatch, revision(observation)["taskPlanPatch"]),
    }[kind]
    payload["metadata"] = {"source": "scope_revision", "rationale": "Preserve all useful work"}
    schema = model.model_json_schema(by_alias=True)
    Draft202012Validator(schema).validate(payload)
    assert model.model_validate(payload).metadata == payload["metadata"]
    payload["metadata"]["workspaceReview"] = {"revision": "not a plan metadata key"}
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)
    assert caught.value.errors()[0]["loc"] == ("metadata",)
    with pytest.raises(SchemaError):
        Draft202012Validator(schema).validate(payload)


def test_metadata_rejection_is_corrected_before_any_runtime_commit():
    observation, plan = snapshot()
    invalid = revision(observation)
    invalid["taskPlanPatch"]["metadata"] = {"workspaceReview": {"revision": "inferred_scope_reconciliation"}}
    valid = deepcopy(invalid)
    valid["taskPlanPatch"]["metadata"] = {"source": "scope_revision", "rationale": "Keep original obligations"}
    class Model:
        calls = []
        def generate_json(self, prompt, schema, **kwargs):
            request = json.loads(prompt)
            self.calls.append(request)
            if len(self.calls) == 1:
                return {"data": invalid}
            feedback = request["validationCorrection"]
            assert feedback["validationErrors"][0]["loc"] == ["taskPlanPatch", "metadata"]
            metadata = next(item for item in feedback["fieldOwnership"]
                if item["fieldPath"] == ["taskPlanPatch", "metadata"])
            assert "workspaceScope" in metadata["allowedFieldsAtParent"]
            assert "workspaceReview" not in metadata["allowedFieldsAtParent"]
            assert feedback["previousCandidate"] == invalid
            return {"data": valid}
    model = Model()
    result = decide_runtime(observation=observation, task_plan=plan, llm=model)
    assert result.action == "revise" and result.task_plan_patch.metadata == valid["taskPlanPatch"]["metadata"]
    assert len(model.calls) == 2


def test_acceptance_feedback_preserves_rule_location_without_candidate_values():
    observation, _ = snapshot()
    invalid = revision(observation)
    invalid["taskPlanPatch"]["metadata"] = {"workspaceReview": {"private": "CANDIDATE_BODY_SECRET"}}
    with pytest.raises(ValidationError) as caught:
        RuntimePlanningDecision.model_validate(invalid)
    rejection = semantic_validation_rejection(caught.value)
    assert rejection.code.value == "INVALID_PROPOSAL"
    assert "taskPlanPatch.metadata:value_error" in rejection.reason
    assert "CANDIDATE_BODY_SECRET" not in rejection.reason and "private" not in rejection.reason
