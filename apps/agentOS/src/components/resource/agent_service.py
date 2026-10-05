"""Agent 注册表的事件驱动心跳与查询服务。"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.resource import AgentProfile, AgentSnapshot, AgentState

from .agent_store import AgentStore, InMemoryAgentStore
from .models import VersionedAgentSnapshot


class AgentService:
    """Agent 注册表的协调入口：登记、事件心跳、候选查询。"""

    def __init__(self, store: AgentStore | None = None) -> None:
        self.store = store or InMemoryAgentStore()

    def register(self, profile: AgentProfile, snapshot: AgentSnapshot) -> VersionedAgentSnapshot:
        return self.store.register(profile, snapshot)

    def report_state(
        self,
        agent_id: str,
        *,
        state: AgentState,
        node_id: str | None = None,
        current_step_id: str | None = None,
        success_rate: float | None = None,
        avg_latency_ms: float | None = None,
        avg_tokens: float | None = None,
    ) -> VersionedAgentSnapshot:
        """Agent 事件驱动心跳：空闲/运行/完成后的状态与指标更新。"""
        current = self.store.get_snapshot(agent_id)
        snapshot = current.snapshot.model_copy(update={
            "state": AgentState(state),
            "node_id": node_id,
            "current_step_id": current_step_id,
            "success_rate": current.snapshot.success_rate if success_rate is None else success_rate,
            "avg_latency_ms": current.snapshot.avg_latency_ms if avg_latency_ms is None else avg_latency_ms,
            "avg_tokens": current.snapshot.avg_tokens if avg_tokens is None else avg_tokens,
            "observed_at": datetime.now(timezone.utc),
            "observation_sequence": current.snapshot.observation_sequence + 1,
        })
        return self.store.update_snapshot(snapshot, expected_version=current.version)

    def profile(self, agent_id: str) -> AgentProfile:
        return self.store.get_profile(agent_id)

    def snapshot(self, agent_id: str) -> VersionedAgentSnapshot:
        return self.store.get_snapshot(agent_id)

    def profiles(self) -> list[AgentProfile]:
        return self.store.list_profiles()

    def set_enabled(self, agent_id: str, *, enabled: bool) -> AgentProfile:
        """切换 Agent 台账的调度开关；与资源目录的 enabled 联动由调用方负责。"""
        profile = self.store.get_profile(agent_id)
        return self.store.update_profile(profile.model_copy(update={"enabled": enabled}))

    def candidates(
        self, *, capabilities: list[str], only_idle: bool = True
    ) -> list[tuple[AgentProfile, VersionedAgentSnapshot]]:
        """按能力标签匹配 + 忙闲过滤，并按历史成功率降序返回。"""
        required = set(capabilities)
        selected: list[tuple[AgentProfile, VersionedAgentSnapshot]] = []
        for profile in self.store.list_profiles():
            if not profile.enabled:
                continue
            if not required.issubset(profile.capabilities):
                continue
            snapshot = self.store.get_snapshot(profile.agent_id)
            if only_idle and snapshot.snapshot.state is not AgentState.IDLE:
                continue
            selected.append((profile, snapshot))
        selected.sort(key=lambda item: item[1].snapshot.success_rate, reverse=True)
        return selected
