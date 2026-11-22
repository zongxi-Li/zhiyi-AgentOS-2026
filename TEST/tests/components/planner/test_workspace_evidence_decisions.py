"""Evidence-informed scope decisions retain local execution and delivery gates."""
import json
from types import SimpleNamespace

import pytest

from components.planner.runtime_decision import decide_runtime
from components.planner.service import ACGPlanningError, PlanningEngine, apply_task_plan_patch
from contracts.planning import PlannedTask, TaskPlan, TaskPlanPatch, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningObservation


def context(*, phase="formal", analysis_done=True):
    nodes = tuple(PlannedTask(key=key, title=key, objective="Inspect and report actual repository sources",
        capabilityRequirements=(capability,), logicalRole=role,
        producedArtifacts=("report",) if key == "report" else ())
        for key, capability, role in (("understand", "task_understanding", "understanding"),
            ("read", "information_extraction", "workspace_acquisition"),
            ("analyze", "analysis", "analysis"), ("report", "artifact_generation", "final_synthesis")))
    plan = TaskPlan(missionId="mission_0123456789ab", nodes=nodes,
        relations=tuple(TaskPlanRelation(sourceKey=source.key, targetKey=target.key, relationType="depends_on")
            for source, target in zip(nodes, nodes[1:])),
        metadata={"workspaceDiscovery": {"version": 1, "phase": phase, "scopeOrigin": "inferred"}} if phase else {})
    completed = {"understand", "read", *({"analyze"} if analysis_done else set())}
    observation = RuntimePlanningObservation(missionId=plan.mission_id, runId="run_evidence",
        graphId="graph_evidence", graphVersion=2, planVersion=1, wakeReason="resume", goal="Review source",
        steps=tuple(dict(stepId=node.key, taskKey=node.key,
            status="completed" if node.key in completed else "pending",
            outputRef="output:" + node.key if node.key in completed else None) for node in nodes),
        remainingStepIds=tuple(node.key for node in nodes if node.key not in completed),
        workspaceObservations=({"kind": "directory", "path": ".", "operation": "read", "recursive": True,
            "complete": False, "missingReads": ["src/main.py"], "missingReadCount": 1,
            "missingListings": [], "missingListingCount": 0, "unsupportedEntries": []},),
        workspaceDiscovery={"version": 1, "phase": phase, "scopeOrigin": "inferred",
            "contextRef": "tool:sealed-context"} if phase else None)
    return observation, plan


class Model:
    def __init__(self, respond):
        self.respond = respond
        self.requests = []

    def generate_json(self, prompt, schema, **kwargs):
        request = json.loads(prompt)
        self.requests.append(request)
        return self.respond(request)


def test_formal_model_reviews_host_candidate_and_receives_separate_source_trust():
    observation, plan = context()
    model = Model(lambda request: {"observationId": request["observationId"], "action": "wait",
        "reason": "Resolve a repository-specific question before scheduling more reads"})
    calls = []

    def materials(observed):
        calls.append(observed.fingerprint())
        return {"sources": [{"sourceRef": "output:read", "findings": {"suspected": "needs review"}}],
            "observations": [{"tool": "fs.read", "path": "package.json", "receiptRef": "receipt:config",
                "output": {"content": '{"test":"actual-observed-command"}'}}]}

    decision = decide_runtime(observation=observation, task_plan=plan, llm=model,
        workspace_context_provider=materials)
    assert decision.action == "wait" and len(model.requests) == 1
    request = model.requests[0]
    assert request["workspaceReviewFallback"]["action"] == "revise"
    assert request["workspaceMaterials"]["sources"]["trustClass"] == "agent_generated"
    assert request["workspaceMaterials"]["observations"]["trustClass"] == "verified_evidence"
    assert "actual-observed-command" in json.dumps(request["workspaceMaterials"])
    assert "actual-observed-command" not in observation.model_dump_json()
    assert calls == [observation.fingerprint()]


def test_ready_delivery_with_gaps_is_corrected_into_local_acquisition_patch():
    observation, plan = context()

    def respond(request):
        if "validationCorrection" not in request:
            return {"observationId": request["observationId"], "action": "continue", "reason": "Deliver now"}
        assert request["validationCorrection"]["validationErrors"][0]["loc"] == ["action"]
        return request["workspaceReviewFallback"]

    model = Model(respond)
    decision = decide_runtime(observation=observation, task_plan=plan, llm=model)
    assert decision.action == "revise" and len(model.requests) == 2
    assert len(decision.task_plan_patch.add_nodes) == 2
    assert not decision.task_plan_patch.retire_keys and not decision.task_plan_patch.replace_keys
    assert {node.logical_role for node in decision.task_plan_patch.add_nodes} == {
        "workspace_acquisition", "workspace_review"}


def test_intermediate_analysis_can_advance_with_partial_coverage():
    observation, plan = context(analysis_done=False)
    model = Model(lambda request: {"observationId": request["observationId"], "action": "continue",
        "reason": "Analyze the current findings before the next review"})
    assert decide_runtime(observation=observation, task_plan=plan, llm=model).action == "continue"
    assert len(model.requests) == 1


def test_historical_workspace_policy_keeps_existing_deterministic_path():
    observation, plan = context(phase=None)
    model = Model(lambda _: pytest.fail("Historical run must not be migrated to a new planning strategy"))
    assert decide_runtime(observation=observation, task_plan=plan, llm=model).action == "revise"
    assert not model.requests


def test_formal_patch_can_declare_artifacts_but_cannot_discard_existing_ones():
    _, plan = context(phase=None)
    patch = TaskPlanPatch(missionId=plan.mission_id, basePlanVersion=1, planVersion=2, expectedArtifacts=("report",))
    revised = apply_task_plan_patch(plan, patch)
    assert revised.expected_artifacts == ("report",)
    preserve = TaskPlanPatch(missionId=plan.mission_id, basePlanVersion=2, planVersion=3)
    assert apply_task_plan_patch(revised, preserve).expected_artifacts == ("report",)
    discard = preserve.model_copy(update={"expected_artifacts": ()})
    with pytest.raises(ACGPlanningError, match="cannot discard"):
        apply_task_plan_patch(revised, discard)


def test_null_material_manifest_refs_do_not_turn_execution_evidence_into_a_workset():
    from components.planner.intent_analyzer import IntentParser
    from components.planner.semantic_planner import SemanticPlanner
    from support.packs.native_capabilities import build_default_capability_catalog

    observation, plan = context(phase="discovery")
    catalog = build_default_capability_catalog()
    engine = SimpleNamespace(
        workspace_context_provider=lambda _: {"sources": [{"sourceRef": "output:discovery", "findings": {}}],
            "observations": [{"tool": "fs.read", "path": "README.md", "receiptRef": "receipt:readme",
                "output": {"text": "Observed repository configuration"}}]},
        workspace_planning_input={"materialRefs": None, "deterministicIntent": True,
            "workspaceObservations": [{"path": "README.md", "kind": "file"}]},
        workspace_planning_domain="general", workspace_planning_task_type="review",
        _planning_total_timeout_seconds=lambda: 60,
        intent_parser=IntentParser(None, catalog), semantic_planner=SemanticPlanner(catalog))
    formal = PlanningEngine._plan_from_workspace_discovery(engine, observation=observation, task_plan=plan)
    assert all(node.workset is None for node in formal.nodes)
    assert set(formal.metadata["workspaceScope"]["sourceRefs"]) == {"output:discovery", "receipt:readme"}
    assert engine.workspace_planning_input["materialRefs"] is None


def test_direct_engine_routes_the_discovery_prefix_before_later_intent_capabilities():
    from components.mission.store import WorkflowRegistry
    from adapters.agent import AgentRegistry
    from adapters.agent.base import AgentProfile
    from support.packs.native_capabilities import build_default_capability_catalog

    agents = AgentRegistry()
    agents.register(SimpleNamespace(profile=AgentProfile(agentName="workspace-reader", domain="general",
        capabilities=["task_understanding", "information_extraction"])))
    engine = PlanningEngine(workflow_registry=WorkflowRegistry(), agent_registry=agents,
        capability_catalog=build_default_capability_catalog())
    result = engine.plan(mission_id="mission_0123456789ab",
        intent="Read and review repository source, analyze findings and produce report", force_dynamic=True,
        deterministic_intent=True, task_input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"},
            "workspaceObservations": [{"path": ".", "kind": "directory", "operation": "read", "recursive": True}]})
    assert result.task_plan.metadata["workspaceDiscovery"]["phase"] == "discovery"
    assert {node.logical_role for node in result.task_plan.nodes} == {"understanding", "workspace_discovery"}
    assert {step.capability for step in result.blueprint.step_nodes()} == {
        "task_understanding", "information_extraction"}


def test_formal_intent_receives_the_accepted_explicit_scope_without_a_machine_input_field():
    from components.planner.intent_analyzer import IntentParser
    from components.planner.workspace_discovery import build_workspace_discovery_plan
    from support.packs.native_capabilities import build_default_capability_catalog
    from contracts.acg.semantic_profile import TaskSemanticProfile

    original_scope = [{"kind": "directory", "path": ".", "operation": "read", "recursive": True}]
    profile = TaskSemanticProfile(primaryGoal="Read all repository sources", workspaceObservations=original_scope,
        workspaceScopeOrigin="explicit")
    original_input = {"workspaceBinding": {"workspaceId": "one", "grantId": "grant-one"}}
    discovery = build_workspace_discovery_plan("mission_0123456789ab", profile, original_input)
    observation, _ = context(phase="discovery")
    model = Model(lambda request: {"primaryGoal": "Review repository", "evidenceScope": "authorized_sources",
        "webExtraction": "snippets", "requiredCapabilities": ["information_extraction", "analysis"],
        "estimatedComplexity": "simple", "workspaceObservations": [{"kind": "directory", "path": "src",
            "operation": "read", "recursive": True, "excludePaths": ["src/large-module"]}]})
    captured = []

    def plan_profile(**kwargs):
        captured.append(kwargs)
        return context()[1]

    engine = SimpleNamespace(workspace_context_provider=lambda _: {
        "sources": [{"sourceRef": "output:discovery", "findings": {}}], "observations": []},
        workspace_planning_input=original_input,
        workspace_planning_domain="general", workspace_planning_task_type="review",
        _planning_total_timeout_seconds=lambda: 60,
        intent_parser=IntentParser(model, build_default_capability_catalog()),
        semantic_planner=SimpleNamespace(plan_profile=plan_profile))
    formal = PlanningEngine._plan_from_workspace_discovery(engine,
        observation=observation, task_plan=discovery)
    assert formal.metadata["workspaceScope"]["requirements"] == original_scope
    assert captured[0]["task_input"]["workspaceObservations"] == original_scope
    assert [item.model_dump(by_alias=True, mode="json")
        for item in captured[0]["profile"].workspace_observations] == original_scope
    assert "workspaceObservations" not in original_input


@pytest.mark.parametrize("stage", ["formal_intent", "formal_decomposition"])
def test_formal_planning_errors_keep_stage_and_safe_contract_diagnostics(stage):
    from adapters.model.protocols import StructuredGenerationError
    from pydantic import ValidationError

    marker = "private model response must not become an audit diagnostic"
    contract_error = ValidationError.from_exception_data("GeneratedPlan", [{
        "type": "string_type", "loc": ("tasks", 0, "objective"), "input": marker}])

    def fail(**kwargs):
        raise ValueError(marker) from contract_error

    observation, plan = context(phase="discovery")
    parser = SimpleNamespace(parse=fail if stage == "formal_intent" else lambda **_: SimpleNamespace(
        workspace_observations=[SimpleNamespace(model_dump=lambda **_: {
            "kind": "file", "path": "README.md", "operation": "read", "recursive": False})]),
        last_audit={"provider": "deepseek", "model": "deepseek-flash", "rawModelResponse": marker})
    decomposer = SimpleNamespace(last_audit={"provider": "deepseek", "model": "deepseek-flash",
        "rawModelResponse": marker})
    engine = SimpleNamespace(workspace_context_provider=lambda _: {
        "sources": [{"sourceRef": "output:discovery", "findings": {}}], "observations": []},
        workspace_planning_input={}, workspace_planning_domain="general", workspace_planning_task_type="review",
        _planning_total_timeout_seconds=lambda: 60, intent_parser=parser,
        semantic_planner=SimpleNamespace(plan_profile=fail, task_decomposer=decomposer))
    with pytest.raises(StructuredGenerationError) as failure:
        PlanningEngine._plan_from_workspace_discovery(engine, observation=observation, task_plan=plan)
    error = failure.value
    assert error.code == ("PLANNER_FORMAL_INTENT_FAILED" if stage == "formal_intent"
        else "PLANNER_FORMAL_DECOMPOSITION_FAILED")
    assert error.metadata["stage"] == stage
    assert error.metadata["validationFailures"][0]["code"] == "string_type"
    assert error.metadata["validationFailures"][0]["fieldPath"] == ["tasks", 0, "objective"]
    assert error.audit == {"provider": "deepseek", "model": "deepseek-flash"}
    assert marker not in str(error) + json.dumps(error.metadata) + json.dumps(error.audit)


def test_formal_builder_checks_the_scope_contract_before_emitting_a_revision():
    from adapters.model.protocols import StructuredGenerationError
    from contracts.acg.semantic_profile import TaskSemanticProfile

    observation, plan = context(phase="discovery")
    # Deliberately bypass parser normalization at this mocked boundary. The
    # real builder must still reject an unrelated model scope before Commit.
    plan = plan.model_copy(update={"metadata": {"workspaceDiscovery": {
        "version": 1, "phase": "discovery", "scopeOrigin": "explicit"}},
        "nodes": tuple(node.model_copy(update={"constraints": [{"workspaceDiscovery": {
            "requestedObservations": [{"kind": "file", "path": "src/required.py", "operation": "read"}]}}]})
            if node.key == "read" else node for node in plan.nodes)})
    profile = TaskSemanticProfile(primaryGoal="Inspect sources", workspaceObservations=[{
        "kind": "file", "path": "src/unrelated.py", "operation": "read"}])
    engine = SimpleNamespace(workspace_context_provider=lambda _: {
        "sources": [{"sourceRef": "output:discovery", "findings": {}}], "observations": []},
        workspace_planning_input={}, workspace_planning_domain="general", workspace_planning_task_type="review",
        _planning_total_timeout_seconds=lambda: 60,
        intent_parser=SimpleNamespace(parse=lambda **_: profile),
        semantic_planner=SimpleNamespace(plan_profile=lambda **_: context()[1]))
    with pytest.raises(StructuredGenerationError) as failure:
        PlanningEngine._plan_from_workspace_discovery(engine, observation=observation, task_plan=plan)
    error = failure.value
    assert error.code == "PLANNER_FORMAL_DECOMPOSITION_FAILED"
    assert error.metadata["validationFailures"] == [{"stage": "formal_decomposition", "code": "value_error",
        "fieldPath": ["metadata", "workspaceScope"], "callKey": "decompose"}]


def test_formal_intent_and_decomposition_receive_the_same_rejected_candidate_and_frozen_goal():
    from copy import deepcopy
    from contracts.acg.semantic_profile import TaskSemanticProfile

    observation, plan = context(phase="discovery")
    feedback = {"observationId": "prior-observation", "code": "INVALID_PROPOSAL",
        "reason": "Candidate scope needs correction", "proposalRef": "graph-patch:rejected"}
    observation = observation.model_copy(update={"planning_commit_rejection": feedback})
    rejected = {"version": 1, "observationId": "prior-observation", "sourceGraphVersion": 2,
        "patch": {"missionId": plan.mission_id, "basePlanVersion": 1, "planVersion": 2,
            "metadata": {"workspaceScope": {"rationale": "previous useful proposal"}}},
        "rejection": {"code": feedback["code"], "reason": feedback["reason"]}}
    material = {"sources": [{"sourceRef": "output:discovery", "findings": {"supported": "evidence"}}],
        "observations": [], "rejectedProposal": rejected}
    loads, requests = [], []

    def load(current):
        loads.append(current)
        return material

    def parse(**kwargs):
        requests.append(deepcopy(kwargs["task_input"]))
        return TaskSemanticProfile(primaryGoal=kwargs["intent"], workspaceObservations=[{
            "kind": "file", "path": "src/main.py", "operation": "read"}])

    def decompose(**kwargs):
        requests.append(deepcopy(kwargs["task_input"]))
        return context()[1]

    engine = SimpleNamespace(workspace_context_provider=load,
        workspace_planning_input={"objective": "stale goal", "materialRefs": None},
        workspace_planning_domain="general", workspace_planning_task_type="review",
        _planning_total_timeout_seconds=lambda: 60,
        intent_parser=SimpleNamespace(parse=parse), semantic_planner=SimpleNamespace(plan_profile=decompose))
    PlanningEngine._plan_from_workspace_discovery(engine, observation=observation, task_plan=plan)
    assert loads == [observation] and len(requests) == 2 and requests[0] == requests[1]
    data = requests[0]
    assert data["objective"] == observation.goal
    supplied = data["sourceMaterials"]["workspaceDiscovery"]
    assert supplied["rejectedProposal"]["trustClass"] == "agent_generated"
    assert supplied["rejectedProposal"]["content"] == rejected
    assert supplied["planningContext"]["planningCommitRejection"] == feedback
    assert supplied["planningContext"]["completedTaskKeys"] == [node.key for node in plan.nodes]
    assert "correct the defective remaining work" in supplied["planningContext"]["purpose"]
    assert engine.workspace_planning_input == {"objective": "stale goal", "materialRefs": None}
