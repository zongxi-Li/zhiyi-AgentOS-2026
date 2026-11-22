"""Initial planning must target the DAG-only formal materialization contract."""
from copy import deepcopy

import pytest

from components.planner.task_decomposer import TaskDecomposer, TaskDecompositionError
from contracts.acg.semantic_profile import TaskSemanticProfile
from support.packs.native_capabilities import build_default_capability_catalog


class Model:
    def __init__(self, *responses):
        self.responses = responses
        self.calls = []

    def generate_json(self, prompt, schema, **kwargs):
        self.calls.append(dict(prompt=prompt, schema=deepcopy(schema), **kwargs))
        return deepcopy(self.responses[len(self.calls) - 1])


def candidate(loop=True):
    return {"tasks": [
        {"key": key, "title": key, "objective": objective, "capabilityId": capability,
         "acceptanceCriteria": ["Evidence is recorded"], "sourceRefs": [],
         "logicalRole": role, "decompositionRationale": "Preserve acceptance obligations"}
        for key, objective, capability, role in (
            ("understand", "Resolve activity goals and constraints", "task_understanding", "task"),
            ("refine", "Prepare and correct the activity deliverables", "solution_design", "decision"),
            ("verify", "Verify every activity acceptance criterion", "verification", "verification"))],
        "relations": [{"sourceKey": "understand", "targetKey": "refine", "relationType": "depends_on"},
                      {"sourceKey": "refine", "targetKey": "verify", "relationType": "depends_on"}],
        "controlPolicies": [{"type": "verification_loop", "bodyEntryKey": "refine", "bodyExitKey": "verify",
                             "conditionSourceKey": "verify", "maxRevisions": 2}] if loop else []}


def plan(model, strategy="initial_commit_candidate", full=False, existing_tasks=()):
    return TaskDecomposer(build_default_capability_catalog(), model).decompose(
        mission_id="mission_0123456789ab",
        profile=TaskSemanticProfile(primaryGoal="Prepare and verify activity files",
                                    requiredCapabilities=["task_understanding", "solution_design", "verification"]),
        strategy=strategy, task_input={"_effectiveCapabilityProfile": "full"} if full else {}, use_llm=True,
        existing_semantic_tasks=existing_tasks)


def test_initial_commit_repairs_a_loop_candidate_before_acceptance():
    model = Model(candidate(), candidate(False))
    result = plan(model)
    assert not result.control_policies
    assert len(model.calls) == 2
    assert model.calls[0]["schema"]["properties"]["controlPolicies"]["maxItems"] == 0
    assert "INITIAL DAG CONTRACT" in model.calls[0]["prompt"]
    assert "INITIAL_CONTROL_GRAPH_UNSUPPORTED" in model.calls[1]["prompt"]
    assert {"refine", "verify"}.issubset({node.title for node in result.nodes})


def test_initial_commit_rejects_persistently_unsupported_loops_after_one_repair():
    model = Model(candidate(), candidate())
    with pytest.raises(TaskDecompositionError, match="INITIAL_CONTROL_GRAPH_UNSUPPORTED"):
        plan(model)
    assert len(model.calls) == 2


def test_existing_non_initial_planning_keeps_supported_verification_loops():
    model = Model(candidate())
    result = plan(model, strategy="dynamic_generation")
    assert len(result.control_policies) == 1
    assert len(model.calls) == 1


def test_staged_initial_planning_repairs_only_the_relation_unit():
    payload = candidate()
    outline = {"tasks": [{k: task[k] for k in ("key", "title", "capabilityId", "logicalRole", "sourceRefs")}
                         for task in payload["tasks"]]}
    relations = {k: payload[k] for k in ("relations", "controlPolicies")}
    model = Model(outline, {"tasks": payload["tasks"]}, relations, {**relations, "controlPolicies": []})
    result = plan(model, full=True)
    assert not result.control_policies
    assert len(model.calls) == 4
    assert model.calls[2]["schema"]["properties"]["controlPolicies"]["maxItems"] == 0
    assert "INITIAL DAG CONTRACT" in model.calls[2]["prompt"]
    assert model.calls[-1]["prompt_version"].endswith(".relations.repair1")
    assert "INITIAL_CONTROL_GRAPH_UNSUPPORTED" in model.calls[-1]["prompt"]


def test_workspace_formal_graph_uses_forward_local_reviews_with_same_dag_materializer():
    model = Model(candidate(), candidate(False))
    result = plan(model, strategy="workspace_evidence_planning")
    assert not result.control_policies
    assert model.calls[0]["schema"]["properties"]["controlPolicies"]["maxItems"] == 0
    assert "FORMAL WORKSPACE DAG CONTRACT" in model.calls[0]["prompt"]
    assert "FORMAL_CONTROL_GRAPH_UNSUPPORTED" in model.calls[1]["prompt"]


@pytest.mark.parametrize("reference", ["workspace_discovery:inspect", "undeclared-task"])
@pytest.mark.parametrize("full", [False, True])
def test_formal_plan_repairs_only_dangling_relations(reference, full):
    payload = candidate(False)
    payload["relations"].append({"sourceKey": reference, "targetKey": "refine", "relationType": "depends_on"})
    invalid_patch = {"operations": [{"op": "remove_relation", "relationIndex": 0}]}
    valid_patch = {"operations": [{"op": "remove_relation", "relationIndex": 2}]}
    if full:
        outline = {"tasks": [{key: task[key] for key in ("key", "title", "capabilityId", "logicalRole", "sourceRefs")}
                             for task in payload["tasks"]]}
        replies = (outline, {"tasks": payload["tasks"]}, {k: payload[k] for k in ("relations", "controlPolicies")})
    else:
        replies = (payload,)
    model = Model(*replies, invalid_patch, valid_patch)
    result = plan(model, strategy="workspace_evidence_planning", full=full,
                  existing_tasks=({"key": "workspace_discovery:inspect"},))
    assert "Completed discovery tasks are evidence context." in model.calls[0]["prompt"]
    assert '"fieldPath": ["relations", 2, "sourceKey"]' in model.calls[-2]["prompt"]
    assert '"originalRelationIndex": 2' in model.calls[-2]["prompt"]
    assert "endpoint repair can only replace or remove each flagged relation once" in model.calls[-1]["prompt"]
    expected = plan(Model(candidate(False)), strategy="workspace_evidence_planning")
    assert result == expected


def test_formal_plan_reports_an_external_parent_before_compiling():
    payload = candidate(False)
    payload["tasks"][1]["parentKey"] = "workspace_discovery:inspect"
    model = Model(payload, payload)
    with pytest.raises(TaskDecompositionError) as error:
        plan(model, strategy="workspace_evidence_planning")
    assert error.value.metadata["validationFailures"][0]["fieldPath"] == ["tasks", 1, "parentKey"]
    assert "unknown_task_reference" in model.calls[1]["prompt"]
