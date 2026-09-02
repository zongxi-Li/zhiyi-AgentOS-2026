from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from components.resource.service import ResourceService
from contracts.resource import (
    DeploymentTier,
    ResourceEndpoint,
    ResourceHealthStatus,
    ResourceProfile,
    ResourceSnapshot,
    ResourceType,
)


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _register_edge() -> ResourceService:
    resources = ResourceService(heartbeat_timeout=timedelta(seconds=30))
    resources.register(
        ResourceProfile(
            resourceId="edge-01",
            resourceType=ResourceType.WORKER,
            deploymentTier=DeploymentTier.EDGE,
            capabilities=["vision.infer"],
            executionEndpoint=ResourceEndpoint(protocol="http", address="http://edge-01:9000"),
        ),
        ResourceSnapshot(
            resourceId="edge-01",
            availableSlots=1,
            utilization=0.0,
            healthStatus=ResourceHealthStatus.UNKNOWN,
        ),
    )
    return resources


def test_remote_heartbeat_is_authoritative_and_expires_without_refresh() -> None:
    resources = _register_edge()

    online = resources.heartbeat("edge-01", received_at=NOW, source="external")
    stale = resources.health_monitor.health("edge-01", now=NOW + timedelta(seconds=31))

    assert online.healthy is True
    assert stale.healthy is False


def test_local_runtime_cannot_refresh_remote_resource() -> None:
    resources = _register_edge()

    with pytest.raises(ValueError, match="external heartbeat"):
        resources.heartbeat("edge-01", received_at=NOW, source="local")


def test_remote_observation_updates_snapshot_and_health_atomically() -> None:
    resources = _register_edge()

    health = resources.observe_remote(
        "edge-01",
        available_slots=3,
        utilization=0.25,
        latency_ms=18,
        observed_at=NOW,
    )
    snapshot = resources.snapshot("edge-01")

    assert health.healthy is True
    assert snapshot.snapshot.available_slots == 3
    assert snapshot.snapshot.utilization == 0.25
    assert snapshot.snapshot.latency_ms == 18
    assert snapshot.snapshot.health_status is ResourceHealthStatus.ONLINE
