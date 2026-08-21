"""规划器生成步骤记忆策略的测试。"""

from __future__ import annotations

from components.planner.acg_builder import ACGBuilder
from components.planner.semantic_planner import SemanticPlanner
from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
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

    task_id = "task_0123456789ab"
    task_plan = SemanticPlanner(catalog).plan_capabilities(
        task_id=task_id,
        capabilities=["analyze", "conclude"],
        strategy="test",
    )
    blueprint = ACGBuilder(catalog).build(
        task_id=task_id,
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
