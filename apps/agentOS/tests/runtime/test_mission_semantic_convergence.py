"""Real Runtime integration using the existing temporary SQLite ACG harness."""

import asyncio
from types import SimpleNamespace

import pytest

from test_planning_loop import runtime_at, Agent, Planner, attach
from components.mission_manager.semantic_service import MissionSemanticService
from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal, run_intent_basis
from contracts.workflow import WorkflowStatus
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from contracts.planning import PlannedTask, TaskPlanPatch, TaskPlanRelation
from contracts.recovery import SemanticPatchRequest
from support.acg.models import ACGBlueprint
from runtime.semantic_revision import SemanticRevisionService
from runtime.planner_input_adapter import planner_input
from service.agents.base import AgentRunContext
from adapters.agent_architecture import FrameworkAgent
from adapters.resource_execution import build_remote_execution_payload
from adapters.model.native_prompt import NativeCapabilityPromptBuilder
from support.acg.models import build_default_capability_catalog


OWNER = SemanticPrincipal(actorId="owner", tenantId="tenant")


def enable(runtime, *, allow_legacy=False):
    runtime.workflow_store._init_semantic_schema()  # This harness owns a temporary DB.
    runtime.workflow_store.enable_existing_mission_semantics()
    runtime.mission_semantic_service = MissionSemanticService(store=runtime.workflow_store,
        authorize=lambda principal, mission, action: principal == OWNER)
    runtime.semantic_principal_provider = lambda: OWNER
    runtime.allow_legacy_mission_intent = allow_legacy


def commit(runtime, mission_id, *, operation="first", revision=0, objective="formal payment risk analysis"):
    return runtime.mission_semantic_service.commit(OWNER, MissionSemanticRequest(
        missionId=mission_id, operationId=operation, expectedMissionRevision=revision,
        objective=objective, constraints=[], sourceRefs=["unverified-reference"]))


class RecordingAgent(Agent):
    def __init__(self):
        super().__init__()
        self.bases = []
        self.task_views = []

    async def run(self, context):
        self.bases.append(context.mission_intent_basis)
        self.task_views.append((context.task.title, context.task.input.get("userIntent")))
        return await super().run(context)


def test_deferred_restart_new_revision_and_execution_use_frozen_basis(tmp_path):
    runtime, _ = runtime_at(tmp_path)
    enable(runtime)
    mission = runtime.create_mission("legacy contract review", workflow_id="seq",
        input={"userIntent": "legacy contract review", "constraints": ["old"], "materialText": "source document"})
    commit(runtime, mission.mission_id)
    _, run = runtime.prepare_run(mission.mission_id, defer_acg_planning=True,
        idempotency_key="request", idempotency_fingerprint="request-fingerprint")
    basis = run_intent_basis(run)
    assert basis.source_revision == 1 and run.execution_state["planningDeferred"]
    commit(runtime, mission.mission_id, operation="second", revision=1, objective="later objective")
    _, replay = runtime.prepare_run(mission.mission_id, defer_acg_planning=True,
        idempotency_key="request", idempotency_fingerprint="request-fingerprint")
    assert replay.run_id == run.run_id and run_intent_basis(replay) == basis
    recovered, agent = runtime_at(tmp_path, RecordingAgent())
    enable(recovered)
    real_planner = recovered._planning_engine_for_run(run)
    planner_calls = []
    class RecordingPlanner:
        def plan(self, **kwargs):
            planner_calls.append(kwargs)
            return real_planner.plan(**kwargs)
    recovered._planning_engine_for_run = lambda run: RecordingPlanner()
    observer = Planner()
    attach(recovered, observer)
    result = asyncio.run(recovered.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.COMPLETED
    assert planner_calls[0]["intent"] == basis.objective
    assert planner_calls[0]["task_input"]["constraints"] == []
    assert planner_calls[0]["task_input"]["materialText"] == "source document"
    assert result.execution_state["taskPlan"]["metadata"]["missionIntentBasisRef"] == basis.reference()
    assert agent.bases and all(b == basis for b in agent.bases)
    assert all(title == intent == basis.objective for title, intent in agent.task_views)
    assert observer.observations[-1].goal == basis.objective
    assert observer.observations[-1].mission_intent_basis_ref == basis.reference()
    assert recovered.workflow_store.get_semantic_snapshot(mission.mission_id).mission_revision == 2
    _, later = recovered.prepare_run(mission.mission_id, defer_acg_planning=True)
    assert run_intent_basis(later).objective == "later objective"
    assert run_intent_basis(recovered.workflow_store.get_run(run.run_id)) == basis


def test_uninitialized_requires_explicit_compatibility_and_permissions_rechecked(tmp_path):
    runtime, _ = runtime_at(tmp_path)
    enable(runtime)
    mission = runtime.create_mission("legacy", workflow_id="seq", input={"userIntent": "legacy input"})
    with pytest.raises(ValueError, match="uninitialized"):
        runtime.prepare_run(mission.mission_id, defer_acg_planning=True)
    runtime.allow_legacy_mission_intent = True
    _, run = runtime.prepare_run(mission.mission_id, defer_acg_planning=True,
        idempotency_key="request", idempotency_fingerprint="f")
    assert run_intent_basis(run).source_type == "LEGACY_INPUT"
    assert run_intent_basis(run).source_revision == 0
    assert runtime.workflow_store.get_semantic_snapshot(mission.mission_id).state is None
    runtime.mission_semantic_service.authorize = lambda *_: False
    with pytest.raises(PermissionError):
        runtime.prepare_run(mission.mission_id, idempotency_key="request", idempotency_fingerprint="f")
    runtime.semantic_principal_provider = None
    with pytest.raises(PermissionError, match="trusted"):
        runtime.prepare_run(mission.mission_id)


def test_semantic_explicit_plan_cannot_self_certify_and_successor_inherits(tmp_path):
    runtime, _ = runtime_at(tmp_path)
    enable(runtime)
    mission = runtime.create_mission("legacy", workflow_id="seq")
    commit(runtime, mission.mission_id)
    _, original = runtime.prepare_run(mission.mission_id)
    basis = run_intent_basis(original)
    package = {"acgBlueprint": original.acg_blueprint, "taskPlan": original.execution_state["taskPlan"],
               "taskBindings": original.execution_state["taskBindings"]}
    with pytest.raises(ValueError, match="trusted parent"):
        runtime.prepare_run(mission.mission_id, input_override=package)
    commit(runtime, mission.mission_id, operation="second", revision=1, objective="later objective")
    _, successor = runtime.prepare_run(mission.mission_id, parent_run_id=original.run_id,
        inherit_parent_basis=True, input_override=package)
    assert run_intent_basis(successor) == basis
    assert successor.execution_state["taskPlan"]["metadata"]["missionIntentBasisRef"] == basis.reference()
    assert SemanticRevisionService._fresh_replacement_execution_state(original)["missionIntentBasis"] == original.execution_state["missionIntentBasis"]
    forged = {**package, "taskPlan": {**package["taskPlan"], "metadata": {}}}
    with pytest.raises(ValueError, match="trusted parent"):
        runtime.prepare_run(mission.mission_id, parent_run_id=original.run_id,
            inherit_parent_basis=True, input_override=forged)


def test_node_adapters_separate_mission_step_and_raw_material(tmp_path):
    runtime, _ = runtime_at(tmp_path)
    enable(runtime)
    mission = runtime.create_mission("legacy", workflow_id="seq",
        input={"userIntent": "wrong legacy goal", "materialText": "raw document"})
    commit(runtime, mission.mission_id)
    _, run = runtime.prepare_run(mission.mission_id)
    basis = run_intent_basis(run)
    step = run.steps[0]
    context = AgentRunContext(task=mission, run=run, workflow=runtime._workflow_for_run(run), step=step,
        memory=[], contextPack=SimpleNamespace(data={}, evidence_refs=[]))
    assert context.mission_intent_basis == basis
    external = FrameworkAgent._input_for(context)
    assert external["mission"]["objective"] == basis.objective
    assert external["materials"]["materialText"] == "raw document"
    assert "userIntent" not in external["materials"]
    assert external["step"]["goal"] == step.goal
    remote = build_remote_execution_payload(context)
    assert remote["missionIntentBasis"]["fingerprint"] == basis.fingerprint
    assert remote["goal"] == step.goal
    descriptor = build_default_capability_catalog().get("cost_analysis")
    envelope = NativeCapabilityPromptBuilder().build_envelope(capability_descriptor=descriptor,
        step_goal="calculate local cost", acceptance_criteria=[], source_refs=[], logical_role="analysis",
        task_title=mission.title, task_input=mission.input, context_data={}, source_data={}, evidence_refs=[],
        output_schema=descriptor.output_contract, mission_intent_basis=basis)
    assert basis.objective in envelope.user_prompt and "calculate local cost" in envelope.user_prompt
    assert "wrong legacy goal" not in envelope.user_prompt
    assert "raw document" in envelope.user_prompt


def test_actual_semantic_graph_revision_preserves_basis_and_plan_reference(tmp_path):
    workflow = WorkflowDefinition(workflowId="seq", name="seq", domain="general", runtimeEngine="acg",
        planningNodes=(PlannedTask(key="step:A", title="A", objective="do A"),
                       PlannedTask(key="step:B", title="B", objective="do B")),
        planningRelations=(TaskPlanRelation(sourceKey="step:A", targetKey="step:B", relationType="depends_on"),),
        steps=(WorkflowStepDefinition(stepId="A", name="A", agentName="runner", reviewRequired=True),
               WorkflowStepDefinition(stepId="B", name="B", agentName="runner")))
    runtime, _ = runtime_at(tmp_path, workflow=workflow)
    enable(runtime)
    mission = runtime.create_mission("legacy", workflow_id="seq")
    commit(runtime, mission.mission_id)
    _, run = runtime.prepare_run(mission.mission_id)
    basis = run_intent_basis(run)
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW
    commit(runtime, mission.mission_id, operation="later", revision=1, objective="new current mission")
    blueprint = ACGBlueprint.model_validate(paused.acg_blueprint)
    version = paused.execution_state["taskPlanVersion"]
    patch = TaskPlanPatch(missionId=mission.mission_id, basePlanVersion=version, planVersion=version+1,
        addNodes=(PlannedTask(key="step:C", title="C", objective="do C", capabilityRequirements=("task_understanding",)),),
        removeRelations=(TaskPlanRelation(sourceKey="step:A", targetKey="step:B", relationType="depends_on"),),
        relations=(TaskPlanRelation(sourceKey="step:A", targetKey="step:C", relationType="depends_on"),
                   TaskPlanRelation(sourceKey="step:C", targetKey="step:B", relationType="depends_on")))
    result = asyncio.run(runtime.apply_semantic_patch(SemanticPatchRequest(patchId="patch", idempotencyKey="patch:1",
        runId=run.run_id, graphId=blueprint.graph_id, baseGraphVersion=blueprint.version, taskPlanPatch=patch)))
    replacement = runtime.workflow_store.get_run(result.run_id)
    assert run_intent_basis(replacement) == basis
    assert replacement.execution_state["taskPlan"]["metadata"]["missionIntentBasisRef"] == basis.reference()
    assert runtime.workflow_store.get_semantic_snapshot(mission.mission_id).mission_revision == 2


def test_runtime_idempotency_key_cannot_cross_mission_scope(tmp_path):
    runtime, _ = runtime_at(tmp_path)
    enable(runtime, allow_legacy=True)
    first = runtime.create_mission("one", workflow_id="seq")
    second = runtime.create_mission("two", workflow_id="seq")
    runtime.prepare_run(first.mission_id, defer_acg_planning=True, idempotency_key="key", idempotency_fingerprint="f")
    with pytest.raises(ValueError, match="another Mission"):
        runtime.prepare_run(second.mission_id, defer_acg_planning=True, idempotency_key="key", idempotency_fingerprint="f")
