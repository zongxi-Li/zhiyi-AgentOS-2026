"""Agent 运行期按需补读上游字段的集成测试。"""

from __future__ import annotations

import asyncio

from components.mission_manager.store import WorkflowRegistry
from contracts.workflow import WorkflowDefinition, WorkflowStatus, WorkflowStepDefinition
from runtime.workflow_runtime import ExecutionRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _Producer(BaseAgent):
    """生成一个用于验证预取与按需补读分离的上游输出。"""

    async def run(self, _context) -> AgentOutput:
        return AgentOutput(output={"title": "brief", "details": "private details"})


class _Consumer(BaseAgent):
    """先消费预取摘要，再通过受控读取器取得所需补充字段。"""

    async def run(self, context) -> AgentOutput:
        extra = await context.communication_reader.read(
            "produce",
            ["details"],
            reason="需要补充事实以完成结论",
        )
        return AgentOutput(output={"answer": f"{context.context_pack.data['title']}:{extra.data['details']}"})


def test_agent_reads_authorized_field_on_demand_without_checkpoint_body() -> None:
    """补读必须经过 Broker，并只把统计和引用投影进 State/Trace。"""
    agents = AgentRegistry()
    agents.register(_Producer(AgentProfile(agentName="produce", domain="general")))
    agents.register(_Consumer(AgentProfile(agentName="consume", domain="general")))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="dynamic-read",
        name="dynamic read",
        domain="general",
        runtimeEngine="acg",
        steps=[
            WorkflowStepDefinition(
                stepId="produce",
                name="produce",
                agentName="produce",
                outputSpec={"type": "object", "properties": {
                    "title": {"type": "string"},
                    "details": {"type": "string"},
                }},
            ),
            WorkflowStepDefinition(
                stepId="consume",
                name="consume",
                agentName="consume",
                input={
                    "from": {"produce": ["title", "details"]},
                    "prefetch": {"produce": ["title"]},
                },
                outputSpec={"type": "object", "properties": {"answer": {"type": "string"}}},
            ),
        ],
    ))
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    )
    task = runtime.create_mission("dynamic", workflow_id="dynamic-read")
    _, run = runtime.prepare_run(task.mission_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    usage = result.execution_state["communicationUsage"]
    assert usage["steps"]["consume"] > 0
    reads = [event for event in result.trace if event.observation == "Broker communication read projected"]
    assert [event.payload["fields"] for event in reads] == [["title"], ["details"]]
    assert "private details" not in str(result.execution_state)
    assert "需要补充事实" not in str([event.payload for event in result.trace])
