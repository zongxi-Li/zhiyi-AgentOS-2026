"""Behavior snapshots that protect the ACG boundary extraction."""

from datetime import datetime, timezone

import pytest

from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from support.acg.validation import ACGValidationError
from support.acg.models import (
    ACGBlueprint,
    ACGEdge,
    EdgeType,
    StepNode,
    TaskSemanticProfile,
    build_default_capability_catalog,
    detect_cycle,
    promote_workflow_to_acg,
    ready_steps,
    topological_order,
    validate_blueprint,
)
from support.acg.planning import ACGResourcePlan, AgentBindingSpec, CommunicationSpec, EvidenceSpec, MemoryAccessSpec


def test_blueprint_serialization_contract_snapshot() -> None:
    timestamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    blueprint = ACGBlueprint(
        graphId="graph-1",
        missionId="mission-1",
        createdAt=timestamp,
        updatedAt=timestamp,
        nodes=[
            StepNode(
                nodeId="step-1", name="Execute",
            ),
            StepNode(nodeId="step-2", name="Finish"),
        ],
        edges=[
            ACGEdge(edgeId="edge-1", sourceId="step-1", targetId="step-2"),
        ],
        resourcePlan=ACGResourcePlan(
            bindings=(
                AgentBindingSpec(stepId="step-1", plannedAgentId="Agent"),
                AgentBindingSpec(stepId="step-2", plannedAgentId="Agent"),
            ),
            memory=(MemoryAccessSpec(stepId="step-1", memoryId="memory-1", access="read"),),
            evidence=(EvidenceSpec(evidenceId="evidence-1", source="test"),),
            communication=(),
        ),
        metadata={"source": "characterization"},
    )

    payload = blueprint.model_dump(by_alias=True, mode="json")

    assert payload["graphId"] == "graph-1"
    assert payload["createdAt"] == "2026-01-02T03:04:05Z"
    assert payload["updatedAt"] == "2026-01-02T03:04:05Z"
    assert [node["nodeType"] for node in payload["nodes"]] == ["step", "step"]
    assert payload["nodes"][0] == {
        "nodeId": "step-1", "nodeType": "step", "name": "Execute",
        "description": "", "metadata": {}, "stepType": "agent", "goal": "",
        "acceptanceCriteria": [], "sourceRefs": [], "logicalRole": "task",
        "inputSpec": {}, "outputSpec": {}, "capability": None,
        "timeout": 0, "retryLimit": 0, "priority": 0, "status": "draft",
        "reviewRequired": False, "stepId": "step-1", "stepName": "Execute",
    }
    assert [edge["edgeType"] for edge in payload["edges"]] == ["dependency"]
    assert payload["resourcePlan"]["bindings"][0]["plannedAgentId"] == "Agent"
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
    assert [(spec.producer_step_id, spec.consumer_step_id)
            for spec in canonical.resource_plan.communication] == [("a", "b")]
    for blueprint in (legacy, canonical):
        assert len(blueprint.resource_plan.bindings) == len(blueprint.step_nodes())
        assert blueprint.metadata == {
            "sourceWorkflowId": "workflow-1", "sourceWorkflowVersion": "1.0.0",
            "promotedFromLinear": True, "enriched": True, "runtimeEngine": "acg",
            "nodeCount": len(blueprint.nodes), "edgeCount": len(blueprint.edges),
        }


def test_workflow_promotion_keeps_agent_bindings_when_cognitive_enrichment_is_disabled() -> None:
    workflow = WorkflowDefinition(
        workflowId="workflow-plain", name="Workflow", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(
            stepId="a", name="Analysis", agentName="analyst", capability="analysis",
        )],
    )

    blueprint = promote_workflow_to_acg(workflow, enrich=False)

    assert len(blueprint.resource_plan.bindings) == 1
    assert blueprint.resource_plan.bindings[0].planned_agent_id == "analyst"
    assert len(blueprint.nodes) == 1


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
        nodes=[
            StepNode(nodeId="a"), StepNode(nodeId="b"),
        ],
        edges=[
            ACGEdge(edgeId="a-b", sourceId="a", targetId="b"),
        ],
        resourcePlan=ACGResourcePlan(bindings=(
            AgentBindingSpec(stepId="a", plannedAgentId="agent"),
            AgentBindingSpec(stepId="b", plannedAgentId="agent"),
        )),
    )

    validate_blueprint(blueprint)
    assert detect_cycle(blueprint) == []
    assert topological_order(blueprint) == ["a", "b"]
    assert ready_steps(blueprint, set()) == ["a"]
    assert ready_steps(blueprint, {"a"}) == ["b"]


@pytest.mark.parametrize("agent_count", [0, 2])
def test_validator_requires_exactly_one_agent_binding_spec(agent_count: int) -> None:
    bindings = tuple(
        AgentBindingSpec(stepId="step", plannedAgentId=f"agent-{index}")
        for index in range(agent_count)
    )
    blueprint = ACGBlueprint(
        nodes=[StepNode(nodeId="step")],
        resourcePlan=ACGResourcePlan(bindings=bindings),
    )

    with pytest.raises(ACGValidationError, match="exactly one AgentBindingSpec"):
        validate_blueprint(blueprint)
