"""各类智能体架构与框架映射到 AgentOS 的协议边界。"""

from __future__ import annotations

from typing import Protocol

from contracts.capability import CapabilityInvocation, CapabilityInvocationResult, CapabilityManifest


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
    """为 LangGraph、AutoGen、CrewAI 等框架预留统一解析门面。"""

    def register(self, adapter: AgentArchitectureAdapter) -> None:
        """登记一个智能体架构适配器。

        TODO: 根据 framework、architecture 和版本建立可审计的多实现索引。
        """
        del adapter
        raise NotImplementedError("TODO: 实现智能体架构适配器注册")

    def resolve(self, capability_id: str) -> AgentArchitectureAdapter:
        """按能力标识解析一个框架适配器。

        TODO: 实现框架能力匹配、运行时健康检查及跨框架上下文转换。
        """
        del capability_id
        raise NotImplementedError("TODO: 实现智能体架构适配器解析")


__all__ = ["AgentArchitectureAdapter", "AgentArchitectureRegistry"]
