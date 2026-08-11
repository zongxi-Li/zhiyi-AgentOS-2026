"""Skills、函数工具和 MCP 工具的统一互操作协议边界。"""

from __future__ import annotations

from typing import Protocol

from contracts.capability import CapabilityInvocation, CapabilityInvocationResult, CapabilityManifest


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
    """为 Skills 和各类工具协议预留发现、校验和受限调用门面。"""

    def register(self, adapter: SkillToolAdapter) -> None:
        """登记一个技能或工具适配器。

        TODO: 实现 manifest 校验、协议版本协商和命名空间冲突处理。
        """
        del adapter
        raise NotImplementedError("TODO: 实现技能工具适配器注册")

    def resolve(self, capability_id: str) -> SkillToolAdapter:
        """按能力标识解析已登记的技能或工具适配器。

        TODO: 实现权限范围过滤、MCP 会话生命周期与故障隔离。
        """
        del capability_id
        raise NotImplementedError("TODO: 实现技能工具适配器解析")


__all__ = ["SkillToolAdapter", "SkillToolCompatibilityRegistry"]
