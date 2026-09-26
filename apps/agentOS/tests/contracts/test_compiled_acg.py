"""Canonical V4 Compiled ACG package contract and fail-closed version tests."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from components.executor.compiler import ACGGraphCompiler
from components.executor.graph import ACGExecutionState
from contracts.compiled_acg import (
    CompiledACGPackage,
    UnsupportedCompiledACGPackageVersion,
    load_compiled_acg_package,
)
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
)


def _resource_rich_blueprint() -> ACGBlueprint:
    return ACGBlueprint(
        graphId="resource-rich",
        nodes=[
            ControlNode(nodeId="start", controlType=ControlType.START),
            StepNode(nodeId="a", outputSpec={"properties": {"result": {}}}),
            StepNode(nodeId="b", inputSpec={"from": {"a": ["result"]}}),
            AgentNode(nodeId="agent", name="Agent", capabilityTags=["analysis"]),
            SkillNode(nodeId="skill", name="Skill", toolName="tool"),
            MemoryNode(nodeId="memory", name="Memory"),
            EvidenceNode(nodeId="evidence", name="Evidence", producerStepId="a"),
        ],
        edges=[
            ACGEdge(edgeId="start-a", sourceId="start", targetId="a"),
            ACGEdge(edgeId="a-b", sourceId="a", targetId="b"),
            ACGEdge(
                edgeId="a-b-communication", sourceId="a", targetId="b",
                edgeType=EdgeType.COMMUNICATION, dataFields=["result"],
            ),
            ACGEdge(edgeId="agent-a", sourceId="agent", targetId="a", edgeType=EdgeType.EXECUTION),
            ACGEdge(edgeId="agent-b", sourceId="agent", targetId="b", edgeType=EdgeType.EXECUTION),
            ACGEdge(edgeId="skill-a", sourceId="skill", targetId="a", edgeType=EdgeType.EXECUTION),
            ACGEdge(edgeId="memory-a", sourceId="memory", targetId="a", edgeType=EdgeType.READ),
            ACGEdge(edgeId="a-memory", sourceId="a", targetId="memory", edgeType=EdgeType.WRITE),
            ACGEdge(edgeId="evidence-b", sourceId="evidence", targetId="b", edgeType=EdgeType.SUPPORT),
        ],
    )


def _package() -> CompiledACGPackage:
    return ACGGraphCompiler().compile_package(_resource_rich_blueprint(), run_id="run-1")


def test_resource_graph_compiles_to_canonical_nodes_edges_and_manifests() -> None:
    blueprint = _resource_rich_blueprint()
    compiler = ACGGraphCompiler()
    package = compiler.compile_package(blueprint, run_id="run-1")
    package_payload = package.model_dump(by_alias=True, mode="json")

    node_ids = {node.node_id for node in package.nodes}
    assert {(node.node_id, node.kind.value) for node in package.nodes} == {
        ("start", "control"), ("a", "step"), ("b", "step"),
    }
    assert [(edge.source_id, edge.target_id, edge.edge_type) for edge in package.edges] == [
        ("start", "a", "dependency"), ("a", "b", "dependency"),
    ]
    assert all(edge.source_id in node_ids and edge.target_id in node_ids for edge in package.edges)
    assert "compatibilityWarnings" not in package_payload
    for manifest in (
        "bindingManifest", "skillManifest", "memoryManifest", "evidenceManifest",
    ):
        assert all(
            "compatibilitySource" not in rule
            for rule in package_payload[manifest]["rules"]
        )

    assert package.binding_manifest.for_step("a").agent_node_ids == ("agent",)
    assert package.skill_manifest.for_step("a")[0].skill_node_id == "skill"
    assert {(rule.memory_node_id, rule.access) for rule in package.memory_manifest.for_step("a")} == {
        ("memory", "read"), ("memory", "write"),
    }
    assert {(rule.step_id, rule.access) for rule in package.evidence_manifest.rules} == {
        ("a", "produce"), ("b", "consume"),
    }
    assert [(rule.producer_step_id, rule.consumer_step_id) for rule in package.communication_manifest.rules] == [
        ("a", "b"),
    ]

    graph = compiler.compile(blueprint, run_id="run-1", package=package)
    assert graph.nodes == ("start", "a", "b")
    assert graph.edges == (("start", "a"), ("a", "b"))
    assert package.control_manifest.entry_node_ids == ("start",)
    assert package.control_manifest.exit_node_ids == ("b",)
    assert graph.ready_steps(ACGExecutionState(
        runId="run-1", completedStepIds=("start",),
    )) == ("a",)
    assert graph.ready_steps(ACGExecutionState(
        runId="run-1", completedStepIds=("start", "a"),
    )) == ("b",)


@pytest.mark.parametrize("field", [
    "agentName", "agent_name", "assignedAgentId", "assigned_agent_id",
    "skillIds", "skill_ids", "memoryIds", "memory_ids", "evidenceIds", "evidence_ids",
])
def test_step_node_rejects_removed_inline_resource_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="legacy resource fields"):
        StepNode.model_validate({"nodeId": "step", field: "legacy"})


@pytest.mark.parametrize("field", ["skillIds", "skill_ids", "memoryIds", "memory_ids"])
def test_agent_node_rejects_removed_inline_resource_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="legacy resource fields"):
        AgentNode.model_validate({"nodeId": "agent", "name": "Agent", field: ["legacy"]})


@pytest.mark.parametrize("field", ["producerStepId", "producer_step_id"])
def test_evidence_metadata_cannot_supply_producer_identity(field: str) -> None:
    with pytest.raises(ValidationError, match="typed producerStepId"):
        EvidenceNode.model_validate({
            "nodeId": "evidence", "metadata": {field: "step"},
        })


@pytest.mark.parametrize("model,field", [
    (StepNode, "agentName"),
    (StepNode, "agent_name"),
    (StepNode, "assignedAgentId"),
    (StepNode, "assigned_agent_id"),
    (StepNode, "skillIds"),
    (StepNode, "skill_ids"),
    (StepNode, "memoryIds"),
    (StepNode, "memory_ids"),
    (StepNode, "evidenceIds"),
    (StepNode, "evidence_ids"),
    (AgentNode, "skillIds"),
    (AgentNode, "skill_ids"),
    (AgentNode, "memoryIds"),
    (AgentNode, "memory_ids"),
])
def test_removed_resource_fields_cannot_be_hidden_in_metadata(model, field: str) -> None:
    with pytest.raises(ValidationError, match="legacy resource fields"):
        model.model_validate({"nodeId": "node", "metadata": {field: "legacy"}})


def test_package_rejects_duplicate_identities_and_dangling_edges() -> None:
    payload = _package().model_dump(by_alias=True, mode="json")
    payload["nodes"].append(deepcopy(payload["nodes"][0]))
    with pytest.raises(ValidationError, match="duplicate nodeId"):
        CompiledACGPackage.model_validate(payload)

    payload = _package().model_dump(by_alias=True, mode="json")
    payload["edges"].append(deepcopy(payload["edges"][0]))
    with pytest.raises(ValidationError, match="duplicate edgeId"):
        CompiledACGPackage.model_validate(payload)

    payload = _package().model_dump(by_alias=True, mode="json")
    payload["edges"][0]["sourceId"] = "agent-x"
    with pytest.raises(ValidationError, match="unknown executable node"):
        CompiledACGPackage.model_validate(payload)


@pytest.mark.parametrize(("manifest_key", "rule"), [
    ("skillManifest", {"stepId": "missing", "skillNodeId": "skill"}),
    ("memoryManifest", {
        "stepId": "missing", "memoryNodeId": "memory", "access": "read",
        "memoryType": "working", "storageType": "inline", "retentionPolicy": "task",
    }),
    ("evidenceManifest", {
        "stepId": "missing", "evidenceNodeId": "evidence", "access": "consume",
        "evidenceType": "document", "source": "test",
    }),
    ("communicationManifest", {
        "producerStepId": "a", "consumerStepId": "missing", "channel": "a:missing",
    }),
])
def test_resource_manifests_reject_unknown_steps(manifest_key: str, rule: dict) -> None:
    payload = _package().model_dump(by_alias=True, mode="json")
    payload[manifest_key]["rules"].append(rule)

    with pytest.raises(ValidationError, match="unknown Step"):
        CompiledACGPackage.model_validate(payload)


def test_control_manifest_rejects_unknown_executable_reference() -> None:
    payload = _package().model_dump(by_alias=True, mode="json")
    payload["controlManifest"]["entryNodeIds"] = ["missing"]

    with pytest.raises(ValidationError, match="control entry references unknown"):
        CompiledACGPackage.model_validate(payload)


def test_canonical_package_serialization_round_trip_is_stable() -> None:
    payload = _package().model_dump(by_alias=True, mode="json")

    restored = CompiledACGPackage.model_validate(payload)

    assert restored.model_dump(by_alias=True, mode="json") == payload
    assert restored.package_version == 4


@pytest.mark.parametrize("version", [3, 99])
def test_loader_rejects_noncanonical_package_versions(version: int) -> None:
    payload = _package().model_dump(by_alias=True, mode="json")
    payload["packageVersion"] = version

    with pytest.raises(
        UnsupportedCompiledACGPackageVersion,
        match=rf"unsupported CompiledACGPackage version: {version}; canonical version is 4",
    ):
        load_compiled_acg_package(payload)
