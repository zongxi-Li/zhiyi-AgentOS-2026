"""各类智能体架构与框架映射到 AgentOS 的协议边界。"""

from __future__ import annotations

from typing import Protocol

from adapters.registry import CapabilityRegistry
from contracts.capability import (
    CapabilityInvocation,
    CapabilityInvocationResult,
    CapabilityKind,
    CapabilityManifest,
)


class AgentArchitectureAdapter(Protocol):
    """定义框架特定智能体运行时对外暴露的统一执行接口。"""

    @property
    def manifest(self) -> CapabilityManifest:
        """返回所适配框架、架构形态和能力范围的声明。"""
        ...

    async def execute(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
        """执行一个单体或多智能体架构调用并返回规范化结果。"""
        ...


class AgentArchitectureRegistry:
    """维护 AgentOS 可调用的 Agent 架构适配器，不创建外部框架运行时。"""

    def __init__(self) -> None:
        self._capabilities: CapabilityRegistry[AgentArchitectureAdapter] = CapabilityRegistry(
            allowed_kinds=(CapabilityKind.AGENT,)
        )

    def register(self, adapter: AgentArchitectureAdapter) -> None:
        """登记 Agent 适配器；相同声明幂等，冲突和类别错误明确拒绝。"""
        self._capabilities.register(adapter)

    def resolve(self, capability_id: str) -> AgentArchitectureAdapter:
        """按能力 ID 解析健康的 Agent 适配器，不做跨框架上下文转换。"""
        return self._capabilities.resolve(capability_id)


__all__ = ["AgentArchitectureAdapter", "AgentArchitectureRegistry"]
