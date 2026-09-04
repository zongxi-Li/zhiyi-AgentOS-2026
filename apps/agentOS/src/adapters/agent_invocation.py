"""冻结执行范围内的 Agent 调用适配器。

节点执行器通过本模块调用 Agent，而不是直接持有任意 Agent 映射。适配器只接受
已经由通信、记忆服务装配完成的 ``AgentRunContext``，负责按 run 的注册表视图解析
目标并归一化“不可见/不存在”错误；它不负责规划 ACG、修改输出或绕过合同写入仓库。
"""

from __future__ import annotations

from typing import Protocol

from service.agents.base import AgentOutput, AgentRunContext, BaseAgent
from service.agents.registry import AgentNotFound


class AgentResolver(Protocol):
    """适配器所需的最小注册表视图，支持全局或冻结 scope 实现。"""

    def resolve(self, domain: str, agent_name: str | None = None, capability: str | None = None) -> BaseAgent:
        """返回 scope 内可用 Agent；不存在或不可见时抛出 ``AgentNotFound``。"""


    def resolve_by_id(self, agent_id: str) -> BaseAgent:
        """Resolve one frozen binding inside the same scope."""


class AgentInvocationError(RuntimeError):
    """把 Agent 解析/调用前边界错误转为稳定、可审计的错误码。"""

    def __init__(self, code: str, step_id: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.step_id = step_id


class AgentInvocationAdapter:
    """使用注入的冻结 Agent 解析器安全调用节点目标。"""

    def __init__(self, *, registry: AgentResolver) -> None:
        self.registry = registry

    async def invoke(self, *, context: AgentRunContext, agent: BaseAgent | None = None) -> AgentOutput:
        """解析当前步骤 Agent 并执行，不可见目标在外部副作用前明确失败。"""
        step = context.step
        try:
            if agent is None:
                agent = self.registry.resolve(
                    domain=context.workflow.domain,
                    agent_name=step.agent_name,
                    capability=step.capability,
                )
            else:
                agent_id = str(agent.profile.agent_id or agent.profile.agent_name)
                agent = self.registry.resolve_by_id(agent_id)
        except (AgentNotFound, KeyError) as exc:
            raise AgentInvocationError(
                "AGENT_NOT_IN_SCOPE",
                step.step_id,
                f"agent {step.agent_name or step.step_id} is not available in run scope",
            ) from exc
        return await agent.run(context)


__all__ = ["AgentInvocationAdapter", "AgentInvocationError"]
