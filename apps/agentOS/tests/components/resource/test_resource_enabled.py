"""资源启用/停用开关的服务级契约：资源画像与 agent 目录投影必须同变。"""

from __future__ import annotations

import pytest

from components.resource.agent_service import AgentService
from components.resource.agent_store import InMemoryAgentStore
from components.resource.service import ResourceService
from components.resource.store import InMemoryResourceStore
from contracts.resource import (
    AgentProfile,
    AgentSnapshot,
    AgentState,
    ResourceHealthStatus,
    ResourceProfile,
    ResourceSnapshot,
    ResourceType,
)


def _agent_resource(resource_id: str = "case_intake") -> tuple[ResourceService, AgentService]:
    resource_service = ResourceService(store=InMemoryResourceStore())
    resource_service.register(
        ResourceProfile(
            resourceId=resource_id,
            resourceType=ResourceType.AGENT,
            capabilities=["agent:case_intake", "case_intake"],
            domains=["legal"],
            enabled=True,
            metadata={
                "directoryKind": "agent",
                "agent": {
                    "agent_id": resource_id,
                    "agent_name": "Case Intake",
                    "domain": "legal",
                    "capabilities": ["case_intake"],
                    "version": "v1",
                    "priority": 10,
                    "enabled": True,
                    "resource_id": None,
                    "labels": [],
                },
            },
        ),
        ResourceSnapshot(
            resourceId=resource_id,
            availableSlots=1,
            utilization=0.0,
            healthStatus=ResourceHealthStatus.ONLINE,
        ),
    )
    agent_service = AgentService(store=InMemoryAgentStore())
    agent_service.register(
        AgentProfile(
            agentId=resource_id,
            capabilities=["case_intake"],
            metadata={"agentName": "Case Intake", "domain": "legal"},
        ),
        AgentSnapshot(agentId=resource_id, state=AgentState.IDLE),
    )
    return resource_service, agent_service


def test_set_enabled_flips_profile_and_agent_metadata() -> None:
    resource_service, _ = _agent_resource()

    updated = resource_service.set_enabled("case_intake", enabled=False)

    assert updated.enabled is False
    stored = resource_service.profile("case_intake")
    assert stored.enabled is False
    assert stored.metadata["agent"]["enabled"] is False


def test_disabled_resource_is_not_a_scheduling_candidate() -> None:
    resource_service, _ = _agent_resource()
    resource_service.heartbeat("case_intake")

    assert resource_service.candidates(["case_intake"])

    resource_service.set_enabled("case_intake", enabled=False)

    assert resource_service.candidates(["case_intake"]) == []


def test_set_enabled_round_trip_restores_scheduling() -> None:
    resource_service, _ = _agent_resource()
    resource_service.heartbeat("case_intake")

    resource_service.set_enabled("case_intake", enabled=False)
    resource_service.set_enabled("case_intake", enabled=True)

    assert resource_service.candidates(["case_intake"])


def test_agent_ledger_set_enabled_updates_store_profile() -> None:
    _, agent_service = _agent_resource()

    updated = agent_service.set_enabled("case_intake", enabled=False)

    assert updated.enabled is False
    assert agent_service.profile("case_intake").enabled is False


def test_set_enabled_unknown_resource_raises_key_error() -> None:
    resource_service, _ = _agent_resource()

    with pytest.raises(KeyError):
        resource_service.set_enabled("missing_resource", enabled=False)
