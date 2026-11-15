"""外部 Agent 框架的受控 ACG 节点桥接测试。"""

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
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from service.agents.base import AgentProfile, AgentRunContext


class _FrameworkAdapter:
    def __init__(self) -> None:
        self.invocations: list[CapabilityInvocation] = []

    @property
    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            capabilityId="agent.framework.writer",
            kind=CapabilityKind.AGENT,
            displayName="Framework writer",
            framework=AgentFramework.LANGCHAIN,
            capabilities=["writing"],
        )

    async def execute(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
        self.invocations.append(invocation)
        return CapabilityInvocationResult(
            invocationId=invocation.invocation_id,
            success=True,
            output={"answer": "ok"},
            metadata={"summary": "framework result"},
        )


def _context() -> AgentRunContext:
    task = RuntimeMissionRecord(
        missionId="mission_000000000001",
        title="framework",
        intent="write",
        input={"topic": "x"},
    )
    run = RuntimeRunRecord(
        missionId="mission_000000000001",
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
    )
    workflow = WorkflowDefinition(
        workflowId="workflow-1",
        name="workflow",
        domain="general",
        intent="write",
        runtimeEngine="acg",
    )
    step = WorkflowStep(
        stepId="step-1",
        name="write",
        agentName="framework-writer",
        resolvedInput={"style": "brief"},
    )
    return AgentRunContext(
        task=task,
        run=run,
        workflow=workflow,
        step=step,
        memory=[],
        contextPack=ContextPack(
            runId=run.run_id,
            stepId=step.step_id,
            data={"source": "allowed"},
        ),
        commitId="commit:run-1:step-1:0",
    )


def test_framework_agent_remains_a_controlled_acg_node() -> None:
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

    context = _context()
    output = asyncio.run(agent.run(context))

    assert output.output == {"answer": "ok"}
    assert output.summary == "framework result"
    invocation = adapter.invocations[0]
    assert invocation.invocation_id == "commit:run-1:step-1:0"
    assert invocation.input["step"] == {
        "stepId": "step-1",
        "input": {"style": "brief"},
    }
    assert invocation.context == {
        "runId": context.run.run_id,
        "workflowId": "workflow-1",
        "stepId": "step-1",
    }
    assert "checkpoint" not in invocation.input
    assert "memoryStore" not in invocation.input


def test_framework_agent_propagates_cancellation() -> None:
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

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.run(_context()))
