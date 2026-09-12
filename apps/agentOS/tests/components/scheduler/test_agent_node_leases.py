from __future__ import annotations

from datetime import datetime, timedelta, timezone

from components.scheduler.leases import InMemoryLeaseCoordinator, RedisLeaseCoordinator
from components.scheduler.service import SchedulerService
from components.resource.service import ResourceService
from contracts.resource import BindingRequirement, ResourceProfile, ResourceSnapshot, ResourceType


NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def test_in_memory_lease_capacity_is_keyed_by_agent_node_pair() -> None:
    coordinator = InMemoryLeaseCoordinator()

    first = coordinator.acquire(
        lease_id="lease-a1",
        resource_id="compat-node-1",
        agent_id="agent-a",
        node_id="node-1",
        capacity=1,
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        ttl=timedelta(seconds=30),
        now=NOW,
    )
    blocked_same_pair = coordinator.acquire(
        lease_id="lease-a2",
        resource_id="compat-node-1",
        agent_id="agent-a",
        node_id="node-1",
        capacity=1,
        run_id="run-1",
        step_id="step-2",
        attempt_id="attempt-2",
        ttl=timedelta(seconds=30),
        now=NOW,
    )
    other_agent_same_node = coordinator.acquire(
        lease_id="lease-b1",
        resource_id="compat-node-1",
        agent_id="agent-b",
        node_id="node-1",
        capacity=1,
        run_id="run-1",
        step_id="step-3",
        attempt_id="attempt-3",
        ttl=timedelta(seconds=30),
        now=NOW,
    )

    assert first is not None
    assert first.agent_id == "agent-a"
    assert first.node_id == "node-1"
    assert first.resource_id == "compat-node-1"
    assert blocked_same_pair is None
    assert other_agent_same_node is not None
    assert coordinator.active_slots("compat-node-1", agent_id="agent-a", node_id="node-1", now=NOW) == 1
    assert coordinator.active_slots("compat-node-1", agent_id="agent-b", node_id="node-1", now=NOW) == 1


def test_in_memory_lease_idempotent_retry_returns_original_pair() -> None:
    coordinator = InMemoryLeaseCoordinator()
    original = coordinator.acquire(
        lease_id="same-lease",
        resource_id="compat-node-1",
        agent_id="agent-a",
        node_id="node-1",
        capacity=1,
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        ttl=timedelta(seconds=30),
        now=NOW,
    )

    repeated = coordinator.acquire(
        lease_id="same-lease",
        resource_id="compat-node-1",
        agent_id="agent-a",
        node_id="node-1",
        capacity=1,
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        ttl=timedelta(seconds=30),
        now=NOW,
    )

    assert repeated == original


class _RedisStub:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def eval(self, *args):
        self.calls.append(args)
        return 1


def test_redis_lease_payload_and_keys_include_agent_node_pair() -> None:
    client = _RedisStub()
    lease = RedisLeaseCoordinator(client).acquire(
        lease_id="redis-pair",
        resource_id="compat-node-1",
        agent_id="agent-a",
        node_id="node-1",
        capacity=1,
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        ttl=timedelta(seconds=30),
        now=NOW,
    )

    assert lease is not None
    assert lease.agent_id == "agent-a"
    assert lease.node_id == "node-1"
    call = client.calls[0]
    flattened = "\n".join(str(part) for part in call)
    assert "agentos:scheduler:pair:agent-a:node-1" in flattened
    assert '"agentId":"agent-a"' in flattened
    assert '"nodeId":"node-1"' in flattened


def test_scheduler_ready_passes_agent_node_pair_to_lease_coordinator() -> None:
    resources = ResourceService()
    resources.register(
        ResourceProfile(
            resourceId="compat-node-1",
            resourceType=ResourceType.WORKER,
            capabilities=["vision.infer"],
            capacity=1,
        ),
        ResourceSnapshot(resourceId="compat-node-1", availableSlots=1, utilization=0.0),
    )
    resources.heartbeat("compat-node-1", received_at=NOW)
    coordinator = InMemoryLeaseCoordinator()

    result = SchedulerService(resource_service=resources, coordinator=coordinator).schedule_ready(
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        requirement=BindingRequirement(
            requiredCapabilities=["vision.infer"],
            preferences={
                "resourceId": "compat-node-1",
                "agentId": "agent-a",
                "nodeId": "node-1",
            },
        ),
        now=NOW,
    )

    assert result.status == "allocated"
    assert result.lease is not None
    assert result.lease.agent_id == "agent-a"
    assert result.lease.node_id == "node-1"
