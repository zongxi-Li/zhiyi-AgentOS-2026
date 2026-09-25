"""EVENT 通信模式的通知引用语义测试。"""

from __future__ import annotations

import asyncio

import pytest

from components.communicator import CommunicatorService
from components.executor.compiler import ACGGraphCompiler
from components.executor.graph import ACGExecutionState
from components.executor.node_runner import ACGNodeRunner
from components.executor.value_store import InMemoryExecutionValueStore
from components.memory import MemoryService
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from support.acg.models import ACGBlueprint, ACGEdge, StepNode
from service.agents.base import AgentOutput, AgentProfile, BaseAgent


class _EventRecordingAgent(BaseAgent):
    """记录收到的 ContextPack，用于确认 EVENT 没有传递上游正文。"""

    def __init__(self) -> None:
        super().__init__(AgentProfile(agentName="event-agent", domain="general"))
        self.context = None

    async def run(self, context):
        self.context = context
        return AgentOutput(output={"received": True}, summary="notified")


def test_event_step_receives_reference_without_upstream_payload() -> None:
    """EVENT 只让消费者知道哪个步骤发生了事件，不可读取其输出正文。"""
    store = InMemoryExecutionValueStore()
    upstream_ref = store.put_output(
        run_id="run-1",
        step_id="source",
        payload={"secret": "must-not-pass"},
    )
    agent = _EventRecordingAgent()
    runner = ACGNodeRunner(
        task=RuntimeMissionRecord(missionId="task-1", title="event"),
        run=RuntimeRunRecord(missionId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg"),
        workflow=WorkflowDefinition(workflowId="workflow-1", name="workflow", domain="general", intent="general", runtimeEngine="acg"),
        steps={"sink": WorkflowStep(stepId="sink", name="sink", agentName="event-agent")},
        agents={"sink": agent},
        communicator=CommunicatorService(run_id="run-1", mission_id="task-1"),
        memory=MemoryService(),
        value_store=store,
        communication_modes={"sink": "EVENT"},
        upstream_step_ids={"sink": ("source",)},
    )

    asyncio.run(runner("sink", ACGExecutionState(runId="run-1", outputRefs={"source": upstream_ref})))

    pack = agent.context.context_pack
    assert pack.data == {}
    assert pack.source_step_ids == ["source"]
    assert pack.evidence_refs == [f"event:{upstream_ref}"]


def test_compiler_rejects_event_step_declaring_input_slots() -> None:
    """EVENT 不能声明 inputSpec.from，否则会变成绕过合同的数据传输通道。"""
    blueprint = ACGBlueprint(
        graphId="event-with-slots",
        nodes=[
            StepNode(nodeId="source", agentName="event-agent"),
            StepNode(
                nodeId="notify",
                agentName="event-agent",
                metadata={"communicationMode": "EVENT"},
                inputSpec={"from": {"source": ["title"]}},
            )
        ],
        edges=[ACGEdge(sourceId="source", targetId="notify")],
    )

    with pytest.raises(ValueError, match="EVENT.*inputSpec.from"):
        ACGGraphCompiler().compile(blueprint)
