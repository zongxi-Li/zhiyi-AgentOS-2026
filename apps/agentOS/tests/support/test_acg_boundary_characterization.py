"""Behavior snapshots that protect the ACG boundary extraction."""

from datetime import datetime, timezone

from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from support.acg.models import (
    ACGBlueprint,
    ACGEdge,
    AgentNode,
    ControlNode,
    ControlType,
    EdgeType,
    EvidenceNode,
    MemoryNode,
    SkillNode,
    StepNode,
    TaskSemanticProfile,
    build_default_capability_catalog,
    detect_cycle,
    promote_workflow_to_acg,
    ready_steps,
    topological_order,
    validate_blueprint,
)


def test_blueprint_serialization_contract_snapshot() -> None:
    timestamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    blueprint = ACGBlueprint(
        graphId="graph-1",
        missionId="mission-1",
        createdAt=timestamp,
        updatedAt=timestamp,
        nodes=[
            StepNode(
                nodeId="step-1", name="Execute", agentName="agent",
                assignedAgentId="agent-1", skillIds=["skill-1"],
                memoryIds=["memory-1"], evidenceIds=["evidence-1"],
            ),
            AgentNode(nodeId="agent-1", name="Agent"),
            SkillNode(nodeId="skill-1", name="Skill"),
            MemoryNode(nodeId="memory-1", name="Memory"),
            EvidenceNode(nodeId="evidence-1", name="Evidence"),
            ControlNode(nodeId="start", controlType=ControlType.START),
        ],
        edges=[
            ACGEdge(edgeId="edge-1", sourceId="start", targetId="step-1"),
            ACGEdge(
                edgeId="edge-2", sourceId="agent-1", targetId="step-1",
                edgeType=EdgeType.EXECUTION,
            ),
            ACGEdge(edgeId="edge-3", sourceId="step-1", targetId="memory-1", edgeType=EdgeType.WRITE),
            ACGEdge(edgeId="edge-4", sourceId="memory-1", targetId="step-1", edgeType=EdgeType.READ),
            ACGEdge(edgeId="edge-5", sourceId="evidence-1", targetId="step-1", edgeType=EdgeType.SUPPORT),
            ACGEdge(edgeId="edge-6", sourceId="step-1", targetId="skill-1", edgeType=EdgeType.COMMUNICATION),
            ACGEdge(edgeId="edge-7", sourceId="start", targetId="step-1", edgeType=EdgeType.CONTROL_FLOW),
        ],
        metadata={"source": "characterization"},
    )

    payload = blueprint.model_dump(by_alias=True, mode="json")

    assert payload["graphId"] == "graph-1"
    assert payload["createdAt"] == "2026-01-02T03:04:05Z"
    assert payload["updatedAt"] == "2026-01-02T03:04:05Z"
    assert [node["nodeType"] for node in payload["nodes"]] == [
        "step", "agent", "skill", "memory", "evidence", "control",
    ]
    assert payload["nodes"][0] == {
        "nodeId": "step-1", "nodeType": "step", "name": "Execute",
        "description": "", "metadata": {}, "stepType": "agent", "goal": "",
        "acceptanceCriteria": [], "sourceRefs": [], "logicalRole": "task",
        "inputSpec": {}, "outputSpec": {}, "assignedAgentId": "agent-1",
        "agentName": "agent", "capability": None, "skillIds": ["skill-1"],
        "memoryIds": ["memory-1"], "evidenceIds": ["evidence-1"],
        "timeout": 0, "retryLimit": 0, "priority": 0, "status": "draft",
        "reviewRequired": False, "stepId": "step-1", "stepName": "Execute",
    }
    assert [edge["edgeType"] for edge in payload["edges"]] == [
        "dependency", "execution", "write", "read", "support", "communication", "control_flow",
    ]
    assert {edge["activation"] for edge in payload["edges"]} == {"active"}
    assert payload["metadata"] == {"source": "characterization"}


def test_workflow_promotion_legacy_and_canonical_modes_snapshot() -> None:
    workflow = WorkflowDefinition(
        workflowId="workflow-1", name="Workflow", description="Objective", domain="general",
        runtimeEngine="acg",
        steps=[
            WorkflowStepDefinition(
                stepId="a", name="Analysis", agentName="analyst",
                capability="analysis", outputSpec={"properties": {"result": {}}},
            ),
            WorkflowStepDefinition(
                stepId="b", name="Report", agentName="writer",
                capability="report", input={"from": {"a": ["result"]}},
            ),
        ],
    )

    legacy = promote_workflow_to_acg(workflow, mission_id="mission-1")
    canonical = promote_workflow_to_acg(
        workflow, mission_id="mission-1", infer_dependencies=False,
    )

    assert [node.node_id for node in legacy.step_nodes()] == ["a", "b"]
    assert [(edge.source_id, edge.target_id) for edge in legacy.edges_of_type(
        EdgeType.DEPENDENCY
    )] == [("a", "b")]
    assert canonical.edges_of_type(EdgeType.DEPENDENCY) == []
    assert [(edge.source_id, edge.target_id) for edge in canonical.edges_of_type(
        EdgeType.COMMUNICATION
    )] == [("a", "b")]
    for blueprint in (legacy, canonical):
        assert blueprint.metadata == {
            "sourceWorkflowId": "workflow-1", "sourceWorkflowVersion": "1.0.0",
            "promotedFromLinear": True, "enriched": True, "runtimeEngine": "acg",
            "nodeCount": len(blueprint.nodes), "edgeCount": len(blueprint.edges),
        }


def test_capability_catalog_and_semantic_profile_snapshot() -> None:
    catalog = build_default_capability_catalog()
    available = catalog.available()

    assert tuple(item.capability_id for item in available) == tuple(
        item.capability_id for item in build_default_capability_catalog().available()
    )
    assert catalog.resolve("analysis").capability_id == "analysis"
    assert catalog.expand_dependencies(["artifact_generation"])[-1] == "artifact_generation"

    profile = TaskSemanticProfile(
        primaryGoal="Deliver", requiredCapabilities=["evidence_analysis"],
        estimatedComplexity="medium", domainHint="general", taskTypeHint="report",
    )
    assert profile.model_dump(by_alias=True, mode="json")["estimatedComplexity"] == "medium"
    assert profile.to_summary() == "[general/report] Deliver | caps=evidence_analysis"


def test_blueprint_graph_algorithm_snapshot() -> None:
    blueprint = ACGBlueprint(
        graphId="graph-1",
        nodes=[StepNode(nodeId="a", agentName="agent"), StepNode(nodeId="b", agentName="agent")],
        edges=[ACGEdge(edgeId="a-b", sourceId="a", targetId="b")],
    )

    validate_blueprint(blueprint)
    assert detect_cycle(blueprint) == []
    assert topological_order(blueprint) == ["a", "b"]
    assert ready_steps(blueprint, set()) == ["a"]
    assert ready_steps(blueprint, {"a"}) == ["b"]
