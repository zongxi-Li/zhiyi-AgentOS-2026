"""Bounded corrections must use fresh errors without replaying valid units."""
from copy import deepcopy
import json

import pytest

from adapters.model.protocols import StructuredGenerationError
from components.planner.task_decomposer import TaskDecomposer, TaskDecompositionError, TASK_PLAN_MAX_REPAIRS, TASK_DECOMPOSITION_PROMPT_VERSION
from contracts.acg.schema import ComplexityLevel
from contracts.acg.semantic_profile import TaskSemanticProfile
from support.packs.native_capabilities import build_default_capability_catalog
from TEST.tests.components.planner.test_hierarchical_task_decomposition import _PlanLLM, _SequencePlanLLM


def task():
    return {"key": "understand", "title": "Understand", "objective": "Resolve supplied requirements",
            "capabilityId": "task_understanding", "acceptanceCriteria": ["Scope is explicit"], "sourceRefs": []}


def profile(**kwargs):
    return TaskSemanticProfile(primaryGoal="Resolve requirements", requiredCapabilities=["task_understanding"],
                               estimatedComplexity=ComplexityLevel.SIMPLE, **kwargs)


def run(llm, **kwargs):
    return TaskDecomposer(build_default_capability_catalog(), llm, progress_callback=kwargs.pop("progress", None)).decompose(
        mission_id="mission_0123456789ab", profile=kwargs.pop("profile", profile()),
        strategy="dynamic_generation", task_input=kwargs.pop("task_input", {}), use_llm=True, **kwargs,
    )


@pytest.mark.parametrize("successful_round", [0, 1, 2, 3])
def test_corrections_receive_latest_problem_and_stop_on_success(successful_round):
    invalid = []
    for field, value in (("objective", ""), ("acceptanceCriteria", []), ("capabilityId", "unknown_capability")):
        invalid.append({"tasks": [{**task(), field: value}], "relations": []})
    valid = {"tasks": [task()], "relations": []}
    llm = _SequencePlanLLM(*invalid[:successful_round], valid)
    events = []
    plan = run(llm, progress=events.append)
    assert len(llm.calls) == successful_round + 1
    assert plan.nodes[0].objective == task()["objective"]
    expected = ["business_objective_required", "acceptance_criteria_required", "unknown_capability"]
    for attempt in range(1, successful_round + 1):
        prompt = llm.calls[attempt]["prompt"]
        assert f"Repair attempt {attempt}/{TASK_PLAN_MAX_REPAIRS}" in prompt
        assert f'"code": "{expected[attempt - 1]}"' in prompt
        assert "Validation detail:" in prompt
        assert "Previous invalid TaskPlan JSON: " + json.dumps(invalid[attempt - 1]) in prompt
        if attempt > 1:
            assert f'"code": "{expected[attempt - 2]}"' not in prompt
    starts = [event["callKey"] for event in events if event.get("eventType") == "planner.stage.started"]
    assert starts == ["decompose", "repair", "repair:2", "repair:3"][:successful_round + 1]


def test_three_repairs_share_the_existing_deadline(monkeypatch):
    import components.planner.complexity as complexity
    clock = [100.0]
    monkeypatch.setattr(complexity, "monotonic", lambda: clock[0])

    class ClockLLM(_PlanLLM):
        def generate_json(self, prompt, schema, **kwargs):
            result = super().generate_json(prompt, schema, **kwargs)
            clock[0] += 0.1
            return result

    llm = ClockLLM({"tasks": [], "relations": []})
    with pytest.raises(TaskDecompositionError):
        run(llm, planning_deadline=100.5)
    assert [call["timeout_seconds"] for call in llm.calls] == pytest.approx([0.5, 0.4, 0.3, 0.2])


@pytest.mark.parametrize("code,calls", [("MODEL_TIMEOUT", 3), ("MODEL_INPUT_BUDGET_EXCEEDED", 1)])
def test_transport_and_input_failures_do_not_trigger_content_corrections(monkeypatch, code, calls):
    monkeypatch.setattr("components.planner.complexity.PLANNING_MAX_RETRIES", 2)

    class FailedLLM(_PlanLLM):
        def generate_json(self, prompt, schema, **kwargs):
            super().generate_json(prompt, schema, **kwargs)
            raise StructuredGenerationError(code, "provider cannot complete the call")

    llm = FailedLLM({})
    with pytest.raises(TaskDecompositionError):
        run(llm)
    assert len(llm.calls) == calls
    assert all("Repair attempt" not in call["prompt"] for call in llm.calls)


def test_staged_third_detail_correction_keeps_outline_and_prior_units():
    outline = {"tasks": [{key: value for key, value in task().items() if key != "objective"}]}
    invalid = {"tasks": [{**task(), "objective": ""}]}
    details = {"tasks": [task()]}
    llm = _SequencePlanLLM(outline, invalid, invalid, invalid, details, {"relations": [], "controlPolicies": []})
    run(llm, task_input={"_effectiveCapabilityProfile": "full"})
    assert len(llm.calls) == 6
    assert [call["prompt_version"].removeprefix(TASK_DECOMPOSITION_PROMPT_VERSION) for call in llm.calls] == [
        ".outline", ".detail", ".detail.repair1", ".detail.repair2", ".detail.repair3", ".relations",
    ]
    for attempt in (1, 2, 3):
        assert '"code": "business_objective_required"' in llm.calls[attempt + 1]["prompt"]
        assert '"fieldPath": ["tasks", 0, "objective"]' in llm.calls[attempt + 1]["prompt"]


@pytest.mark.parametrize("invalid_patch,detail", [
    ({"operations": [{"op": "remove_relation", "relationIndex": 99}]}, "repair patch relationIndex is invalid"),
    ({"operations": [None]}, "operations must be an array of objects"),
    ({"operations": "invalid"}, "operations must be an array of objects"),
])
def test_failed_patch_is_explained_without_rewriting_frozen_tasks(invalid_patch, detail):
    initial = {"tasks": [task(), {**task(), "key": "other", "objective": "Check a second requirement"}],
               "relations": [{"sourceKey": "understand", "targetKey": "other", "relationType": "depends_on"},
                             {"sourceKey": "other", "targetKey": "understand", "relationType": "depends_on"}]}
    valid_patch = {"operations": [{"op": "remove_relation", "relationIndex": 1}]}
    llm = _SequencePlanLLM(initial, invalid_patch, valid_patch)
    plan = run(llm)
    assert len(llm.calls) == 3
    assert detail in llm.calls[2]["prompt"]
    assert '"code": "topology_patch_invalid"' in llm.calls[2]["prompt"]
    assert "Frozen Tasks:" in llm.calls[2]["prompt"]
    assert all("operations" in call["schema"]["properties"] for call in llm.calls[1:])
    assert {node.key: node.objective for node in plan.nodes if node.key in {"understand", "other"}} == {
        row["key"]: row["objective"] for row in initial["tasks"]
    }


def test_coverage_corrections_receive_latest_assignment_errors():
    original = {**task(), "sourceRefs": ["artifact:3"]}
    initial = {"tasks": [original], "relations": []}
    assignments = {"assignments": [{"sourceRef": f"artifact:{index}", "taskKey": "understand", "rationale": "Own the requirement"}
                                    for index in (1, 2)]}
    incomplete = {"assignments": assignments["assignments"][:1]}
    unknown = deepcopy(assignments)
    unknown["assignments"][0]["taskKey"] = "unknown"
    llm = _SequencePlanLLM(initial, incomplete, unknown, assignments)
    plan = run(llm, profile=profile(expectedArtifacts=["Summary", "Requirements register", "Decision record"]))
    assert len(llm.calls) == 4
    assert '"code": "source_assignment_coverage"' in llm.calls[2]["prompt"]
    assert '"code": "source_assignment_invalid"' in llm.calls[3]["prompt"]
    assert plan.nodes[0].objective == original["objective"]
    assert plan.nodes[0].source_refs == ("artifact:3", "artifact:1", "artifact:2")


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_relation_unit_shares_three_repairs_across_json_and_topology_errors(repair_succeeds):
    tasks = [task(), {**task(), "key": "other", "objective": "Check a second requirement"}]
    outline = {"tasks": [{key: row[key] for key in ("key", "title", "capabilityId", "sourceRefs")} for row in tasks]}
    cyclic = {"relations": [
        {"sourceKey": "understand", "targetKey": "other", "relationType": "depends_on"},
        {"sourceKey": "other", "targetKey": "understand", "relationType": "depends_on"},
    ], "controlPolicies": []}
    invalid = {"operations": [{"op": "remove_relation", "relationIndex": 99}]}
    valid = {"operations": [{"op": "remove_relation", "relationIndex": 1}]}

    class Replies(_SequencePlanLLM):
        def generate_json(self, prompt, schema, **kwargs):
            result = super().generate_json(prompt, schema, **kwargs)
            if isinstance(result, Exception):
                raise result
            return result

    llm = Replies(outline, {"tasks": tasks}, StructuredGenerationError("MODEL_OUTPUT_INVALID_JSON", "invalid JSON"),
                  cyclic, invalid, valid if repair_succeeds else invalid)
    events = []
    if repair_succeeds:
        plan = run(llm, task_input={"_effectiveCapabilityProfile": "full"}, progress=events.append)
        assert {node.key for node in plan.nodes} == {"understand", "other"}
    else:
        with pytest.raises(TaskDecompositionError, match="relationIndex is invalid"):
            run(llm, task_input={"_effectiveCapabilityProfile": "full"}, progress=events.append)
    assert len(llm.calls) == 6
    starts = [event["callKey"] for event in events if event.get("eventType") == "planner.stage.started"]
    assert starts[-4:] == ["relations", "relations.repair", "relations.cycle-repair:2", "relations.cycle-repair:3"]
    assert '"code": "MODEL_OUTPUT_INVALID_JSON"' in llm.calls[3]["prompt"]
    assert '"code": "dependency_cycle"' in llm.calls[4]["prompt"]
    assert '"code": "topology_patch_invalid"' in llm.calls[5]["prompt"]
