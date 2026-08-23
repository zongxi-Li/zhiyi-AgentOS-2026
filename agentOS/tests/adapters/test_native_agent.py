"""原生 Agent 的外部工具调用合同测试。"""

from __future__ import annotations

import asyncio

from adapters.model_adapter import StructuredGenerationResult
from adapters.model.native import NativeGeneralAgent
from components.communicator.contracts import ContextPack
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from service.agents import AgentRunContext
from support.acg.models import build_default_capability_catalog


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


class _OversizedTextArrayModel:
    """模拟供应商忽略 JSON Schema ``maxItems`` 的有效 JSON 响应。"""

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def generate_json(self, **_kwargs) -> StructuredGenerationResult:
        self.calls += 1
        return StructuredGenerationResult(
            data={
                "task_summary": "理解任务",
                "constraints": [],
                "success_criteria": [],
                "assumptions": [f"假设 {index}" for index in range(20)],
                "open_questions": [],
            },
            provider="test",
            model="test",
        )


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


def test_native_agent_losslessly_bounds_provider_text_arrays() -> None:
    """供应商忽略 maxItems 时，Native 边界应保留原文并产出合法合同。"""
    agent = NativeGeneralAgent()
    model = _OversizedTextArrayModel()
    descriptor = build_default_capability_catalog().get("task_understanding")
    task = RuntimeMissionRecord(missionId="task-2", title="understand")
    run = RuntimeRunRecord(
        missionId=task.mission_id,
        workflowId="native",
        domain="general",
        runtimeEngine="acg",
    )
    workflow = WorkflowDefinition(
        workflowId="native",
        name="native",
        domain="general",
        runtimeEngine="acg",
    )
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=workflow,
        step=WorkflowStep(
            stepId="understand",
            name="understand",
            agentName=agent.profile.agent_name,
            capability="task_understanding",
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="understand"),
        modelRuntime=model,
        capabilityDescriptor=descriptor,
        commitId="commit:run-2:understand:0",
    )

    result = asyncio.run(agent.run(context))

    assert model.calls == 1
    assert len(result.output["assumptions"]) == 12
    assert "\n".join(result.output["assumptions"]) == "\n".join(
        f"假设 {index}" for index in range(20)
    )
