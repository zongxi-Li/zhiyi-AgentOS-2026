"""Workspace discovery grounds planning without changing caller requirements."""
from copy import deepcopy

import pytest

from components.planner.workspace_discovery import (
    build_workspace_discovery_plan, workspace_discovery_decision, workspace_planning_material,
)
from contracts.planning import PlannedTask, TaskPlan, TaskPlanPatch, TaskPlanRelation, VerificationLoopPolicy
from contracts.runtime_planning import RuntimePlanningObservation, StepObservation
from contracts.acg.semantic_profile import TaskSemanticProfile


def inputs(*, explicit=False):
    requested = [{"path": ".", "kind": "directory", "operation": "read", "recursive": True}]
    profile = TaskSemanticProfile(primaryGoal="Review the selected repository",
        workspaceObservations=requested, keyConstraints=["Inspect source before making code claims"],
        expectedArtifacts=["Review report"])
    task_input = {"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"},
        "constraints": list(profile.key_constraints), "expectedArtifacts": list(profile.expected_artifacts)}
    if explicit:
        task_input["workspaceObservations"] = deepcopy(requested)
    return profile, task_input


@pytest.mark.parametrize("explicit", [False, True])
def test_discovery_preserves_requirements_and_declares_only_an_observation_prefix(explicit):
    profile, task_input = inputs(explicit=explicit)
    before = deepcopy((profile, task_input))
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    assert (profile, task_input) == before
    assert plan.metadata["workspaceDiscovery"] == {
        "version": 1, "phase": "discovery", "scopeOrigin": "explicit" if explicit else "inferred"}
    assert [node.capability_requirements for node in plan.nodes] == [
        ("task_understanding",), ("information_extraction",)]
    assert plan.nodes[-1].logical_role == "workspace_discovery"
    assert [(edge.source_key, edge.target_key) for edge in plan.relations] == [
        (plan.nodes[0].key, plan.nodes[1].key)]
    assert not plan.expected_artifacts and all(not node.produced_artifacts for node in plan.nodes)
    assert "recursive" in plan.nodes[-1].objective
    assert "does not require recursively enumerating every directory" in plan.nodes[-1].objective
    assert "workspaceBinding" not in plan.model_dump_json(by_alias=True)
    assert TaskPlan.model_validate_json(plan.model_dump_json(by_alias=True)) == plan


@pytest.mark.parametrize("defect", ["missing_binding", "unbound_workspace", "unbound_grant", "revoked", "no_scope", "input_only"])
def test_discovery_does_not_intercept_requests_without_live_workspace_reading_intent(defect):
    profile, task_input = inputs()
    if defect == "missing_binding":
        task_input.pop("workspaceBinding")
    elif defect == "unbound_workspace":
        task_input["workspaceBinding"].pop("workspaceId")
    elif defect == "unbound_grant":
        task_input["workspaceBinding"].pop("grantId")
    elif defect == "revoked":
        task_input["workspaceBinding"]["revoked"] = True
    elif defect == "no_scope":
        profile.workspace_observations = []
    else:
        profile.evidence_scope = "task_input_only"
    assert build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input) is None


def test_literal_file_request_is_preserved_instead_of_becoming_a_recursive_repository_scan():
    profile, task_input = inputs(explicit=True)
    profile.workspace_observations = [
        type(profile.workspace_observations[0])(path="src/parser.py", kind="file", operation="read")]
    task_input["workspaceObservations"] = [item.model_dump() for item in profile.workspace_observations]
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    scoped = plan.nodes[-1].constraints[0]["workspaceDiscovery"]["requestedObservations"]
    assert scoped == [{"path": "src/parser.py", "kind": "file", "operation": "read", "recursive": False}]


def test_textual_explicit_scope_profile_is_preserved_without_machine_scope_input():
    profile, task_input = inputs()
    profile.workspace_scope_origin = "explicit"
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    assert "workspaceObservations" not in task_input
    assert plan.metadata["workspaceDiscovery"]["scopeOrigin"] == "explicit"


def test_scope_metadata_does_not_admit_execution_identity_or_arbitrary_metadata():
    node = PlannedTask(key="inspect", title="Inspect", objective="Inspect actual source",
        metadata={"workspaceScope": {"phase": "formal"}})
    TaskPlan(missionId="mission_aabbccddeeff", nodes=(node,),
        metadata={"workspaceDiscovery": {"version": 1, "phase": "discovery", "scopeOrigin": "inferred"}})
    with pytest.raises(ValueError, match="execution identities"):
        PlannedTask(key="inspect", title="Inspect", objective="Inspect actual source",
            metadata={"workspaceScope": {"runId": "forged"}})
    with pytest.raises(ValueError, match="non-planning keys"):
        PlannedTask(key="inspect", title="Inspect", objective="Inspect actual source", metadata={"arbitrary": True})


def observe(plan, *, completed=None, **overrides):
    completed = {node.key for node in plan.nodes} if completed is None else set(completed)
    payload = dict(missionId=plan.mission_id, runId="run_discovery", graphId="discovery",
        graphVersion=plan.plan_version, planVersion=plan.plan_version, wakeReason="resume",
        goal="Review the selected repository",
        steps=tuple(StepObservation(stepId="step:" + node.key, taskKey=node.key,
            status="completed" if node.key in completed else "pending",
            outputRef="output:" + node.key if node.key in completed else None,
            auditOutcome="allow" if node.key in completed else None) for node in plan.nodes),
        remainingStepIds=tuple("step:" + node.key for node in plan.nodes if node.key not in completed))
    return RuntimePlanningObservation(**{**payload, **overrides})


def formal_plan(mission_id, *, source_key="analysis"):
    return TaskPlan(missionId=mission_id, nodes=(
        PlannedTask(key=source_key, title="Analyze source", objective="Analyze the observed source",
            capabilityRequirements=("analysis",)),
        PlannedTask(key="report", title="Review report", objective="Report cited findings",
            capabilityRequirements=("artifact_generation",), logicalRole="final_synthesis",
            producedArtifacts=("report",)),
    ), relations=(TaskPlanRelation(sourceKey=source_key, targetKey="report", relationType="depends_on"),),
        expectedArtifacts=("report",), metadata={"workspaceScope": {"version": 1,
            "requirements": [{"path": "src", "kind": "directory", "operation": "read", "recursive": True}],
            "rationale": "Discovery identified source under src", "sourceRefs": ["receipt:source-layout"]}})


def test_pending_discovery_runs_before_formal_builder_is_called():
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    def builder(**kwargs):
        pytest.fail("Formal planning requires committed discovery observations")
    decision = workspace_discovery_decision(observation=observe(plan, completed=()), task_plan=plan,
        formal_plan_builder=builder)
    assert decision.action == "continue" and decision.task_plan_patch is None


def test_committed_discovery_becomes_an_additive_suffix_with_scope_and_deliverables():
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    formal = formal_plan(plan.mission_id, source_key=plan.nodes[0].key)
    before = deepcopy((plan, formal))
    observation = observe(plan)
    calls = []
    def builder(**kwargs):
        calls.append(kwargs)
        return formal
    decision = workspace_discovery_decision(observation=observation, task_plan=plan, formal_plan_builder=builder)
    assert calls == [{"observation": observation, "task_plan": plan}]
    assert (plan, formal) == before
    patch = decision.task_plan_patch
    assert decision.action == "revise" and patch.expected_artifacts == ("report",)
    assert not patch.retire_keys and not patch.replace_keys and not patch.remove_relations
    assert {node.key for node in patch.add_nodes}.isdisjoint(node.key for node in plan.nodes)
    assert patch.metadata["workspaceDiscovery"] == {"version": 1, "phase": "formal", "scopeOrigin": "inferred"}
    assert patch.metadata["workspaceScope"] == formal.metadata["workspaceScope"]
    source, report = patch.add_nodes
    assert (plan.nodes[-1].key, source.key) in {(edge.source_key, edge.target_key) for edge in patch.relations}
    assert (source.key, report.key) in {(edge.source_key, edge.target_key) for edge in patch.relations}
    combined = TaskPlan(missionId=plan.mission_id, planVersion=patch.plan_version,
        nodes=(*plan.nodes, *patch.add_nodes), relations=(*plan.relations, *patch.relations),
        expectedArtifacts=patch.expected_artifacts, metadata={**plan.metadata, **patch.metadata})
    assert all(combined.nodes[i] == plan.nodes[i] for i in range(len(plan.nodes)))
    assert workspace_discovery_decision(observation=observe(combined), task_plan=combined,
        formal_plan_builder=builder) is None
    assert len(calls) == 1


def test_formal_suffix_preserves_parent_and_verification_control_references():
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    formal = formal_plan(plan.mission_id)
    analysis, report = formal.nodes
    formal = formal.model_copy(update={
        "nodes": (analysis, report.model_copy(update={"parent_key": analysis.key})),
        "control_policies": (VerificationLoopPolicy(bodyEntryKey=analysis.key,
            bodyExitKey=report.key, conditionSourceKey=report.key),),
    })
    patch = workspace_discovery_decision(observation=observe(plan), task_plan=plan,
        formal_plan_builder=lambda **kwargs: formal).task_plan_patch
    source, report = patch.add_nodes
    assert report.parent_key == source.key
    assert patch.control_policies[0].body_entry_key == source.key
    assert patch.control_policies[0].body_exit_key == patch.control_policies[0].condition_source_key == report.key


def test_full_length_semantic_keys_remain_valid_when_namespaced():
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    formal = formal_plan(plan.mission_id, source_key="a" * 200)
    patch = workspace_discovery_decision(observation=observe(plan), task_plan=plan,
        formal_plan_builder=lambda **kwargs: formal).task_plan_patch
    assert all(len(node.key) <= 200 for node in patch.add_nodes)


def test_namespacing_keeps_distinct_model_keys_and_existing_prefixes_disjoint():
    from contracts import stable_checksum
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    old_understanding, discovery = plan.nodes
    understanding = old_understanding.model_copy(update={"key": "workspace_formal:v2:0:existing"})
    plan = plan.model_copy(update={"nodes": (understanding, discovery), "relations": (
        TaskPlanRelation(sourceKey=understanding.key, targetKey=discovery.key, relationType="depends_on"),)})
    long_key = "a" * 200
    formal = formal_plan(plan.mission_id, source_key=long_key)
    extra = PlannedTask(key=stable_checksum({"key": long_key})[:32], title="Independent source check",
        objective="Check another discovered module", capabilityRequirements=("analysis",))
    formal = formal.model_copy(update={"nodes": (*formal.nodes, extra)})
    patch = workspace_discovery_decision(observation=observe(plan), task_plan=plan,
        formal_plan_builder=lambda **kwargs: formal).task_plan_patch
    added = {node.key for node in patch.add_nodes}
    assert len(added) == len(formal.nodes)
    assert added.isdisjoint(node.key for node in plan.nodes)


def test_a_status_label_without_committed_output_cannot_start_formal_planning():
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    observation = observe(plan)
    observation = observation.model_copy(update={"steps": tuple(
        step.model_copy(update={"output_ref": None}) for step in observation.steps)})
    def builder(**kwargs):
        pytest.fail("A completed status label does not supply committed discovery evidence")
    decision = workspace_discovery_decision(observation=observation, task_plan=plan, formal_plan_builder=builder)
    assert decision.action == "wait" and decision.task_plan_patch is None


@pytest.mark.parametrize("defect", ["foreign_mission", "missing_scope"])
def test_discovery_does_not_accept_a_formal_suffix_without_the_same_mission_and_a_scope(defect):
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    formal = formal_plan("mission_112233445566" if defect == "foreign_mission" else plan.mission_id)
    if defect == "missing_scope":
        formal = formal.model_copy(update={"metadata": {}})
    with pytest.raises(ValueError, match="another Mission|workspaceScope"):
        workspace_discovery_decision(observation=observe(plan), task_plan=plan,
            formal_plan_builder=lambda **kwargs: formal)


def test_discovery_preserves_failure_handling_and_waits_without_an_online_planner():
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    assert workspace_discovery_decision(observation=observe(plan, failedStepIds=("step:inspect",)),
        task_plan=plan, formal_plan_builder=None) is None
    decision = workspace_discovery_decision(observation=observe(plan), task_plan=plan, formal_plan_builder=None)
    assert decision.action == "wait" and decision.task_plan_patch is None


def test_optional_patch_deliverables_preserve_legacy_serialization():
    patch = TaskPlanPatch(missionId="mission_aabbccddeeff", basePlanVersion=1, planVersion=2)
    assert "expectedArtifacts" not in patch.model_dump(mode="json", by_alias=True)
    declared = patch.model_copy(update={"expected_artifacts": ("report",)})
    assert declared.model_dump(mode="json", by_alias=True)["expectedArtifacts"] == ["report"]


def test_formal_understanding_root_reuses_the_committed_prefix_and_inherits_caller_constraints():
    from components.planner.service import apply_task_plan_patch
    from components.auditor.human_review_policy import bind_review_policy, validate_review_policy

    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    requirement = {"type": "mission_constraint", "constraintId": "constraint:read",
        "value": "Cite actually inspected source", "sourceRefs": ["constraint:read"]}
    plan = plan.model_copy(update={"nodes": tuple(node.model_copy(update={"constraints": [
        *node.constraints, deepcopy(requirement)]}) for node in plan.nodes)})
    plan = bind_review_policy(plan, "human_in_loop")
    before = deepcopy(plan)
    formal = formal_plan(plan.mission_id)
    understanding = PlannedTask(key="fresh-understanding", title="Understand mission again",
        objective="Understand this mission", capabilityRequirements=("task_understanding",))
    analysis = formal.nodes[0].model_copy(update={"parent_key": understanding.key, "constraints": [
        {"type": "mission_constraint", "value": "Model tried replacing the original requirement"},
        {"type": "user_human_review", "mode": "auto"}, {"type": "analysis_focus", "value": "imports"}]})
    formal = formal.model_copy(update={"nodes": (understanding, analysis, formal.nodes[-1]),
        "relations": (TaskPlanRelation(sourceKey=understanding.key, targetKey=analysis.key,
            relationType="depends_on"), *formal.relations)})
    patch = workspace_discovery_decision(observation=observe(plan), task_plan=plan,
        formal_plan_builder=lambda **kwargs: formal).task_plan_patch
    applied = apply_task_plan_patch(plan, patch)
    assert plan == before
    assert sum(node.capability_requirements == ("task_understanding",) for node in applied.nodes) == 1
    assert patch.add_nodes[0].parent_key == plan.nodes[0].key
    assert all(requirement in node.constraints for node in patch.add_nodes)
    assert {"type": "analysis_focus", "value": "imports"} in patch.add_nodes[0].constraints
    assert all(not any("Model tried" in str(item) for item in node.constraints) for node in patch.add_nodes)
    validate_review_policy(applied, "human_in_loop")
    old_keys = {node.key for node in plan.nodes}
    assert not any(relation.target_key in old_keys for relation in patch.relations)
    assert all(applied.nodes[index] == node for index, node in enumerate(plan.nodes))
    assert applied.expected_artifacts == ("report",)


def test_understanding_with_an_incoming_dependency_remains_new_work():
    profile, task_input = inputs()
    plan = build_workspace_discovery_plan("mission_aabbccddeeff", profile, task_input)
    formal = formal_plan(plan.mission_id)
    analysis, report = formal.nodes
    understanding = PlannedTask(key="module-understanding", title="Understand the inspected module",
        objective="Interpret the analysis findings", capabilityRequirements=("task_understanding",))
    formal = formal.model_copy(update={"nodes": (analysis, understanding, report), "relations": (
        TaskPlanRelation(sourceKey=analysis.key, targetKey=understanding.key, relationType="depends_on"),
        TaskPlanRelation(sourceKey=understanding.key, targetKey=report.key, relationType="depends_on"))})
    patch = workspace_discovery_decision(observation=observe(plan), task_plan=plan,
        formal_plan_builder=lambda **kwargs: formal).task_plan_patch
    assert len(patch.add_nodes) == 3
    assert sum(node.capability_requirements == ("task_understanding",) for node in patch.add_nodes) == 1


def test_workspace_material_keeps_agent_claims_separate_from_authenticated_read_bodies():
    material = {"sources": [{"sourceRef": "output:discovery", "finding": "Unverified source claim"}],
        "observations": [{"receiptRef": "receipt:file", "output": {"text": "actual source"}}]}
    before = deepcopy(material)
    prompt = workspace_planning_material(material)
    assert material == before
    assert prompt["sources"]["trustClass"] == "agent_generated"
    assert prompt["sources"]["content"] == material["sources"]
    assert prompt["observations"]["trustClass"] == "verified_evidence"
    assert prompt["observations"]["content"] == material["observations"]
