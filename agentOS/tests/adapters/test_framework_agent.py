"""外部 Agent 框架受控桥接测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.agent_architecture import AgentArchitectureRegistry, FrameworkAgent
from components.communicator.contracts import ContextPack
from contracts.capability import (
    AgentFramework,
    CapabilityInvocation,
    CapabilityInvocationResult,
    CapabilityKind,
    CapabilityManifest,
)
from contracts.workflow import AgentTask, WorkflowDefinition, WorkflowRun, WorkflowStep
from service.agents.base import AgentProfile, AgentRunContext


class _FrameworkAdapter:
    """记录桥接请求，不包含任何执行图对象或运行时状态。"""

    def __init__(self) -> None:
        self.invocations: list[CapabilityInvocation] = []

    @property
    def manifest(self) -> CapabilityManifest:
        """声明一个外部框架 Agent 能力。"""
        return CapabilityManifest(
            capabilityId="agent.framework.writer",
            kind=CapabilityKind.AGENT,
            displayName="Framework writer",
            framework=AgentFramework.LANGCHAIN,
            capabilities=["writing"],
        )

    async def execute(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
        """返回规范输出，外部框架仅是 ACG 节点内部被调用者。"""
        self.invocations.append(invocation)
        return CapabilityInvocationResult(
            invocationId=invocation.invocation_id,
            success=True,
            output={"answer": "ok"},
            metadata={"summary": "framework result"},
        )


def test_framework_agent_uses_registry_as_controlled_acg_node() -> None:
    """桥接 Agent 只接收已装配输入和引用元数据，不能取得或替换 ACG 图。"""
    adapter = _FrameworkAdapter()
    registry = AgentArchitectureRegistry()
    registry.register(adapter)
    agent = FrameworkAgent(
        profile=AgentProfile(
            agentName="framework-writer",
            domain="general",
            capabilities=["writing"],
        ),
        capability_id="agent.framework.writer",
        registry=registry,
    )
    task = AgentTask(taskId="task-1", title="framework", intent="write", input={"topic": "x"})
    run = WorkflowRun(taskId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")
    workflow = WorkflowDefinition(workflowId="workflow-1", name="workflow", domain="general", intent="write", runtimeEngine="acg")
    step = WorkflowStep(stepId="step-1", name="write", agentName="framework-writer", resolvedInput={"style": "brief"})
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=workflow,
        step=step,
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId=step.step_id, data={"source": "allowed"}),
        commitId="commit:run-1:step-1:0",
    )

    output = asyncio.run(agent.run(context))

    assert output.output == {"answer": "ok"}
    assert output.summary == "framework result"
    invocation = adapter.invocations[0]
    assert invocation.invocation_id == "commit:run-1:step-1:0"
    assert invocation.capability_id == "agent.framework.writer"
    assert invocation.input == {
        "task": {"taskId": "task-1", "intent": "write", "input": {"topic": "x"}},
        "step": {"stepId": "step-1", "input": {"style": "brief"}},
        "context": {"data": {"source": "allowed"}, "evidenceRefs": []},
    }
    assert invocation.context == {
        "runId": run.run_id,
        "workflowId": "workflow-1",
        "stepId": "step-1",
    }
    assert invocation.options == {"commitId": "commit:run-1:step-1:0"}


def test_framework_agent_propagates_cancellation_to_external_adapter() -> None:
    """ACG 取消节点时，框架桥接不得把取消改写成框架失败。"""
    class _CancelledAdapter(_FrameworkAdapter):
        async def execute(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
            raise asyncio.CancelledError()

    registry = AgentArchitectureRegistry()
    registry.register(_CancelledAdapter())
    agent = FrameworkAgent(
        profile=AgentProfile(agentName="framework-writer", domain="general"),
        capability_id="agent.framework.writer",
        registry=registry,
    )
    task = AgentTask(taskId="task-1", title="framework")
    run = WorkflowRun(taskId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")
    workflow = WorkflowDefinition(workflowId="workflow-1", name="workflow", domain="general", runtimeEngine="acg")
    step = WorkflowStep(stepId="step-1", name="write", agentName="framework-writer")
    context = AgentRunContext(task=task, run=run, workflow=workflow, step=step, memory=[])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.run(context))
