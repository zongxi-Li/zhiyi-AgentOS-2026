"""仅依据共享能力目录执行确定性的能力绑定与协作路由。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from service.agents import AgentRegistry
from service.agents.base import BaseAgent
from support.acg.models import CapabilityCatalog, PlanningCapabilityDescriptor
from support.acg.models import build_default_capability_catalog
from support.acg.models import TaskSemanticProfile


@dataclass
class CapabilityBinding:
    """一个能力到智能体的候选绑定；``score`` 仅用于同次路由的稳定排序。"""
    capability: str
    agent_name: str
    score: float
    ephemeral: bool = False


@dataclass
class CollaborationNetwork:
    """能力绑定后的协作网络。

    ``bindings`` 保持所需能力的处理顺序，``estimated_entropy`` 是跨智能体边界估算；
    未解析能力或超过 ``entropy_budget`` 时调用方应拒绝执行。
    """
    bindings: List[CapabilityBinding] = field(default_factory=list)
    estimated_entropy: int = 0
    entropy_budget: int = 0
    notes: List[str] = field(default_factory=list)
    unresolved_capabilities: List[str] = field(default_factory=list)

    @property
    def agent_names(self) -> List[str]:
        """按首次绑定顺序返回去重智能体名称，不修改绑定集合。"""
        return list(dict.fromkeys(binding.agent_name for binding in self.bindings))

    @property
    def over_budget(self) -> bool:
        """在存在正预算且估算熵超限时返回真。"""
        return self.entropy_budget > 0 and self.estimated_entropy > self.entropy_budget


class CognitiveRouter:
    """在受限领域回退内，以稳定排序绑定已规范化能力和智能体。"""

    def __init__(
        self,
        agent_registry: AgentRegistry,
        capability_catalog: CapabilityCatalog | None = None,
        *,
        entropy_per_edge: int = 256,
    ) -> None:
        self.agent_registry = agent_registry
        self.capability_catalog = capability_catalog or build_default_capability_catalog()
        self.entropy_per_edge = entropy_per_edge

    def route(self, profile: TaskSemanticProfile, *, domain: str) -> CollaborationNetwork:
        """为画像中的能力生成确定性协作网络。

        仅在领域可见的目录与已注册智能体中选择，按能力请求顺序处理，并以领域、语义、
        优先级和注册顺序稳定排序；不改变注册表或画像。
        """
        network = CollaborationNetwork(entropy_budget=profile.entropy_budget)
        available = {
            item.capability_id for item in self.capability_catalog.available(domain)
        }
        agents = list(self.agent_registry.all())

        for requested in profile.required_capabilities:
            try:
                descriptor = self.capability_catalog.resolve(requested)
            except KeyError:
                network.unresolved_capabilities.append(requested)
                network.notes.append(f"unregistered planning capability: {requested}")
                continue
            if descriptor.capability_id not in available:
                network.unresolved_capabilities.append(descriptor.capability_id)
                network.notes.append(
                    f"capability unavailable for domain {domain}: {descriptor.capability_id}"
                )
                continue
            binding = self._match_capability(descriptor, agents, domain=domain)
            if binding is None:
                network.unresolved_capabilities.append(descriptor.capability_id)
                network.notes.append(f"unresolved capability: {descriptor.capability_id}")
            else:
                network.bindings.append(binding)

        network.estimated_entropy = max(0, len(network.agent_names) - 1) * self.entropy_per_edge
        if network.over_budget:
            network.notes.append(
                f"estimated entropy {network.estimated_entropy} exceeds budget "
                f"{network.entropy_budget}"
            )
        return network

    def _match_capability(
        self,
        descriptor: PlanningCapabilityDescriptor,
        agents: list[BaseAgent],
        *,
        domain: str,
    ) -> Optional[CapabilityBinding]:
        candidates = self.candidates_for(descriptor, domain=domain, agents=agents)
        return candidates[0] if candidates else None

    def candidates_for(
        self,
        descriptor: PlanningCapabilityDescriptor,
        *,
        domain: str,
        agents: list[BaseAgent] | None = None,
    ) -> list[CapabilityBinding]:
        """返回作用域内兼容绑定，并按领域、语义、优先级、注册顺序稳定降序排列。"""

        task_domain = (domain or "").strip().lower()
        aliases = {
            descriptor.capability_id.lower(),
            *(alias.strip().lower() for alias in descriptor.aliases),
        }
        ranked: list[tuple[tuple[int, float, int, int], BaseAgent]] = []
        for index, agent in enumerate(agents or list(self.agent_registry.all())):
            agent_domain = (agent.profile.domain or "").strip().lower()
            if task_domain == "general":
                if agent_domain != "general":
                    continue
                domain_rank = 2
            elif agent_domain == task_domain:
                domain_rank = 2
            elif agent_domain == "general":
                domain_rank = 1
            else:
                continue

            agent_terms = {
                *(item.strip().lower() for item in agent.profile.capabilities),
                (agent.profile.agent_name or "").strip().lower(),
            }
            semantic = self._semantic_score(aliases, agent_terms)
            if semantic <= 0:
                continue
            ranked.append(
                (
                    (
                        domain_rank,
                        semantic,
                        int(agent.profile.binding_priority),
                        -index,
                    ),
                    agent,
                )
            )

        bindings: list[CapabilityBinding] = []
        for rank, agent in sorted(ranked, key=lambda item: item[0], reverse=True):
            score = rank[0] + rank[1] + max(0, rank[2]) / 1000
            bindings.append(
                CapabilityBinding(
                    capability=descriptor.capability_id,
                    agent_name=agent.profile.agent_name,
                    score=round(score, 4),
                )
            )
        return bindings

    @staticmethod
    def _semantic_score(aliases: set[str], agent_terms: set[str]) -> float:
        if aliases & agent_terms:
            return 1.0
        if any(
            alias and term and (alias in term or term in alias)
            for alias in aliases
            for term in agent_terms
        ):
            return 0.8
        return 0.0


__all__ = ["CognitiveRouter", "CollaborationNetwork", "CapabilityBinding"]
