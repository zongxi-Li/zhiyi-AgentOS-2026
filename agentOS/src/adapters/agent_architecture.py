"""各类智能体架构与框架映射到 AgentOS 的协议边界。"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from adapters.registry import CapabilityRegistry
from contracts.capability import (
    CapabilityInvocation,
    CapabilityInvocationResult,
    CapabilityKind,
    CapabilityManifest,
)
from service.agents.base import AgentOutput, AgentProfile, AgentRunContext, BaseAgent


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


class AgentFrameworkError(RuntimeError):
    """表示框架适配结果不满足 AgentOS 受控节点合同。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FrameworkAgent(BaseAgent):
    """将已注册外部框架适配器限制为一个 AgentOS ACG 节点。

    这个桥接器没有图、检查点、状态或调度 API。ACGNodeRunner 仍负责装配通信与记忆、
    调用本 ``run`` 方法、校验输出、审计并提交结果。外部框架只能处理当前节点已获准
    的输入，而不能继续创建子图或访问其他步骤的完整输出。
    """

    def __init__(
        self,
        *,
        profile: AgentProfile,
        capability_id: str,
        registry: AgentArchitectureRegistry,
    ) -> None:
        super().__init__(profile)
        self._capability_id = capability_id.strip()
        self._registry = registry
        if not self._capability_id:
            raise ValueError("AGENT_CAPABILITY_REQUIRED: capability_id is required")

    async def run(self, context: AgentRunContext) -> AgentOutput:
        """调用已冻结框架能力并把其结果映射为原生 AgentOutput。"""
        adapter = self._registry.resolve(self._capability_id)
        invocation_id = context.commit_id or (
            f"agent:{context.run.run_id}:{context.step.step_id}:{context.step.attempt}"
        )
        invocation = CapabilityInvocation(
            invocationId=invocation_id,
            capabilityId=self._capability_id,
            input=self._input_for(context),
            context={
                "runId": context.run.run_id,
                "workflowId": context.workflow.workflow_id,
                "stepId": context.step.step_id,
            },
            options={"commitId": context.commit_id} if context.commit_id else {},
        )
        try:
            result = await adapter.execute(invocation)
        except asyncio.CancelledError:
            # 客户端取消必须跨越框架桥接直接抵达底层任务，不能被转成正常 Agent 输出。
            raise
        except Exception as exc:
            raise AgentFrameworkError(
                "AGENT_FRAMEWORK_FAILED", "external agent framework invocation failed"
            ) from exc
        if result.invocation_id != invocation_id:
            raise AgentFrameworkError(
                "AGENT_RESULT_INVALID", "external agent framework returned a mismatched invocation"
            )
        if not result.success:
            code = self._error_code(result.error)
            raise AgentFrameworkError(code, "external agent framework reported failure")
        return AgentOutput(
            output=dict(result.output),
            summary=self._summary(result.metadata),
        )

    @staticmethod
    def _input_for(context: AgentRunContext) -> dict[str, Any]:
        """从节点上下文构建最小调用载荷，不传递执行器、MemoryStore 或工具对象。"""
        pack = context.context_pack
        pack_data = getattr(pack, "data", {}) if pack is not None else {}
        evidence_refs = getattr(pack, "evidence_refs", []) if pack is not None else []
        return {
            "task": {
                "taskId": context.task.task_id,
                "intent": context.task.intent,
                "input": dict(context.task.input),
            },
            "step": {
                "stepId": context.step.step_id,
                "input": dict(context.step.resolved_input),
            },
            "context": {
                "data": dict(pack_data) if isinstance(pack_data, dict) else {},
                "evidenceRefs": list(evidence_refs) if isinstance(evidence_refs, list) else [],
            },
        }

    @staticmethod
    def _summary(metadata: dict[str, Any]) -> str:
        """只接受短文本摘要，防止外部扩展元数据混入 AgentOS 输出。"""
        summary = metadata.get("summary") if isinstance(metadata, dict) else None
        return summary if isinstance(summary, str) else ""

    @staticmethod
    def _error_code(error: object) -> str:
        """从框架错误投影稳定代码，未知或不可信值统一收敛。"""
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, str) and code.strip():
                return code.strip()
        return "AGENT_FRAMEWORK_FAILED"


__all__ = [
    "AgentArchitectureAdapter",
    "AgentArchitectureRegistry",
    "AgentFrameworkError",
    "FrameworkAgent",
]
