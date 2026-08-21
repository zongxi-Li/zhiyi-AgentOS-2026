"""Runtime graph revision and GraphPatch capability regression."""

from __future__ import annotations

import asyncio
import pytest

from components.executor import GraphPatchConflictError, InMemoryExecutionValueStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.task_manager.store import WorkflowRegistry
from contracts.planning import TaskNodeBindingPatch, TaskNodeImplementationBinding, TaskPlanNode, TaskPlanPatch
from contracts.recovery import GraphPatch
from contracts.workflow import (
    ReviewDecision,
    ReviewDecisionType,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStepDefinition,
)
from runtime import WorkflowRuntime
from runtime.v2 import AcgIdentityLifecycleService, WknIdentityLifecycleAdapter
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode
from support.stores.memory_workflow_store import MemoryWorkflowStore
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage


class _PatchAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(agentName="runner", domain="general"))
        self.calls: list[str] = []

    async def run(self, context):
        self.calls.append(context.step.step_id)
        return AgentOutput(output={"value": context.step.step_id})


class _BoundAgent(BaseAgent):
    def __init__(self, agent_id: str, name: str, calls: list[str], *, priority: int) -> None:
        super().__init__(
            AgentProfile(
                agentId=agent_id,
                agentName=name,
                domain="general",
                capabilities=["analysis"],
                bindingPriority=priority,
            )
        )
        self.calls = calls

    async def run(self, context):
        self.calls.append(self.profile.agent_id)
        return AgentOutput(output={"value": self.profile.agent_id})


def _runtime(tmp_path, *, with_identity: bool = False) -> tuple[WorkflowRuntime, _PatchAgent]:
    agents = AgentRegistry()
    agent = _PatchAgent()
    agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="patchable",
            name="patchable",
            domain="general",
            runtimeEngine="acg",
            steps=[
                WorkflowStepDefinition(
                    stepId="review",
                    name="review",
                    agentName="runner",
                    reviewRequired=True,
                    outputSpec={"type": "object", "properties": {"value": {"type": "string"}}},
                ),
                WorkflowStepDefinition(
                    stepId="deliver",
                    name="deliver",
                    agentName="runner",
                    outputSpec={"type": "object", "properties": {"value": {"type": "string"}}},
                ),
            ],
        )
    )
    identity_lifecycle = None
    if with_identity:
        identity_service = AcgIdentityLifecycleService(
            SQLiteV2Repositories(SQLiteV2Storage(":memory:"))
        )
        identity_lifecycle = WknIdentityLifecycleAdapter(
            identity_service,
            identity_service.repositories,
        )
    return (
        WorkflowRuntime(
            agent_registry=agents,
            workflow_registry=workflows,
            workflow_store=MemoryWorkflowStore(),
            checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
            execution_value_store=InMemoryExecutionValueStore(),
            identity_lifecycle=identity_lifecycle,
        ),
        agent,
    )


def test_runtime_graph_patch_carries_explicit_task_plan_binding(tmp_path):
    runtime, _agent = _runtime(tmp_path, with_identity=True)
    identity = runtime.identity_lifecycle.lifecycle_service
    try:
        task = runtime.create_task("identity patch", workflow_id="patchable")
        paused = asyncio.run(runtime.start(task.task_id, workflow_id="patchable"))
        original_domain_run = identity.repositories.runs.get(paused.run_id)
        original_blueprint = identity.repositories.blueprints.get(
            original_domain_run.blueprint_id
        )
        original_attempt_ids = {
            attempt.attempt_id
            for attempt in identity.repositories.attempts.list_for_run(paused.run_id)
        }
        blueprint = ACGBlueprint.model_validate(paused.acg_blueprint)
        original_edge = next(
            edge
            for edge in blueprint.edges
            if edge.edge_type is EdgeType.DEPENDENCY
            and edge.source_id == "review"
            and edge.target_id == "deliver"
        )
        patch = GraphPatch(
            patchId="patch-identity-enrich",
            idempotencyKey="patch-identity-enrich:v1",
            runId=paused.run_id,
            graphId=blueprint.graph_id,
            baseGraphVersion=blueprint.version,
            removeEdgeIds=[original_edge.edge_id],
            addNodes=[StepNode(
                nodeId="enrich",
                name="enrich",
                goal="enrich result",
                agentName="runner",
            ).model_dump(by_alias=True, mode="json")],
            addEdges=[
                ACGEdge(
                    edgeId="identity-review-to-enrich",
                    sourceId="review",
                    targetId="enrich",
                ).model_dump(by_alias=True, mode="json"),
                ACGEdge(
                    edgeId="identity-enrich-to-deliver",
                    sourceId="enrich",
                    targetId="deliver",
                ).model_dump(by_alias=True, mode="json"),
            ],
            taskPlanPatch=TaskPlanPatch(
                taskId=task.task_id,
                basePlanVersion=1,
                planVersion=2,
                addNodes=(TaskPlanNode(
                    key="step:enrich",
                    title="enrich",
                    objective="enrich result",
                ),),
            ),
            taskNodeBindingPatch=TaskNodeBindingPatch(bindings=(TaskNodeImplementationBinding(
                    planNodeKey="step:enrich",
                    acgNodeId="enrich",
                ),)),
            )

        applied = asyncio.run(runtime.apply_graph_patch(patch))
        old_domain_run = identity.repositories.runs.get(paused.run_id)
        domain_run = identity.repositories.runs.get(applied.run_id)
        bindings = identity.repositories.task_node_bindings.find_for_acg_node(
            "enrich",
            domain_run.blueprint_id,
        )

        assert applied.graph_version == 2
        assert old_domain_run.status.value == "superseded"
        assert domain_run.graph_version == 2
        assert applied.run_id != paused.run_id
        assert len(bindings) == 1
        assert bindings[0].task_node_id.startswith("node_")
        assert domain_run.metadata["parentRunId"] == paused.run_id
        assert domain_run.metadata["supersedesRunId"] == paused.run_id
        assert domain_run.metadata["sourcePatchId"] == patch.patch_id
        assert identity.repositories.blueprints.get(
            old_domain_run.blueprint_id
        ).graph == original_blueprint.graph
        assert {
            attempt.attempt_id
            for attempt in identity.repositories.attempts.list_for_run(paused.run_id)
        } == original_attempt_ids
    finally:
        identity.close()


def test_graph_patch_without_identity_lifecycle_is_rejected_without_mutation(tmp_path):
    runtime, _agent = _runtime(tmp_path)
    task = runtime.create_task("patch", workflow_id="patchable")
    paused = asyncio.run(runtime.start(task.task_id, workflow_id="patchable"))
    assert paused.status is WorkflowStatus.WAITING_REVIEW
    blueprint = ACGBlueprint.model_validate(paused.acg_blueprint)
    original_edge = next(
        edge
        for edge in blueprint.edges
        if edge.edge_type is EdgeType.DEPENDENCY
        and edge.source_id == "review"
        and edge.target_id == "deliver"
    )
    patch = GraphPatch(
        patchId="patch-add-enrich",
        idempotencyKey="patchable:enrich:v1",
        runId=paused.run_id,
        graphId=blueprint.graph_id,
        baseGraphVersion=blueprint.version,
        removeEdgeIds=[original_edge.edge_id],
        addNodes=[
            StepNode(
                nodeId="enrich",
                agentName="runner",
                outputSpec={"type": "object", "properties": {"value": {"type": "string"}}},
            ).model_dump(by_alias=True, mode="json")
        ],
        addEdges=[
            ACGEdge(edgeId="review-to-enrich", sourceId="review", targetId="enrich").model_dump(by_alias=True, mode="json"),
            ACGEdge(edgeId="enrich-to-deliver", sourceId="enrich", targetId="deliver").model_dump(by_alias=True, mode="json"),
        ],
        reason="insert deterministic enrichment before delivery",
    )
    old_checkpoint = paused.execution_state["checkpointId"]

    with pytest.raises(ValueError, match="identity lifecycle adapter"):
        asyncio.run(runtime.apply_graph_patch(patch))

    unchanged = runtime.get_status(paused.run_id)
    assert unchanged.status is WorkflowStatus.WAITING_REVIEW
    assert unchanged.execution_state["checkpointId"] == old_checkpoint
    assert unchanged.execution_state["graphVersion"] == blueprint.version
    assert unchanged.acg_blueprint == paused.acg_blueprint


def test_graph_patch_identity_transaction_rolls_back_replacement_run(tmp_path, monkeypatch):
    runtime, _agent = _runtime(tmp_path, with_identity=True)
    identity = runtime.identity_lifecycle.lifecycle_service
    try:
        task = runtime.create_task("identity rollback", workflow_id="patchable")
        paused = asyncio.run(runtime.start(task.task_id, workflow_id="patchable"))
        blueprint = ACGBlueprint.model_validate(paused.acg_blueprint)
        original_edge = next(
            edge for edge in blueprint.edges
            if edge.edge_type is EdgeType.DEPENDENCY
            and edge.source_id == "review"
            and edge.target_id == "deliver"
        )
        patch = GraphPatch(
            patchId="patch-identity-rollback",
            idempotencyKey="patch-identity-rollback:v1",
            runId=paused.run_id,
            graphId=blueprint.graph_id,
            baseGraphVersion=blueprint.version,
            removeEdgeIds=[original_edge.edge_id],
            addNodes=[StepNode(
                nodeId="enrich",
                name="enrich",
                goal="enrich result",
                agentName="runner",
            ).model_dump(by_alias=True, mode="json")],
            addEdges=[
                ACGEdge(
                    edgeId="rollback-review-to-enrich",
                    sourceId="review",
                    targetId="enrich",
                ).model_dump(by_alias=True, mode="json"),
                ACGEdge(
                    edgeId="rollback-enrich-to-deliver",
                    sourceId="enrich",
                    targetId="deliver",
                ).model_dump(by_alias=True, mode="json"),
            ],
            taskPlanPatch=TaskPlanPatch(
                taskId=task.task_id,
                basePlanVersion=1,
                planVersion=2,
                addNodes=(TaskPlanNode(
                    key="step:enrich",
                    title="enrich",
                    objective="enrich result",
                ),),
            ),
            taskNodeBindingPatch=TaskNodeBindingPatch(bindings=(
                TaskNodeImplementationBinding(
                    planNodeKey="step:enrich",
                    acgNodeId="enrich",
                ),
            )),
        )
        original_finish = identity.finish_run

        def fail_supersede(run_id, status):
            if status.value == "superseded":
                raise RuntimeError("simulated supersede failure")
            return original_finish(run_id, status)

        monkeypatch.setattr(identity, "finish_run", fail_supersede)
        with pytest.raises(RuntimeError, match="simulated supersede failure"):
            asyncio.run(runtime.apply_graph_patch(patch))

        runs = identity.repositories.runs.list_for_task(task.task_id)
        assert [run.run_id for run in runs] == [paused.run_id]
        assert runs[0].status.value != "superseded"
        assert len(identity.repositories.blueprints.list_for_task(task.task_id)) == 1
        assert len(identity.repositories.task_plans.list_for_task(task.task_id)) == 1
        assert {
            node.metadata["plannerSemanticKey"]
            for node in identity.repositories.task_nodes.list_for_task(task.task_id)
        } == {"step:review", "step:deliver"}
    finally:
        identity.close()


def test_graph_patch_rejects_stale_version(tmp_path):
    runtime, _ = _runtime(tmp_path)
    task = runtime.create_task("patch", workflow_id="patchable")
    paused = asyncio.run(runtime.start(task.task_id, workflow_id="patchable"))
    blueprint = ACGBlueprint.model_validate(paused.acg_blueprint)

    with pytest.raises(GraphPatchConflictError, match="version"):
        asyncio.run(
            runtime.apply_graph_patch(
                GraphPatch(
                    patchId="stale",
                    idempotencyKey="stale",
                    runId=paused.run_id,
                    graphId=blueprint.graph_id,
                    baseGraphVersion=blueprint.version + 1,
                    addNodes=[StepNode(nodeId="late", agentName="runner").model_dump(by_alias=True, mode="json")],
                )
            )
        )


def test_runtime_rebinds_pending_step_to_scoped_healthy_alternate(tmp_path):
    calls: list[str] = []
    agents = AgentRegistry()
    review_agent = _PatchAgent()
    primary = _BoundAgent("primary", "primary", calls, priority=10)
    alternate = _BoundAgent("alternate", "alternate", calls, priority=5)
    for agent in (review_agent, primary, alternate):
        agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="rebindable",
            name="rebindable",
            domain="general",
            runtimeEngine="acg",
            steps=[
                WorkflowStepDefinition(
                    stepId="review",
                    name="review",
                    agentName="runner",
                    reviewRequired=True,
                    nextStepId="deliver",
                ),
                WorkflowStepDefinition(
                    stepId="deliver", name="deliver", agentName="primary", capability="analysis"
                ),
            ],
        )
    )
    runtime = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "rebind-checkpoints.sqlite3"),
        execution_value_store=InMemoryExecutionValueStore(),
    )
    task = runtime.create_task("rebind", workflow_id="rebindable")
    paused = asyncio.run(runtime.start(task.task_id, workflow_id="rebindable"))
    assert paused.execution_state["resourceBindings"]["deliver"] == "primary"
    assert calls == []

    selected = asyncio.run(
        runtime.rebind_step(run_id=paused.run_id, step_id="deliver", reason="primary unavailable")
    )
    with pytest.raises(ValueError, match="budget exhausted"):
        asyncio.run(
            runtime.rebind_step(run_id=paused.run_id, step_id="deliver", reason="second switch")
        )
    completed = asyncio.run(
        runtime.apply_review(
            ReviewDecision(
                runId=paused.run_id,
                stepId="review",
                decision=ReviewDecisionType.APPROVED,
                operationId="approve-rebound-run",
            )
        )
    )

    assert selected == "alternate"
    assert calls == ["alternate"]
    assert completed.execution_state["bindingRequirements"]["deliver"]["preferences"] == {
        "resourceId": "alternate"
    }
    assert completed.execution_state["bindingHistory"][-1]["previousAgentId"] == "primary"
    assert any(
        event.event_type.value == "runtime_patch_applied"
        and event.payload.get("patchType") == "alternate_binding"
        for event in completed.trace
    )
