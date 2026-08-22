"""原生 Agent 的外部工具调用合同测试。"""

from __future__ import annotations

import asyncio

from adapters.model.native import NativeGeneralAgent
from components.communicator.contracts import ContextPack
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from service.agents import AgentRunContext


class _SearchResult:
    """提供原生检索 Agent 所需的最小工具响应。"""

    text = '{"ok": true, "data": {"results": []}}'
    sources: list[object] = []
    tool_executions: list[object] = []


class _SearchTool:
    """记录 NativeGeneralAgent 传入的稳定工具提交标识。"""

    def __init__(self) -> None:
        self.commit_id: str | None = None

    async def execute(self, _name: str, _arguments: dict, **kwargs) -> _SearchResult:
        self.commit_id = kwargs.get("commit_id")
        return _SearchResult()


def test_native_retrieval_forwards_snake_case_commit_id() -> None:
    """原生检索必须与工具保护层使用同一 ``commit_id`` 参数名。"""
    agent = NativeGeneralAgent()
    tool = _SearchTool()
    task = RuntimeMissionRecord(missionId="task-1", title="retrieve")
    run = RuntimeRunRecord(missionId=task.mission_id, workflowId="native", domain="general", runtimeEngine="acg")
    workflow = WorkflowDefinition(workflowId="native", name="native", domain="general", runtimeEngine="acg")
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=workflow,
        step=WorkflowStep(stepId="retrieve", name="retrieve", agentName=agent.profile.agent_name, capability="information_retrieval"),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="retrieve"),
        toolRuntime=tool,
        commitId="commit:run-1:retrieve:0",
    )

    asyncio.run(agent.run(context))

    assert tool.commit_id == "commit:run-1:retrieve:0"
