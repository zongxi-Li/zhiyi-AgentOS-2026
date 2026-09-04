"""规划器生成步骤记忆策略的测试。"""

from __future__ import annotations

from components.planner.acg_builder import ACGBuilder
from components.planner.semantic_planner import SemanticPlanner
from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
from components.executor.compiler import ACGGraphCompiler
from support.acg.models import (
    CapabilityCatalog,
    PlanningCapabilityDescriptor,
    TaskSemanticProfile,
)


def test_builder_derives_memory_write_policy_from_capability() -> None:
    """能力目录的 writesMemory 必须转换成可冻结、可执行的步骤策略。"""
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(
            capabilityId="analyze",
            displayName="分析",
            writesMemory=False,
            domainHints=["general"],
        ),
        PlanningCapabilityDescriptor(
            capabilityId="conclude",
            displayName="结论",
            writesMemory=True,
            domainHints=["general"],
        ),
    ])
    network = CollaborationNetwork(bindings=[
        CapabilityBinding(capability="analyze", agent_name="agent", score=1.0),
        CapabilityBinding(capability="conclude", agent_name="agent", score=1.0),
    ])

    mission_id = "mission_0123456789ab"
    task_plan = SemanticPlanner(catalog).plan_capabilities(
        mission_id=mission_id,
        capabilities=["analyze", "conclude"],
        strategy="test",
    )
    blueprint = ACGBuilder(catalog).build(
        mission_id=mission_id,
        profile=TaskSemanticProfile(
            primaryGoal="test",
            requiredCapabilities=["analyze", "conclude"],
        ),
        network=network,
        task_plan=task_plan,
    )

    policies = {
        node.capability: node.metadata["memoryPolicy"]
        for node in blueprint.step_nodes()
    }
    assert policies["analyze"] == {
        "policyId": "capability:analyze:v1",
        "read": True,
        "readTypes": ["episodic"],
        "write": False,
        "writeType": None,
        "limit": 10,
        "tokenBudget": None,
        "requireAudit": False,
    }
    assert policies["conclude"]["write"] is True
    assert policies["conclude"]["requireAudit"] is True


def test_builder_compiles_evidence_producer_and_consumer_permissions() -> None:
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(
            capabilityId="retrieve",
            displayName="Retrieve",
            requiresEvidence=True,
            domainHints=["general"],
        ),
        PlanningCapabilityDescriptor(
            capabilityId="analyze",
            displayName="Analyze",
            dependsOn=["retrieve"],
            requiresEvidence=True,
            domainHints=["general"],
        ),
    ])
    network = CollaborationNetwork(bindings=[
        CapabilityBinding(capability="retrieve", agent_name="agent", score=1.0),
        CapabilityBinding(capability="analyze", agent_name="agent", score=1.0),
    ])
    mission_id = "mission_0123456789ab"
    task_plan = SemanticPlanner(catalog).plan_capabilities(
        mission_id=mission_id,
        capabilities=["retrieve", "analyze"],
        strategy="test",
    )
    blueprint = ACGBuilder(catalog).build(
        mission_id=mission_id,
        profile=TaskSemanticProfile(
            primaryGoal="test",
            requiredCapabilities=["retrieve", "analyze"],
        ),
        network=network,
        task_plan=task_plan,
    )

    package = ACGGraphCompiler().compile_package(blueprint)
    retrieve_step = next(node for node in blueprint.step_nodes() if node.capability == "retrieve")
    analyze_step = next(node for node in blueprint.step_nodes() if node.capability == "analyze")
    evidence_node_id = f"evidence::{retrieve_step.node_id}"

    assert retrieve_step.evidence_ids == []
    assert any(
        rule.step_id == retrieve_step.node_id
        and rule.evidence_node_id == evidence_node_id
        and rule.access == "produce"
        for rule in package.evidence_manifest.rules
    )
    assert any(
        rule.step_id == analyze_step.node_id
        and rule.evidence_node_id == evidence_node_id
        and rule.access == "consume"
        for rule in package.evidence_manifest.rules
    )
