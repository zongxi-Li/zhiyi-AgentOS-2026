"""冻结运行范围内的 Agent 调用适配测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.agent_invocation import AgentInvocationAdapter, AgentInvocationError
from components.communicator.contracts import ContextPack
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from service.agents.base import AgentOutput, AgentProfile, AgentRunContext, BaseAgent
from service.agents.registry import AgentRegistry


class _Agent(BaseAgent):
    """返回固定合同输出的测试 Agent。"""

    async def run(self, context: AgentRunContext) -> AgentOutput:
        return AgentOutput(output={"answer": self.profile.agent_name})


def _context(agent_name: str) -> AgentRunContext:
    """构造最小的受控 Agent 调用上下文。"""
    task = RuntimeMissionRecord(missionId="task-1", title="agent invocation")
    run = RuntimeRunRecord(missionId=task.mission_id, workflowId="workflow-1", domain="general", runtimeEngine="acg")
    workflow = WorkflowDefinition(workflowId="workflow-1", name="workflow", domain="general", intent="general", runtimeEngine="acg")
    step = WorkflowStep(stepId="one", name="one", agentName=agent_name)
    return AgentRunContext(task=task, run=run, workflow=workflow, step=step, memory=[], contextPack=ContextPack(runId=run.run_id, stepId="one"))


def test_agent_invoker_rejects_agent_outside_frozen_scope() -> None:
    """未进入执行快照范围的 Agent 必须在真实调用前被适配器阻止。"""
    registry = AgentRegistry()
    registry.register(_Agent(AgentProfile(agentName="allowed-agent", domain="general")))
    invoker = AgentInvocationAdapter(registry=registry.scoped(["allowed-agent"]))

    with pytest.raises(AgentInvocationError, match="not available in run scope") as captured:
        asyncio.run(invoker.invoke(context=_context("blocked-agent")))

    assert captured.value.code == "AGENT_NOT_IN_SCOPE"


def test_agent_invoker_calls_agent_visible_in_frozen_scope() -> None:
    """在冻结 scope 内解析的 Agent 可获得已装配上下文并返回结构化输出。"""
    registry = AgentRegistry()
    registry.register(_Agent(AgentProfile(agentName="allowed-agent", domain="general")))
    invoker = AgentInvocationAdapter(registry=registry.scoped(["allowed-agent"]))

    result = asyncio.run(invoker.invoke(context=_context("allowed-agent")))

    assert result.output == {"answer": "allowed-agent"}


def test_agent_context_accepts_stable_commit_identifier() -> None:
    """执行器必须向 Agent 传递本次步骤尝试的稳定幂等标识。"""
    context = _context("allowed-agent").model_copy(
        update={"commit_id": "commit:run-1:one:0"}
    )

    assert context.commit_id == "commit:run-1:one:0"
