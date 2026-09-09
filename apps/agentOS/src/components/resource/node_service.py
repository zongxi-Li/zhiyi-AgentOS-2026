"""面向调度器的节点登记、心跳与候选查询服务。"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.resource import NodeHealthStatus, NodeProfile, NodeSnapshot

from .models import NodeHealth, VersionedNodeSnapshot
from .node_health import NodeHealthMonitor, infer_load_status
from .node_store import InMemoryNodeStore, NodeStore

_PRIVACY_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def _privacy_rank(value: str) -> int:
    return _PRIVACY_RANK.get(value, -1)


class NodeService:
    """节点资源表的协调入口：登记、心跳、候选查询。"""

    def __init__(
        self,
        store: NodeStore | None = None,
        health_monitor: NodeHealthMonitor | None = None,
    ) -> None:
        self.store = store or InMemoryNodeStore()
        self.health_monitor = health_monitor or NodeHealthMonitor()

    def register(self, profile: NodeProfile, snapshot: NodeSnapshot) -> VersionedNodeSnapshot:
        return self.store.register(profile, snapshot)

    def heartbeat(
        self,
        node_id: str,
        *,
        cpu_utilization: float = 0.0,
        gpu_utilization: float = 0.0,
        available_memory_mb: int = 0,
        queued_tasks: int = 0,
        latency_ms: float | None = None,
        success: bool = True,
        observed_at: datetime | None = None,
    ) -> NodeHealth:
        """节点上报一次心跳：刷新快照动态字段与健康投影。"""
        timestamp = observed_at if observed_at is not None else datetime.now(timezone.utc)
        current = self.store.get_snapshot(node_id)
        load = max(cpu_utilization, gpu_utilization)
        snapshot = current.snapshot.model_copy(update={
            "cpu_utilization": cpu_utilization,
            "gpu_utilization": gpu_utilization,
            "available_memory_mb": available_memory_mb,
            "queued_tasks": queued_tasks,
            "latency_ms": latency_ms,
            "health_status": infer_load_status(queued_tasks, load),
            "last_heartbeat": timestamp,
            "observed_at": timestamp,
            "observation_sequence": current.snapshot.observation_sequence + 1,
        })
        self.store.update_snapshot(snapshot, expected_version=current.version)
        return self.health_monitor.report(
            node_id,
            observed_at=timestamp,
            queued_tasks=queued_tasks,
            utilization=load,
            success=success,
        )

    def profile(self, node_id: str) -> NodeProfile:
        return self.store.get_profile(node_id)

    def snapshot(self, node_id: str) -> VersionedNodeSnapshot:
        return self.store.get_snapshot(node_id)

    def profiles(self) -> list[NodeProfile]:
        return self.store.list_profiles()

    def health(self, node_id: str, *, now: datetime | None = None) -> NodeHealth:
        return self.health_monitor.health(node_id, now=now)

    def candidates(
        self,
        *,
        min_gpu_memory_mb: int = 0,
        min_privacy_level: str | None = None,
        node_types: list[str] | None = None,
        now: datetime | None = None,
    ) -> list[NodeProfile]:
        """按硬约束过滤出健康可用的节点。"""
        selected: list[NodeProfile] = []
        for profile in self.store.list_profiles():
            if not profile.enabled:
                continue
            health = self.health_monitor.health(profile.node_id, now=now)
            if health.status in (NodeHealthStatus.STALE, NodeHealthStatus.OFFLINE):
                continue
            if profile.gpu_memory_mb < min_gpu_memory_mb:
                continue
            if (
                min_privacy_level is not None
                and _privacy_rank(profile.privacy_level) < _privacy_rank(min_privacy_level)
            ):
                continue
            if node_types and profile.node_type.value not in node_types:
                continue
            selected.append(profile)
        return selected
