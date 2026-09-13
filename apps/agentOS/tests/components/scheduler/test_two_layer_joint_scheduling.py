from __future__ import annotations

from datetime import datetime, timezone

from components.resource.agent_service import AgentService
from components.resource.node_service import NodeService
from components.scheduler.two_layer_service import TwoLayerSchedulerService
from components.scheduler.leases import InMemoryLeaseCoordinator
from contracts.resource import BindingRequirement
from contracts.resource import (
    AgentProfile,
    AgentSnapshot,
    DeploymentTier,
    NodeProfile,
    NodeSnapshot,
)


NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def _node(
    nodes: NodeService,
    node_id: str,
    *,
    model_ids: list[str],
    gpu_memory_mb: int,
    privacy_level: str = "internal",
    queued_tasks: int = 0,
) -> None:
    nodes.register(
        NodeProfile(
            nodeId=node_id,
            deploymentTier=DeploymentTier.EDGE,
            modelIds=model_ids,
            gpuMemoryMb=gpu_memory_mb,
            privacyLevel=privacy_level,
        ),
        NodeSnapshot(nodeId=node_id, availableMemoryMb=32768, observationSequence=0),
    )
    nodes.heartbeat(
        node_id,
        available_memory_mb=32768,
        queued_tasks=queued_tasks,
        observed_at=NOW,
    )


def _agent(
    agents: AgentService,
    agent_id: str,
    *,
    allowed_node_ids: list[str],
    required_model_ids: list[str],
    required_gpu_memory_mb: int = 0,
    min_privacy_level: str = "internal",
    success_rate: float = 0.9,
) -> None:
    agents.register(
        AgentProfile(
            agentId=agent_id,
            capabilities=["vision.infer"],
            allowedNodeIds=allowed_node_ids,
            requiredModelIds=required_model_ids,
            requiredGpuMemoryMb=required_gpu_memory_mb,
            minPrivacyLevel=min_privacy_level,
        ),
        AgentSnapshot(agentId=agent_id, successRate=success_rate),
    )


def test_two_layer_scheduler_filters_nodes_with_agent_whitelist_model_gpu_and_privacy() -> None:
    nodes = NodeService()
    agents = AgentService()
    _node(
        nodes,
        "edge-fast-but-forbidden",
        model_ids=["vision-large"],
        gpu_memory_mb=49152,
        privacy_level="restricted",
    )
    _node(
        nodes,
        "edge-whitelisted-small-model",
        model_ids=["vision-small"],
        gpu_memory_mb=49152,
        privacy_level="restricted",
    )
    _node(
        nodes,
        "edge-whitelisted-low-privacy",
        model_ids=["vision-large"],
        gpu_memory_mb=49152,
        privacy_level="internal",
    )
    _node(
        nodes,
        "edge-whitelisted-valid",
        model_ids=["vision-large"],
        gpu_memory_mb=24576,
        privacy_level="confidential",
        queued_tasks=2,
    )
    _agent(
        agents,
        "vision-agent",
        allowed_node_ids=[
            "edge-whitelisted-small-model",
            "edge-whitelisted-low-privacy",
            "edge-whitelisted-valid",
        ],
        required_model_ids=["vision-large"],
        required_gpu_memory_mb=16384,
        min_privacy_level="confidential",
    )
    scheduler = TwoLayerSchedulerService(node_service=nodes, agent_service=agents)

    placement = scheduler.schedule(
        capabilities=["vision.infer"],
        required_model_ids=["vision-large"],
        min_gpu_memory_mb=8192,
        min_privacy_level="internal",
        now=NOW,
    )

    assert placement is not None
    assert placement.agent.agent_id == "vision-agent"
    assert placement.node.node_id == "edge-whitelisted-valid"
    assert placement.effective_requirements["requiredModelIds"] == ["vision-large"]
    assert placement.effective_requirements["minGpuMemoryMb"] == 16384
    assert placement.effective_requirements["minPrivacyLevel"] == "confidential"


def test_two_layer_scheduler_does_not_fallback_outside_agent_whitelist() -> None:
    nodes = NodeService()
    agents = AgentService()
    _node(nodes, "cloud-valid-but-not-allowed", model_ids=["legal"], gpu_memory_mb=32768)
    _node(nodes, "edge-allowed-too-small", model_ids=["legal"], gpu_memory_mb=1024)
    _agent(
        agents,
        "legal-agent",
        allowed_node_ids=["edge-allowed-too-small"],
        required_model_ids=["legal"],
        required_gpu_memory_mb=8192,
    )

    placement = TwoLayerSchedulerService(node_service=nodes, agent_service=agents).schedule(
        capabilities=["vision.infer"],
        now=NOW,
    )

    assert placement is None


def test_two_layer_ready_schedule_creates_pair_bound_lease() -> None:
    nodes = NodeService()
    agents = AgentService()
    _node(nodes, "node-a", model_ids=["model-a"], gpu_memory_mb=8192)
    _agent(agents, "agent-a", allowed_node_ids=["node-a"], required_model_ids=["model-a"])
    scheduler = TwoLayerSchedulerService(
        node_service=nodes,
        agent_service=agents,
        coordinator=InMemoryLeaseCoordinator(),
    )

    result = scheduler.schedule_ready(
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        requirement=BindingRequirement(
            requiredCapabilities=["vision.infer"],
            requiredModelIds=["model-a"],
            preferences={"agentId": "agent-a", "nodeId": "node-a"},
        ),
        now=NOW,
    )

    assert result.status == "allocated"
    assert result.binding is not None
    assert result.binding.resource_id == "node-a"
    assert result.lease is not None
    assert result.lease.agent_id == "agent-a"
    assert result.lease.node_id == "node-a"
