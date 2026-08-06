"""仅以 AgentRegistry 快照为依据解析确定性的执行绑定。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from support.agents.registry import AgentNotFound
from contracts.workflow import utc_now
from components.recovery.runtime_recovery.constants import (
    MAX_BINDING_SWITCHES_PER_NODE,
    MAX_SAME_BINDING_RETRIES,
)
from components.recovery.runtime_recovery.events import stable_hash


class BindingType(str, Enum):
    """执行绑定粒度：仅 Agent 或 Agent 与模型的组合。"""
    AGENT = "AGENT"
    AGENT_MODEL = "AGENT_MODEL"


class ExecutionBinding(BaseModel):
    """冻结一个候选执行绑定的身份、能力、权限和来源元数据。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    binding_id: str = Field(alias="bindingId")
    agent_name: str = Field(alias="agentName")
    agent_id: str = Field(default="", alias="agentId")
    domain: str
    capability: str
    model_name: str = Field(default="", alias="modelName")
    allowed_skills: list[str] = Field(default_factory=list, alias="allowedSkills")
    allowed_tools: list[str] = Field(default_factory=list, alias="allowedTools")
    binding_type: BindingType = Field(default=BindingType.AGENT, alias="bindingType")
    source: str = "native"
    plugin_id: str | None = Field(default=None, alias="pluginId")
    plugin_version: str | None = Field(default=None, alias="pluginVersion")
    contribution_id: str | None = Field(default=None, alias="contributionId")
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_agent(cls, agent, *, capability: str, registration_order: int):
        """从注册 Agent 构建稳定绑定标识；只读取画像，复杂度为技能与工具列表长度 O(n)。"""
        profile = agent.profile
        agent_id = str(profile.agent_id or profile.agent_name)
        model_name = str(profile.model_name or "")
        key = stable_hash(
            profile.agent_name.strip().lower(),
            agent_id.strip().lower(),
            model_name.strip().lower(),
            capability.strip().lower(),
        )
        return cls(
            bindingId=f"binding_{key[:24]}",
            agentName=profile.agent_name,
            agentId=agent_id,
            domain=profile.domain,
            capability=capability,
            modelName=model_name,
            allowedSkills=list(dict.fromkeys(profile.allowed_skills)),
            allowedTools=list(dict.fromkeys(profile.allowed_tools)),
            bindingType=BindingType.AGENT_MODEL if model_name else BindingType.AGENT,
            priority=profile.binding_priority,
            source=profile.source,
            pluginId=profile.plugin_id,
            pluginVersion=profile.plugin_version,
            contributionId=profile.contribution_id or profile.agent_name,
            metadata={"registrationOrder": registration_order},
        )


class BindingHistoryRecord(BaseModel):
    """记录节点一次绑定选择及其被替代时间，供恢复审计和重放使用。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    binding_id: str = Field(alias="bindingId")
    selected_at_graph_version: int = Field(alias="selectedAtGraphVersion")
    source_event_id: str | None = Field(default=None, alias="sourceEventId")
    source_patch_id: str | None = Field(default=None, alias="sourcePatchId")
    reason_code: str = Field(default="INITIAL_BINDING", alias="reasonCode")
    selected_at: datetime = Field(default_factory=utc_now, alias="selectedAt")
    superseded_at: datetime | None = Field(default=None, alias="supersededAt")


class BindingAvailabilityProvider(Protocol):
    """定义检查绑定当前可用性的只读边界。"""

    def is_available(self, binding: ExecutionBinding) -> bool:
        """返回绑定是否可执行；实现不得修改绑定或运行图。"""
        ...


class RegistryBindingAvailabilityProvider:
    """通过 Agent 注册表查询绑定可用性，不缓存或修改注册表。"""
    def __init__(self, agent_registry) -> None:
        self.agent_registry = agent_registry

    def is_available(self, binding: ExecutionBinding) -> bool:
        """解析相同领域、名称和能力的 Agent；缺失时返回假而非泄漏 ``KeyError``。"""
        try:
            agent = self.agent_registry.resolve(
                domain=binding.domain,
                agent_name=binding.agent_name,
                capability=binding.capability,
            )
        except KeyError:
            return False
        return bool(agent.profile.enabled)


class CandidateResolver:
    """以稳定顺序解析所有已登记、兼容且可用的执行绑定。"""

    def __init__(self, agent_registry, availability_provider=None) -> None:
        self.agent_registry = agent_registry
        self.availability_provider = availability_provider or RegistryBindingAvailabilityProvider(
            agent_registry
        )

    def resolve_candidates(
        self,
        *,
        domain: str,
        capability: str,
        required_skills: list[str] | None = None,
        excluded_binding_ids: list[str] | None = None,
        allowed_agent_ids: list[str] | tuple[str, ...] | None = None,
    ) -> list[ExecutionBinding]:
        """按领域、能力、技能、排除集和允许 Agent 范围筛选候选。

        返回优先级与注册顺序确定的副本列表；不改变注册表，复杂度为 Agent 数量
        乘以其能力与技能集合大小 O(n)，可用性提供方异常由其实现自行定义。
        """
        normalized_domain = domain.strip().lower()
        normalized_capability = capability.strip().lower()
        required = {item.strip().lower() for item in (required_skills or []) if item.strip()}
        excluded = set(excluded_binding_ids or [])
        bindings: list[ExecutionBinding] = []
        for order, agent in enumerate(self.agent_registry.all()):
            profile = agent.profile
            if (
                allowed_agent_ids is not None
                and self.agent_registry.agent_id(agent) not in set(allowed_agent_ids)
            ):
                continue
            if profile.domain.strip().lower() != normalized_domain:
                continue
            capabilities = {item.strip().lower() for item in profile.capabilities}
            if normalized_capability not in capabilities:
                continue
            allowed = {item.strip().lower() for item in profile.allowed_skills}
            if not required.issubset(allowed):
                continue
            binding = ExecutionBinding.from_agent(
                agent, capability=capability, registration_order=order
            )
            if binding.binding_id in excluded or not self.availability_provider.is_available(binding):
                continue
            bindings.append(binding)
        return sorted(
            bindings,
            key=lambda item: (
                -item.priority,
                int(item.metadata.get("registrationOrder", 0)),
                item.binding_id,
            ),
        )

    def resolve(
        self,
        *,
        domain: str,
        capability: str,
        allowed_agent_ids: list[str] | tuple[str, ...] | None = None,
    ):
        """返回最佳候选绑定；没有候选时抛出 ``AgentNotFound``。"""
        candidates = self.resolve_candidates(
            domain=domain,
            capability=capability,
            allowed_agent_ids=allowed_agent_ids,
        )
        if not candidates:
            raise AgentNotFound(f"no binding candidate: {domain}/{capability}")
        return candidates[0]

    def validate_binding(
        self,
        *,
        domain: str,
        capability: str,
        required_skills: list[str] | None,
        binding: ExecutionBinding | dict[str, Any],
        allowed_agent_ids: list[str] | tuple[str, ...] | None = None,
    ) -> bool:
        """验证给定绑定仍在当前候选集中，输入模型不合法时抛出校验错误。"""
        expected = ExecutionBinding.model_validate(binding)
        candidates = self.resolve_candidates(
            domain=domain,
            capability=capability,
            required_skills=required_skills,
            allowed_agent_ids=allowed_agent_ids,
        )
        return any(item.binding_id == expected.binding_id for item in candidates)


__all__ = [
    "BindingAvailabilityProvider",
    "BindingHistoryRecord",
    "BindingType",
    "CandidateResolver",
    "ExecutionBinding",
    "MAX_BINDING_SWITCHES_PER_NODE",
    "MAX_SAME_BINDING_RETRIES",
    "RegistryBindingAvailabilityProvider",
]
