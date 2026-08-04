"""资源候选集必须只包含能立即承接工作的健康资源。"""

from datetime import datetime, timedelta, timezone

from contracts.resource import ResourceProfile, ResourceSnapshot
from resource.service import ResourceService


def _snapshot(resource_id: str, slots: int, observed_at: datetime) -> ResourceSnapshot:
    return ResourceSnapshot(
        resourceId=resource_id,
        availableSlots=slots,
        utilization=0.2,
        observedAt=observed_at,
    )


def test_candidates_exclude_unhealthy_and_full_resources():
    """候选资源必须同时满足能力、健康状态和空闲槽位条件。"""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    service = ResourceService(heartbeat_timeout=timedelta(seconds=30))

    for resource_id, slots in (("healthy", 1), ("unhealthy", 1), ("full", 0)):
        service.register(
            ResourceProfile(resourceId=resource_id, capabilities=["summarize"]),
            _snapshot(resource_id, slots, now),
        )

    service.heartbeat("healthy", received_at=now)
    service.heartbeat("full", received_at=now)
    service.heartbeat("unhealthy", received_at=now - timedelta(minutes=1))

    candidates = service.candidates(["summarize"], now=now)

    assert [candidate.profile.resource_id for candidate in candidates] == ["healthy"]


def test_snapshot_updates_are_versioned_and_replace_the_latest_observation():
    """每次快照更新都应产生递增版本，供调度器识别观测新旧。"""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    service = ResourceService()
    service.register(
        ResourceProfile(resourceId="worker", capabilities=["summarize"]),
        _snapshot("worker", 1, now),
    )

    updated = service.update_snapshot(_snapshot("worker", 2, now + timedelta(seconds=1)))

    assert updated.version == 2
    assert service.snapshot("worker").snapshot.available_slots == 2
