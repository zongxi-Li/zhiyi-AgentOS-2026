"""Real ExecutionRuntime coverage for structured memory events and phase capsules."""

from __future__ import annotations

import asyncio

from components.memory import MemoryService, PhaseCapsule
from components.memory.store import SQLiteMemoryStore
from components.mission_manager.store import WorkflowRegistry
from contracts.workflow import WorkflowDefinition, WorkflowDefinitionType, WorkflowStatus
from contracts.planning import TaskImplementationBinding, TaskPlan, TaskPlanRelation, PlannedTask
from runtime.workflow_runtime import ExecutionRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, EvidenceNode, StepNode
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _GoldenMemoryAgent(BaseAgent):
    def __init__(self, name: str) -> None:
        super().__init__(AgentProfile(agentName=name, domain="general", capabilities=["analysis"]))

    async def run(self, context):
        step_id = context.step.step_id
        evidence_ref = f"evidence:{step_id}"
        sources = [{"citationId": evidence_ref, "provider": "golden-memory-fixture"}]
        return AgentOutput(
            output={
                "summary": f"confirmed {step_id}",
                "evidence_refs": [evidence_ref],
                "body": f"PRIVATE-BODY-{step_id}",
            },
            summary=f"confirmed {step_id}",
            sources=sources,
            evidenceRefs=[evidence_ref],
        )


def _memory_policy() -> dict:
    return {
        "policyId": "golden-memory-v1",
        "read": True,
        "write": True,
        "readTypes": ["episodic", "semantic"],
        "writeType": "episodic",
        "limit": 10,
        "tokenBudget": 512,
        "requireAudit": True,
    }


def _node(step_id: str, stage: str, agent_name: str) -> StepNode:
    return StepNode(
        nodeId=step_id,
        name=step_id,
        agentName=agent_name,
        capability="analysis",
        outputSpec={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                "body": {"type": "string"},
            },
        },
        metadata={"planningStage": stage, "memoryPolicy": _memory_policy()},
    )


def _run(tmp_path):
    agents = AgentRegistry()
    agents.register(_GoldenMemoryAgent("golden-memory-a"))
    agents.register(_GoldenMemoryAgent("golden-memory-b"))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="golden-memory-runtime",
        name="golden memory runtime",
        domain="general",
        runtimeEngine="acg",
        definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP,
    ))
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
    )
    blueprint = ACGBlueprint(
        taskId="",
        objective="prove structured runtime memory",
        nodes=[
            _node("research-a", "research", "golden-memory-a"),
            _node("research-b", "research", "golden-memory-b"),
            _node("synthesize", "synthesize", "golden-memory-a"),
            EvidenceNode(
                nodeId="evidence-node:research-a",
                name="research-a evidence",
                evidenceType="test",
                source="golden-memory-fixture",
                producerStepId="research-a",
            ),
            EvidenceNode(
                nodeId="evidence-node:research-b",
                name="research-b evidence",
                evidenceType="test",
                source="golden-memory-fixture",
                producerStepId="research-b",
            ),
            EvidenceNode(
                nodeId="evidence-node:synthesize",
                name="synthesize evidence",
                evidenceType="test",
                source="golden-memory-fixture",
                producerStepId="synthesize",
            ),
        ],
        edges=[
            ACGEdge(sourceId="research-a", targetId="synthesize", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(sourceId="research-b", targetId="synthesize", edgeType=EdgeType.DEPENDENCY),
        ],
    )
    task = runtime.create_mission(
        "Golden memory integration",
        workflow_id="golden-memory-runtime",
        input={
            "acgBlueprint": blueprint.model_dump(by_alias=True, mode="json"),
            "constraints": ["reference-only persistence"],
            "openQuestions": ["human confirmation pending"],
        },
    )
    task_plan = TaskPlan(
        missionId=task.mission_id,
        nodes=tuple(PlannedTask(
            key=f"step:{step.node_id}",
            title=step.name or step.node_id,
            objective=step.goal or step.description or step.node_id,
            capabilityRequirements=((step.capability,) if step.capability else ()),
            metadata={"plannerStrategy": "test_explicit"},
        ) for step in blueprint.step_nodes()),
        relations=(
            TaskPlanRelation(sourceKey="step:research-a", targetKey="step:synthesize", relationType="depends_on"),
            TaskPlanRelation(sourceKey="step:research-b", targetKey="step:synthesize", relationType="depends_on"),
        ),
    )
    task.input.update({
        "taskPlan": task_plan.model_dump(by_alias=True, mode="json"),
        "taskBindings": [
            TaskImplementationBinding(
                planNodeKey=f"step:{step.node_id}", acgNodeId=step.node_id
            ).model_dump(by_alias=True, mode="json")
            for step in blueprint.step_nodes()
        ],
    })
    runtime.workflow_store.save_mission(task)
    _, prepared = runtime.prepare_run(task.mission_id, workflow_id="golden-memory-runtime")
    return runtime, asyncio.run(runtime.execute_prepared_run(prepared.run_id))


def test_runtime_memory_integration_builds_events_from_real_node_results(tmp_path) -> None:
    runtime, run = _run(tmp_path)

    assert run.status is WorkflowStatus.COMPLETED
    events = [
        event for event in run.trace
        if event.observation == "Structured memory event projected"
    ]
    assert len(events) == 3
    assert {event.payload["stepId"] for event in events} == {
        "research-a", "research-b", "synthesize"
    }
    records = [
        runtime.memory_store.get(f"memory:{run.run_id}:{step_id}")
        for step_id in ("research-a", "research-b", "synthesize")
    ]
    assert all(record is not None for record in records)
    assert all("PRIVATE-BODY" not in str(record.content) for record in records)
    assert all(set(record.content) == {
        "eventId", "runId", "stepId", "commitId", "summary",
        "evidenceRefs", "metrics", "decision", "relations",
    } for record in records)


def test_phase_capsule_runtime_uses_completed_stage_memory(tmp_path) -> None:
    runtime, run = _run(tmp_path)

    refs = run.execution_state["phaseCapsuleRefs"]
    assert set(refs) == {"research", "synthesize"}
    research = runtime.memory_store.get(refs["research"])
    assert research is not None
    capsule = PhaseCapsule.model_validate(research.content)
    assert capsule.goal == "Golden memory integration"
    assert capsule.confirmed_summary
    assert capsule.evidence_refs == ["evidence:research-a", "evidence:research-b"]
    assert capsule.constraints == ["reference-only persistence"]
    assert capsule.open_questions == ["human confirmation pending"]
    assert capsule.source_memory_refs == [
        f"memory:{run.run_id}:research-a",
        f"memory:{run.run_id}:research-b",
    ]
    capsule_events = [
        event for event in run.trace if event.payload.get("kind") == "phase_capsule"
    ]
    assert len(capsule_events) == 2
    scheduled = [
        set(event.payload.get("stepIds") or [])
        for event in run.trace if event.event_type.value == "step_scheduled"
    ]
    assert {"research-a", "research-b"} in scheduled
