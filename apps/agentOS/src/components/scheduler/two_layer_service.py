"""端边云两层调度服务：先选 Agent，再放置节点，最后租约。"""

from __future__ import annotations

from datetime import datetime

from contracts.resource import AgentProfile, NodeProfile

from ..resource.agent_service import AgentService
from ..resource.node_service import NodeService
from .agent_selection import agent_eligible, agent_score
from .node_placement import node_eligible, node_score


def _reliability_from_failures(consecutive_failures: int) -> float:
    return 1.0 / (1.0 + consecutive_failures)


class TwoLayerSchedulerService:
    """组合节点放置与 Agent 选择，作为统一资源调度的替代入口。"""

    def __init__(
        self,
        node_service: NodeService | None = None,
        agent_service: AgentService | None = None,
    ) -> None:
        self.node_service = node_service or NodeService()
        self.agent_service = agent_service or AgentService()

    def select_agent(
        self, *, capabilities: list[str], only_idle: bool = True
    ) -> AgentProfile | None:
        """按能力标签 + 忙闲 + 历史成功率选择最优 Agent。"""
        candidates = self.agent_service.candidates(capabilities=capabilities, only_idle=only_idle)
        return candidates[0][0] if candidates else None

    def place_node(
        self,
        *,
        min_gpu_memory_mb: int = 0,
        min_privacy_level: str | None = None,
        node_types: list[str] | None = None,
        now: datetime | None = None,
    ) -> NodeProfile | None:
        """硬约束过滤 + 软评分选出最优节点。"""
        best: tuple[float, NodeProfile] | None = None
        for profile in self.node_service.profiles():
            if node_types and profile.node_type.value not in node_types:
                continue
            snapshot = self.node_service.snapshot(profile.node_id).snapshot
            health = self.node_service.health_monitor.health(profile.node_id, now=now)
            if not node_eligible(
                profile,
                health_status=health.status,
                min_gpu_memory_mb=min_gpu_memory_mb,
                min_privacy_level=min_privacy_level,
            ):
                continue
            reliability = _reliability_from_failures(health.consecutive_failures)
            score = node_score(profile, snapshot, reliability=reliability)
            if best is None or score > best[0]:
                best = (score, profile)
        return best[1] if best else None
