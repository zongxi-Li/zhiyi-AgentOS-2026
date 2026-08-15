"""统一资源目录：登记能力元数据并稳定识别可执行 Agent。

目录只保存资源描述，不保存 Agent 输入输出或供应商运行时对象。Agent 实例仍由
``service.agents.AgentRegistry`` 持有；目录负责在 ACG 准备阶段按领域、能力、健康状态和
冻结 scope 选出稳定 agentId，从而避免执行期因全局注册表变化而漂移。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from contracts.capability import CapabilityKind, CapabilityManifest
from service.agents.base import AgentProfile


class ResourceConflictError(ValueError):
    """同一资源身份被登记为不同描述时抛出。"""


class ResourceNotFoundError(KeyError):
    """没有满足领域、能力、健康和 scope 条件的资源时抛出。"""


@dataclass(frozen=True)
class AgentResource:
    """Agent 的目录投影，字段来自 AgentProfile 且不携带可调用实例。"""

    agent_id: str
    agent_name: str
    domain: str
    capabilities: tuple[str, ...]
    version: str
    priority: int
    enabled: bool
    resource_id: str | None = None
    labels: tuple[tuple[str, str], ...] = ()


class ResourceDirectory:
    """单机资源元数据目录，提供确定性登记、健康标记与 Agent 选择。"""

    def __init__(self) -> None:
        self._agents: dict[str, AgentResource] = {}
        self._capabilities: dict[str, CapabilityManifest] = {}
        self._health: dict[str, bool] = {}

    def register_agent(self, profile: AgentProfile) -> AgentResource:
        """登记 AgentProfile 的稳定资源投影；相同描述可重复登记。"""
        agent_id = str(profile.agent_id or profile.agent_name).strip()
        agent_name = str(profile.agent_name).strip()
        domain = str(profile.domain).strip().lower()
        if not agent_id or not agent_name or not domain:
            raise ValueError("agentId, agentName and domain are required")
        metadata = dict(profile.model_extra or {})
        labels = metadata.get("labels", {})
        if not isinstance(labels, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items()):
            raise ValueError("agent labels must be a string mapping")
        resource = AgentResource(
            agent_id=agent_id,
            agent_name=agent_name,
            domain=domain,
            capabilities=tuple(sorted({item.strip().lower() for item in profile.capabilities if item.strip()})),
            version=str(profile.plugin_version or "v1"),
            priority=int(profile.binding_priority),
            enabled=bool(profile.enabled),
            resource_id=(str(metadata["resourceId"]) if metadata.get("resourceId") else None),
            labels=tuple(sorted(labels.items())),
        )
        existing = self._agents.get(agent_id)
        if existing is not None and existing != resource:
            raise ResourceConflictError(f"agent resource conflicts with existing identity: {agent_id}")
        self._agents[agent_id] = resource
        self._health.setdefault(agent_id, True)
        return resource

    def register_capability(self, manifest: CapabilityManifest) -> CapabilityManifest:
        """登记模型、Skill 或 Tool 等能力声明；不同版本覆盖同 ID 会明确失败。"""
        existing = self._capabilities.get(manifest.capability_id)
        if existing is not None and existing != manifest:
            raise ResourceConflictError(
                f"capability resource conflicts with existing identity: {manifest.capability_id}"
            )
        self._capabilities[manifest.capability_id] = manifest
        self._health.setdefault(manifest.capability_id, True)
        return manifest

    def set_health(self, resource_id: str, *, healthy: bool) -> None:
        """标记已登记资源健康状态，未知身份不得被隐式创建。"""
        if resource_id not in self._agents and resource_id not in self._capabilities:
            raise ResourceNotFoundError(f"resource is not registered: {resource_id}")
        self._health[resource_id] = healthy

    def resolve_capability(
        self,
        capability_id: str,
        *,
        kind: CapabilityKind | None = None,
    ) -> CapabilityManifest:
        """按稳定能力标识与可选类别解析健康资源。"""
        manifest = self._capabilities.get(capability_id)
        if manifest is None or not self._health.get(capability_id, True):
            raise ResourceNotFoundError(f"capability resource is not available: {capability_id}")
        if kind is not None and manifest.kind is not kind:
            raise ResourceNotFoundError(
                f"capability resource kind does not match: {capability_id}"
            )
        return manifest

    def resolve_agent(
        self,
        *,
        domain: str,
        agent_name: str | None = None,
        capability: str | None = None,
        allowed_agent_ids: Iterable[str] | None = None,
    ) -> AgentResource:
        """按 scope、健康、精确名称、能力、领域和优先级选择唯一 Agent。"""
        normalized_domain = (domain or "").strip().lower()
        normalized_name = (agent_name or "").strip().lower()
        normalized_capability = (capability or "").strip().lower()
        allowed = {str(item) for item in allowed_agent_ids} if allowed_agent_ids is not None else None
        candidates = [
            item
            for item in self._agents.values()
            if item.enabled and self._health.get(item.agent_id, True)
            and (allowed is None or item.agent_id in allowed)
            and item.domain in (normalized_domain, "general")
        ]
        if normalized_name:
            named = [item for item in candidates if item.agent_name.lower() == normalized_name]
            if named:
                return self._select(named, normalized_domain)
        if normalized_capability:
            capable = [item for item in candidates if normalized_capability in item.capabilities]
            if capable:
                return self._select(capable, normalized_domain)
        raise ResourceNotFoundError(
            f"agent resource not found: domain={domain}, agentName={agent_name}, capability={capability}"
        )

    @staticmethod
    def _select(candidates: list[AgentResource], requested_domain: str) -> AgentResource:
        """将请求领域、优先级和稳定 ID 组成唯一且可预测的选择顺序。"""
        return sorted(
            candidates,
            key=lambda item: (
                0 if item.domain == requested_domain else 1,
                -item.priority,
                item.agent_id,
            ),
        )[0]


__all__ = ["AgentResource", "ResourceConflictError", "ResourceDirectory", "ResourceNotFoundError"]
