"""Agent 选择：能力匹配 + 忙闲过滤 + 成功率排序（纯函数）。"""

from __future__ import annotations

from contracts.resource import AgentProfile, AgentSnapshot, AgentState


def agent_eligible(
    profile: AgentProfile,
    snapshot: AgentSnapshot,
    *,
    required_capabilities: list[str],
    only_idle: bool = True,
) -> bool:
    """Agent 硬约束：启用 + 能力子集 + 空闲。"""
    if not profile.enabled:
        return False
    if not set(required_capabilities).issubset(profile.capabilities):
        return False
    if only_idle and snapshot.state is not AgentState.IDLE:
        return False
    return True


def agent_score(snapshot: AgentSnapshot) -> float:
    """Agent 软评分：历史成功率越高越优。"""
    return snapshot.success_rate
