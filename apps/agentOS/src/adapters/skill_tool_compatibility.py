"""Skills、函数工具和 MCP 工具的统一互操作协议边界。"""

from __future__ import annotations

from typing import Protocol

from adapters.registry import CapabilityRegistry
from contracts.capability import (
    CapabilityInvocation,
    CapabilityInvocationResult,
    CapabilityKind,
    CapabilityManifest,
)


class SkillToolAdapter(Protocol):
    """定义本地技能、函数工具、OpenAPI 与 MCP 工具的共同调用接口。"""

    @property
    def manifest(self) -> CapabilityManifest:
        """返回技能或工具的身份、协议、权限与输入输出能力声明。"""
        ...

    async def invoke(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
        """在实现负责的权限和副作用边界内调用目标能力。"""
        ...


class SkillToolCompatibilityRegistry:
    """维护本地技能、函数与工具协议适配器的受限发现入口。"""

    def __init__(self) -> None:
        self._capabilities: CapabilityRegistry[SkillToolAdapter] = CapabilityRegistry(
            allowed_kinds=(CapabilityKind.SKILL, CapabilityKind.TOOL)
        )

    def register(self, adapter: SkillToolAdapter) -> None:
        """登记技能或工具适配器；不同类别不能通过本入口静默伪装。"""
        self._capabilities.register(adapter)

    def resolve(self, capability_id: str) -> SkillToolAdapter:
        """按能力 ID 解析健康适配器；权限和会话仍由调用运行时负责。"""
        return self._capabilities.resolve(capability_id)


__all__ = ["SkillToolAdapter", "SkillToolCompatibilityRegistry"]
