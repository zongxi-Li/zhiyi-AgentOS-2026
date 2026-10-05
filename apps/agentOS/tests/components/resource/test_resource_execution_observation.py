"""observe_execution 的服务级契约：健康 EMA 与目录快照必须同步更新。"""

from __future__ import annotations

import pytest

from components.resource.service import ResourceService
from components.resource.store import InMemoryResourceStore
from contracts.resource import ResourceHealthStatus, ResourceProfile, ResourceSnapshot, ResourceType


@pytest.fixture
def service() -> ResourceService:
    service = ResourceService(store=InMemoryResourceStore())
    service.register(
        ResourceProfile(
            resourceId="case_intake",
            resourceType=ResourceType.AGENT,
            capabilities=["case_intake"],
            domains=["legal"],
        ),
        ResourceSnapshot(
            resourceId="case_intake",
            availableSlots=1,
            utilization=0.0,
            healthStatus=ResourceHealthStatus.UNKNOWN,
        ),
    )
    return service


def test_successful_execution_updates_snapshot_latency_and_reliability(service: ResourceService) -> None:
    health = service.observe_execution("case_intake", success=True, latency_ms=1500.0)

    assert health.reliability == pytest.approx(0.6)  # EMA(0.5 -> success, alpha=0.2)
    snapshot = service.snapshot("case_intake").snapshot
    assert snapshot.latency_ms == 1500.0
    assert snapshot.reliability == pytest.approx(0.6)
    assert snapshot.health_status is ResourceHealthStatus.ONLINE
    assert snapshot.observation_sequence == 1
    # 利用率归调度器记账，执行观测不得伪造。
    assert snapshot.utilization == 0.0


def test_failed_execution_lowers_reliability_without_faking_online(service: ResourceService) -> None:
    service.observe_execution("case_intake", success=True, latency_ms=1000.0)

    health = service.observe_execution("case_intake", success=False, latency_ms=3000.0)

    assert health.reliability == pytest.approx(0.6 * 0.8 + 0.0 * 0.2)
    snapshot = service.snapshot("case_intake").snapshot
    assert snapshot.reliability == pytest.approx(0.6 * 0.8)
    # 失败不得把快照标成在线；健康降级由既有的 set_health 路径负责。
    assert snapshot.health_status is ResourceHealthStatus.ONLINE  # 首次成功留下的状态
    assert snapshot.latency_ms == 3000.0


def test_observation_is_treated_as_activity_signal(service: ResourceService) -> None:
    service.observe_execution("case_intake", success=True, latency_ms=800.0)

    health = service.health_monitor.health("case_intake")
    # 执行观测视为活动信号：last_heartbeat 被刷新，资源在 TTL 内视为健康。
    assert health.healthy is True
    assert health.last_heartbeat is not None


def test_observe_execution_rejects_unknown_resource(service: ResourceService) -> None:
    with pytest.raises(KeyError):
        service.observe_execution("missing_resource", success=True, latency_ms=10.0)
