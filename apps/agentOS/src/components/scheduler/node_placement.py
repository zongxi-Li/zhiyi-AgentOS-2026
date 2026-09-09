"""节点放置：端边云硬约束过滤与软评分（纯函数）。"""

from __future__ import annotations

from contracts.resource import NodeHealthStatus, NodeProfile, NodeSnapshot

_PRIVACY_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def node_eligible(
    profile: NodeProfile,
    *,
    health_status: NodeHealthStatus,
    min_gpu_memory_mb: int = 0,
    min_privacy_level: str | None = None,
) -> bool:
    """节点硬约束：状态健康 + 显存足够 + 隐私满足。"""
    if not profile.enabled:
        return False
    if health_status in (NodeHealthStatus.STALE, NodeHealthStatus.OFFLINE):
        return False
    if profile.gpu_memory_mb < min_gpu_memory_mb:
        return False
    if (
        min_privacy_level is not None
        and _PRIVACY_RANK.get(profile.privacy_level, -1) < _PRIVACY_RANK.get(min_privacy_level, -1)
    ):
        return False
    return True


def node_score(
    profile: NodeProfile,
    snapshot: NodeSnapshot,
    *,
    reliability: float,
) -> float:
    """节点软评分：负载越低、排队越少、可靠度越高越优。"""
    load = max(snapshot.cpu_utilization, snapshot.gpu_utilization)
    queue = min(1.0, snapshot.queued_tasks / 10.0)
    return round(0.5 * reliability + 0.3 * (1.0 - load) + 0.2 * (1.0 - queue), 9)
