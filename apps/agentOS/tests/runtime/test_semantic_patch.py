"""PR-8B semantic-first graph revision characterization."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from components.executor import GraphPatchConflictError, InMemoryExecutionValueStore
from components.mission_manager.store import WorkflowRegistry
from components.planner.topology import TopologyCompileError
from components.recovery.checkpoint import ACGCheckpointStore
from contracts.planning import (
    PlannedTask,
    TaskBindingPatch,
    TaskImplementationBinding,
    TaskPlanPatch,
    TaskPlanRelation,
    VerificationLoopPolicy,
)
from contracts.recovery import GraphPatch, SemanticPatchRequest
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from runtime import ExecutionRuntime
from runtime.semantic_patch import derive_graph_patch
from runtime.v2 import AcgIdentityLifecycleService, IdentityProjectionBridge
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage
from support.acg.models import ACGBlueprint, ACGResourcePlan, AgentBindingSpec, EdgeType
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _Agent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(agentName="runner", domain="general"))

    async def run(self, context):
        return AgentOutput(output={"value": context.step.step_id})


def _paused(tmp_path):
    agents = AgentRegistry()
    agents.register(_Agent())
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="seq",
        name="seq",
        domain="general",
        runtimeEngine="acg",
        planningNodes=(
            PlannedTask(key="step:A", title="A", objective="do A"),
            PlannedTask(key="step:B", title="B", objective="do B"),
        ),
        planningRelations=(
            TaskPlanRelation(
                sourceKey="step:A", targetKey="step:B", relationType="depends_on"
            ),
        ),
        steps=(
            WorkflowStepDefinition(
                stepId="A", name="A", agentName="runner", reviewRequired=True
            ),
            WorkflowStepDefinition(stepId="B", name="B", agentName="runner"),
        ),
    ))
    lifecycle = AcgIdentityLifecycleService(
        SQLiteV2Repositories(SQLiteV2Storage(":memory:"))
    )
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "cp.sqlite3"),
        execution_value_store=InMemoryExecutionValueStore(),
        identity_lifecycle=IdentityProjectionBridge(
            lifecycle, lifecycle.repositories
        ),
    )
    mission = runtime.create_mission("semantic patch", workflow_id="seq")
    run = asyncio.run(runtime.start(mission.mission_id, workflow_id="seq"))
    return runtime, lifecycle, mission, run


def _request(mission, run, blueprint, plan_patch, *, bindings=None, resources=None, patch_id="p1"):
    return SemanticPatchRequest(
        patchId=patch_id,
        idempotencyKey=f"{patch_id}:v1",
        runId=run.run_id,
        graphId=blueprint.graph_id,
        baseGraphVersion=blueprint.version,
        taskPlanPatch=plan_patch,
        taskNodeBindingPatch=(
            TaskBindingPatch(bindings=tuple(bindings)) if bindings else None
        ),
        resourcePlanPatch=resources,
    )


def test_add_task_is_lowered_from_task_plan_and_graph_patch_is_derived(tmp_path):
    runtime, lifecycle, mission, paused = _paused(tmp_path)
    try:
        old = ACGBlueprint.model_validate(paused.acg_blueprint)
        request = _request(
            mission,
            paused,
            old,
            TaskPlanPatch(
                missionId=mission.mission_id,
                basePlanVersion=1,
                planVersion=2,
                addNodes=(PlannedTask(key="step:C", title="C", objective="do C"),),
                removeRelations=(TaskPlanRelation(
                    sourceKey="step:A", targetKey="step:B", relationType="depends_on"
                ),),
                relations=(
                    TaskPlanRelation(
                        sourceKey="step:A", targetKey="step:C", relationType="depends_on"
                    ),
                    TaskPlanRelation(
                        sourceKey="step:C", targetKey="step:B", relationType="depends_on"
                    ),
                ),
            ),
            bindings=(TaskImplementationBinding(planNodeKey="step:C", acgNodeId="C"),),
            resources=ACGResourcePlan(bindings=(
                AgentBindingSpec(stepId="C", plannedAgentId="runner"),
            )),
        )
        result = asyncio.run(runtime.apply_semantic_patch(request))
        replacement = runtime.workflow_store.get_run(result.run_id)
        revised = ACGBlueprint.model_validate(replacement.acg_blueprint)
        dependencies = {
            (edge.source_id, edge.target_id)
            for edge in revised.edges_of_type(EdgeType.DEPENDENCY)
        }
        assert dependencies == {("A", "C"), ("C", "B")}
        assert replacement.execution_state["resourceBindings"] == {}
        stored = runtime.execution_value_store.get_graph_patch(
            run_id=result.run_id, patch_ref=result.patch_ref.uri
        )
        assert stored["addedNodes"][0]["nodeId"] == "C"
        assert "taskPlanPatch" not in stored
    finally:
        lifecycle.close()


def test_dependency_removal_changes_task_plan_and_lowered_graph(tmp_path):
    runtime, lifecycle, mission, paused = _paused(tmp_path)
    try:
        old = ACGBlueprint.model_validate(paused.acg_blueprint)
        relation = TaskPlanRelation(
            sourceKey="step:A", targetKey="step:B", relationType="depends_on"
        )
        request = _request(
            mission,
            paused,
            old,
            TaskPlanPatch(
                missionId=mission.mission_id,
                basePlanVersion=1,
                planVersion=2,
                removeRelations=(relation,),
            ),
            patch_id="remove-dependency",
        )
        result = asyncio.run(runtime.apply_semantic_patch(request))
        replacement = runtime.workflow_store.get_run(result.run_id)
        assert replacement.execution_state["taskPlan"]["relations"] == []
        assert ACGBlueprint.model_validate(replacement.acg_blueprint).edges == []
    finally:
        lifecycle.close()


def test_revised_task_plan_and_acg_have_identical_semantic_reachability(tmp_path):
    from components.planner.acg_semantic_validator import (
        semantic_reachability_projection,
    )
    from contracts.planning import TaskPlan

    runtime, lifecycle, mission, paused = _paused(tmp_path)
    try:
        old = ACGBlueprint.model_validate(paused.acg_blueprint)
        relation = TaskPlanRelation(
            sourceKey="step:A", targetKey="step:B", relationType="depends_on"
        )
        request = _request(
            mission,
            paused,
            old,
            TaskPlanPatch(
                missionId=mission.mission_id,
                basePlanVersion=1,
                planVersion=2,
                removeRelations=(relation,),
            ),
            patch_id="authority-guard",
        )
        result = asyncio.run(runtime.apply_semantic_patch(request))
        replacement = runtime.workflow_store.get_run(result.run_id)
        revised = ACGBlueprint.model_validate(replacement.acg_blueprint)
        bindings = tuple(
            TaskImplementationBinding.model_validate(item)
            for item in replacement.execution_state["taskBindings"]
        )
        plan = TaskPlan.model_validate(replacement.execution_state["taskPlan"])
        assert {task.key for task in plan.nodes} == {"step:A", "step:B"}
        assert semantic_reachability_projection(revised, bindings) == frozenset()
    finally:
        lifecycle.close()


def test_cycle_is_rejected_by_topology_compiler_before_transition(tmp_path):
    runtime, lifecycle, mission, paused = _paused(tmp_path)
    try:
        old = ACGBlueprint.model_validate(paused.acg_blueprint)
        request = _request(
            mission,
            paused,
            old,
            TaskPlanPatch(
                missionId=mission.mission_id,
                basePlanVersion=1,
                planVersion=2,
                relations=(TaskPlanRelation(
                    sourceKey="step:B", targetKey="step:A", relationType="depends_on"
                ),),
            ),
            patch_id="cycle",
        )
        with pytest.raises(TopologyCompileError):
            asyncio.run(runtime.apply_semantic_patch(request))
        assert runtime.workflow_store.get_run(paused.run_id).status == paused.status
    finally:
        lifecycle.close()


def test_capability_change_requires_replacement_planning_decisions(tmp_path):
    runtime, lifecycle, mission, paused = _paused(tmp_path)
    try:
        old = ACGBlueprint.model_validate(paused.acg_blueprint)
        plan_patch = TaskPlanPatch(
            missionId=mission.mission_id,
            basePlanVersion=1,
            planVersion=2,
            replaceKeys=("step:B",),
            addNodes=(PlannedTask(
                key="step:B",
                title="B2",
                objective="analyse B",
                capabilityRequirements=("task_understanding",),
            ),),
        )
        incomplete = _request(mission, paused, old, plan_patch, patch_id="cap-missing")
        with pytest.raises(ValueError, match="TaskBindingPatch"):
            asyncio.run(runtime.apply_semantic_patch(incomplete))

        complete = _request(
            mission,
            paused,
            old,
            plan_patch,
            bindings=(TaskImplementationBinding(planNodeKey="step:B", acgNodeId="B2"),),
            resources=ACGResourcePlan(bindings=(AgentBindingSpec(
                stepId="B2",
                plannedAgentId="runner",
                requiredCapabilities=("task_understanding",),
            ),)),
            patch_id="cap-complete",
        )
        result = asyncio.run(runtime.apply_semantic_patch(complete))
        revised = ACGBlueprint.model_validate(
            runtime.workflow_store.get_run(result.run_id).acg_blueprint
        )
        assert next(node for node in revised.step_nodes() if node.node_id == "B2").capability == "task_understanding"
        assert not revised.has_node("B")
    finally:
        lifecycle.close()


def test_explicit_control_change_is_lowered_from_task_plan_policy(tmp_path):
    runtime, lifecycle, mission, paused = _paused(tmp_path)
    try:
        old = ACGBlueprint.model_validate(paused.acg_blueprint)
        request = _request(
            mission,
            paused,
            old,
            TaskPlanPatch(
                missionId=mission.mission_id,
                basePlanVersion=1,
                planVersion=2,
                controlPolicies=(VerificationLoopPolicy(
                    bodyEntryKey="step:A",
                    bodyExitKey="step:B",
                    conditionSourceKey="step:B",
                ),),
            ),
            patch_id="control",
        )
        result = asyncio.run(runtime.apply_semantic_patch(request))
        revised = ACGBlueprint.model_validate(
            runtime.workflow_store.get_run(result.run_id).acg_blueprint
        )
        assert [node.node_id for node in revised.nodes if node.node_type.value == "control"] == [
            "ctrl_verification_loop_1"
        ]
    finally:
        lifecycle.close()


def test_derived_graph_patch_is_deterministic():
    old = ACGBlueprint(missionId="m", graphId="g", objective="old", version=1)
    new = old.model_copy(deep=True)
    new.version = 2
    first = derive_graph_patch(old, new, patch_id="derived")
    second = derive_graph_patch(old, new, patch_id="derived")
    assert first == second
    assert first.checksum() == second.checksum()


def test_legacy_arbitrary_graph_patch_payload_is_rejected():
    with pytest.raises(ValidationError):
        GraphPatch.model_validate({
            "patchId": "legacy",
            "idempotencyKey": "legacy:v1",
            "runId": "run",
            "graphId": "graph",
            "baseGraphVersion": 1,
            "addNodes": [{"nodeId": "C", "nodeType": "step"}],
        })


def test_stale_semantic_patch_is_rejected(tmp_path):
    runtime, lifecycle, mission, paused = _paused(tmp_path)
    try:
        old = ACGBlueprint.model_validate(paused.acg_blueprint)
        request = SemanticPatchRequest(
            patchId="stale",
            idempotencyKey="stale:v1",
            runId=paused.run_id,
            graphId=old.graph_id,
            baseGraphVersion=old.version + 1,
            taskPlanPatch=TaskPlanPatch(
                missionId=mission.mission_id,
                basePlanVersion=1,
                planVersion=2,
                removeRelations=(TaskPlanRelation(
                    sourceKey="step:A", targetKey="step:B", relationType="depends_on"
                ),),
            ),
        )
        with pytest.raises(GraphPatchConflictError, match="version"):
            asyncio.run(runtime.apply_semantic_patch(request))
    finally:
        lifecycle.close()
