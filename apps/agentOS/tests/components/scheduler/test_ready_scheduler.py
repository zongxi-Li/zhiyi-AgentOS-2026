"""READY-node scheduler filtering, scoring and lease coordination tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from components.resource.service import ResourceService
from components.scheduler.leases import InMemoryLeaseCoordinator
from components.scheduler.service import SchedulerService
from contracts.resource import BindingRequirement, ResourceProfile, ResourceSnapshot, ResourceType


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _register(service: ResourceService, resource_id: str, *, capacity: int = 1, enabled: bool = True):
    service.register(
        ResourceProfile(
            resourceId=resource_id,
            resourceType=ResourceType.AGENT,
            capabilities=["analyse"],
            domains=["general"],
            capacity=capacity,
            enabled=enabled,
        ),
        ResourceSnapshot(resourceId=resource_id, availableSlots=capacity, utilization=0.0),
    )
    service.heartbeat(resource_id, received_at=NOW)


def test_scheduler_filters_then_scores_with_stable_resource_id_tie_break() -> None:
    resources = ResourceService(heartbeat_timeout=timedelta(minutes=5))
    _register(resources, "agent-b")
    _register(resources, "agent-a")
    _register(resources, "disabled", enabled=False)
    scheduler = SchedulerService(resource_service=resources)

    result = scheduler.schedule_ready(
        run_id="run-1",
        step_id="analyse",
        attempt_id="attempt-1",
        requirement=BindingRequirement(
            requiredCapabilities=["analyse"],
            domain="general",
            resourceTypes=["agent"],
        ),
        now=NOW,
    )

    assert result.status == "allocated"
    assert result.binding is not None and result.binding.resource_id == "agent-a"
    assert result.lease is not None and result.lease.attempt_id == "attempt-1"
    disabled = next(item for item in result.candidates if item.resource_id == "disabled")
    assert [reason.value for reason in disabled.reasons] == ["DISABLED"]


def test_atomic_capacity_allocation_never_exceeds_slots_under_100_requests() -> None:
    resources = ResourceService(heartbeat_timeout=timedelta(minutes=5))
    _register(resources, "worker", capacity=7)
    coordinator = InMemoryLeaseCoordinator()
    scheduler = SchedulerService(resource_service=resources, coordinator=coordinator)
    requirement = BindingRequirement(requiredCapabilities=["analyse"], resourceTypes=["agent"])

    def allocate(index: int):
        return scheduler.schedule_ready(
            run_id="run-100",
            step_id=f"step-{index}",
            attempt_id=f"attempt-{index}",
            requirement=requirement,
            now=NOW,
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(allocate, range(100)))

    assert sum(item.status == "allocated" for item in results) == 7
    assert coordinator.active_slots("worker", now=NOW) == 7


def test_expired_lease_releases_capacity() -> None:
    resources = ResourceService(heartbeat_timeout=timedelta(minutes=5))
    _register(resources, "worker")
    coordinator = InMemoryLeaseCoordinator()
    scheduler = SchedulerService(
        resource_service=resources,
        coordinator=coordinator,
        lease_ttl=timedelta(seconds=5),
    )
    requirement = BindingRequirement(requiredCapabilities=["analyse"])
    first = scheduler.schedule_ready(
        run_id="run", step_id="one", attempt_id="a1", requirement=requirement, now=NOW
    )
    second = scheduler.schedule_ready(
        run_id="run",
        step_id="two",
        attempt_id="a2",
        requirement=requirement,
        now=NOW + timedelta(seconds=6),
    )

    assert first.status == "allocated"
    assert second.status == "allocated"
