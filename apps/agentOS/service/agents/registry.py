"""Agent 服务注册表与运行范围视图。"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from contracts.authority import LogicalAgentId
from .base import BaseAgent


class AgentNotFound(KeyError):
    """当前领域、名称、能力或运行范围内没有可调用 Agent 时抛出。"""


class AgentRegistry:
    """注册并按领域、名称、能力解析 Agent。"""

    def __init__(self) -> None:
        self._agents: Dict[Tuple[str, str], BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """按规范化领域和名称登记 Agent，空标识不写入。"""
        domain = (agent.profile.domain or "").strip().lower()
        name = (agent.profile.agent_name or "").strip().lower()
        if not domain or not name:
            raise ValueError("agent domain and agentName are required")
        self._agents[(domain, name)] = agent

    def resolve(
        self,
        domain: str,
        agent_name: Optional[str] = None,
        capability: Optional[str] = None,
        *,
        allowed_agent_ids: Iterable[str] | None = None,
    ) -> BaseAgent:
        """在可见范围内优先按名称、再按能力解析 Agent。"""
        normalized_domain = (domain or "").strip().lower()
        normalized_name = (agent_name or "").strip().lower()
        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None
        if normalized_name:
            for candidate_domain in (normalized_domain, "general"):
                agent = self._agents.get((candidate_domain, normalized_name))
                if agent is not None and (allowed is None or self.agent_id(agent) in allowed):
                    return agent
        normalized_capability = (capability or "").strip().lower()
        if normalized_capability:
            for candidate_domain in ((normalized_domain, "general") if normalized_domain != "general" else ("general",)):
                for (agent_domain, _), agent in self._agents.items():
                    if agent_domain != candidate_domain:
                        continue
                    if allowed is not None and self.agent_id(agent) not in allowed:
                        continue
                    if normalized_capability in {item.lower() for item in agent.profile.capabilities}:
                        return agent
        raise AgentNotFound(
            f"agent not registered: domain={domain}, agentName={agent_name}, capability={capability}"
        )

    def resolve_by_id(
        self,
        agent_id: str,
        *,
        allowed_agent_ids: Iterable[str] | None = None,
    ) -> BaseAgent:
        """按稳定 Agent 标识解析实例，并保持冻结 scope 的访问限制。"""
        normalized_id = str(agent_id).strip()
        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None
        if allowed is not None and normalized_id not in allowed:
            raise AgentNotFound(f"agent is outside the execution scope: {normalized_id}")
        for agent in self._agents.values():
            if self.agent_id(agent) == normalized_id:
                return agent
        raise AgentNotFound(f"agent id is not registered: {normalized_id}")

    def all(self) -> Iterable[BaseAgent]:
        """按登记顺序返回当前 Agent 快照。"""
        return tuple(self._agents.values())

    @staticmethod
    def agent_id(agent: BaseAgent) -> LogicalAgentId:
        """优先返回显式 Agent 标识，缺失时回退到名称。"""
        return LogicalAgentId(str(agent.profile.agent_id or agent.profile.agent_name))

    def scoped(self, agent_ids: Iterable[str]) -> "ScopedAgentRegistry":
        """创建仅包含指定标识的只读运行范围视图。"""
        return ScopedAgentRegistry(self, tuple(agent_ids))


class ScopedAgentRegistry:
    """单个 run 的冻结 Agent 可见性视图。"""

    def __init__(self, registry: AgentRegistry, agent_ids: tuple[str, ...]) -> None:
        self._registry = registry
        self._agent_ids = frozenset(agent_ids)

    def all(self) -> Iterable[BaseAgent]:
        """返回底层注册表中属于当前运行范围的 Agent。"""
        return tuple(agent for agent in self._registry.all() if self._registry.agent_id(agent) in self._agent_ids)

    def agent_id(self, agent: BaseAgent) -> str:
        """委托底层注册表获得稳定标识，不扩大当前可见范围。"""
        return self._registry.agent_id(agent)

    def resolve(self, domain: str, agent_name: Optional[str] = None, capability: Optional[str] = None) -> BaseAgent:
        """仅从冻结范围内解析 Agent；越界候选与缺失候选都明确失败。"""
        return self._registry.resolve(domain, agent_name, capability, allowed_agent_ids=self._agent_ids)

    def resolve_by_id(self, agent_id: str) -> BaseAgent:
        """只按当前冻结 scope 内的稳定 Agent 标识解析实例。"""
        return self._registry.resolve_by_id(agent_id, allowed_agent_ids=self._agent_ids)
