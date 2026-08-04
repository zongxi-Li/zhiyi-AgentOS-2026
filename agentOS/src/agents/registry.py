"""AgentOS Core 的智能体注册表，负责按领域、名称和能力解析应用层 Pack 智能体。"""


from typing import Dict, Iterable, Optional, Tuple

from agents.base import BaseAgent


class AgentNotFound(KeyError):
    """工作流步骤找不到匹配智能体时抛出。"""


class AgentRegistry:
    """供 Core 解析应用层 Pack 智能体的注册表。"""

    def __init__(self):
        self._agents: Dict[Tuple[str, str], BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """按规范化领域和名称注册智能体；缺少任一标识时抛出 ``ValueError`` 并不写入。"""
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
        """在可见作用域内解析智能体。

        先精确名称、再通用领域名称，最后按注册顺序匹配能力；未命中抛出 ``AgentNotFound``，
        读取过程不修改注册表。
        """
        normalized_domain = (domain or "").strip().lower()
        normalized_name = (agent_name or "").strip().lower()

        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None

        if normalized_name:
            agent = self._agents.get((normalized_domain, normalized_name))
            if agent is not None and (
                allowed is None or self.agent_id(agent) in allowed
            ):
                return agent
            if normalized_domain != "general":
                agent = self._agents.get(("general", normalized_name))
                if agent is not None and (
                    allowed is None or self.agent_id(agent) in allowed
                ):
                    return agent

        normalized_capability = (capability or "").strip().lower()
        if normalized_capability:
            candidate_domains = (
                (normalized_domain, "general")
                if normalized_domain != "general"
                else ("general",)
            )
            for candidate_domain in candidate_domains:
                for (agent_domain, _), agent in self._agents.items():
                    if agent_domain != candidate_domain:
                        continue
                    if allowed is not None and self.agent_id(agent) not in allowed:
                        continue
                    if normalized_capability in {
                        item.lower() for item in agent.profile.capabilities
                    }:
                        return agent

        raise AgentNotFound(
            f"agent not registered: domain={domain}, agentName={agent_name}, capability={capability}"
        )

    def all(self) -> Iterable[BaseAgent]:
        """按注册顺序返回全部智能体的不可变快照，复杂度 ``O(A)``。"""
        return tuple(self._agents.values())

    @staticmethod
    def agent_id(agent: BaseAgent) -> str:
        """返回稳定可见性标识；优先显式 ``agent_id``，否则回退智能体名称。"""
        return str(agent.profile.agent_id or agent.profile.agent_name)

    def scoped(self, agent_ids: Iterable[str]) -> "ScopedAgentRegistry":
        """创建冻结可见标识集合的只读注册表视图，不复制智能体实例。"""
        return ScopedAgentRegistry(self, tuple(agent_ids))


class ScopedAgentRegistry:
    """进程级智能体注册表的单运行只读视图；只暴露创建时指定的标识集合。"""

    def __init__(self, registry: AgentRegistry, agent_ids: tuple[str, ...]) -> None:
        self._registry = registry
        self._agent_ids = frozenset(agent_ids)

    def all(self) -> Iterable[BaseAgent]:
        """按底层注册顺序返回作用域内智能体，复杂度 ``O(A)``。"""
        return tuple(
            agent
            for agent in self._registry.all()
            if self._registry.agent_id(agent) in self._agent_ids
        )

    def agent_id(self, agent: BaseAgent) -> str:
        """委托底层注册表取得稳定智能体标识，不扩大本视图可见性。"""
        return self._registry.agent_id(agent)

    def resolve(
        self,
        domain: str,
        agent_name: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> BaseAgent:
        """在冻结作用域内执行名称/能力解析；越界候选与不存在候选均抛出 ``AgentNotFound``。"""
        return self._registry.resolve(
            domain,
            agent_name,
            capability,
            allowed_agent_ids=self._agent_ids,
        )
