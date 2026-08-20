"""Runtime graph revision and GraphPatch capability regression."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from components.executor import GraphPatchConflictError, InMemoryExecutionValueStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.task_manager.store import WorkflowRegistry
from contracts.recovery import GraphPatch
from contracts.workflow import (
    ReviewDecision,
    ReviewDecisionType,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStepDefinition,
)
from runtime import WorkflowRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode
from support.stores.memory_workflow_store import MemoryWorkflowStore


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


def _runtime(tmp_path) -> tuple[WorkflowRuntime, _PatchAgent]:
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
    return (
        WorkflowRuntime(
            agent_registry=agents,
            workflow_registry=workflows,
            workflow_store=MemoryWorkflowStore(),
            checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
            execution_value_store=InMemoryExecutionValueStore(),
        ),
        agent,
    )


def test_runtime_applies_versioned_patch_at_review_barrier_and_executes_new_node(tmp_path):
    runtime, agent = _runtime(tmp_path)
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

    applied = asyncio.run(runtime.apply_graph_patch(patch))
    patched = runtime.get_status(paused.run_id)

    assert applied.applied is True
    assert applied.graph_version == 2
    assert patched.execution_state["graphVersion"] == 2
    assert patched.execution_state["checkpointId"] != old_checkpoint
    assert patched.execution_state["graphPatchRefs"] == [applied.patch_ref.uri]
    assert runtime.execution_value_store.get_graph_patch(
        run_id=patched.run_id,
        patch_ref=applied.patch_ref.uri,
    )["patchId"] == patch.patch_id
    assert "addNodes" not in patched.execution_state

    replay = asyncio.run(runtime.apply_graph_patch(patch))
    assert replay.applied is False
    assert replay.idempotent_replay is True
    assert replay.patch_ref.uri == applied.patch_ref.uri

    completed = asyncio.run(
        runtime.apply_review(
            ReviewDecision(
                runId=paused.run_id,
                stepId="review",
                decision=ReviewDecisionType.APPROVED,
                operationId="approve-patched-run",
            )
        )
    )
    assert completed.status is WorkflowStatus.COMPLETED
    assert agent.calls == ["review", "enrich", "deliver"]
    assert completed.completed_step_ids == ["review", "enrich", "deliver"]

    runtime.clean_execution_orphans(
        run_id=completed.run_id,
        older_than=datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    assert runtime.execution_value_store.get_graph_patch(
        run_id=completed.run_id,
        patch_ref=applied.patch_ref.uri,
    )["patchId"] == patch.patch_id


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
