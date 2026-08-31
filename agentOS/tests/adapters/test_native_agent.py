"""原生 Agent 的外部工具调用合同测试。"""

from __future__ import annotations

import asyncio

from adapters.model_adapter import StructuredGenerationError, StructuredGenerationResult
from adapters.model.native import NativeGeneralAgent
from components.content import ContentWorksetSession, SQLiteContentManifestStore
from components.communicator.contracts import ContextPack
from contracts.content import ContentKind, WorksetSpec
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
        self.kwargs: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate_json(self, **_kwargs) -> StructuredGenerationResult:
        self.calls += 1
        self.kwargs.append(dict(_kwargs))
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


class _WorksetModel:
    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def generate_json(self, **_kwargs) -> StructuredGenerationResult:
        self.calls += 1
        return StructuredGenerationResult(
            data={
                "task_summary": f"result-{self.calls}",
                "constraints": [],
                "success_criteria": [],
                "assumptions": [],
                "open_questions": [],
            },
            provider="test",
            model="workset-model",
            usage={"input_tokens": 10, "output_tokens": 4},
        )


class _ArtifactRecoveryModel:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate_json(self, **kwargs) -> StructuredGenerationResult:
        self.calls.append(kwargs)
        call = len(self.calls)
        if call == 1:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_EXHAUSTED",
                "capacity reached",
                audit={
                    "provider": "test", "model": "test", "finishReason": "length",
                    "outputPolicy": "api_controlled", "outputExhausted": True,
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            )
        if call == 2:
            data = {
                "title": "完整报告", "executiveSummary": "摘要",
                "sections": [
                    {"title": "第一章", "goal": "覆盖需求", "sourceFields": ["requirements"]},
                    {"title": "第二章", "goal": "覆盖验证", "sourceFields": ["verification"]},
                ],
                "calculations": [], "assumptions": [], "openQuestions": [],
                "sourceRefs": ["source:1"],
            }
        elif call in {3, 4}:
            index = call - 2
            data = {
                "title": f"第{index}章", "content": f"完整内容 {index}",
                "sourceFields": ["requirements" if index == 1 else "verification"],
            }
        else:
            data = {
                "status": "passed",
                "checks": [{"criterion": "全部覆盖", "result": "通过", "evidence": "source:1"}],
                "unresolvedGaps": [],
            }
        return StructuredGenerationResult(data=data, provider="test", model="test")


class _GenericRecoveryModel:
    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def generate_json(self, **_kwargs) -> StructuredGenerationResult:
        self.calls += 1
        if self.calls == 1:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_EXHAUSTED", "capacity",
                audit={"finishReason": "length", "outputExhausted": True, "usage": {}},
            )
        if self.calls == 2:
            data = {"subtasks": [
                {"title": "A", "goal": "analyze A", "sourceScope": ["a"]},
                {"title": "B", "goal": "analyze B", "sourceScope": ["b"]},
            ]}
        else:
            data = {
                "task_summary": "merged" if self.calls == 5 else f"partial-{self.calls}",
                "constraints": [], "success_criteria": [], "assumptions": [],
                "open_questions": [],
            }
        return StructuredGenerationResult(data=data, provider="test", model="test")


def test_native_retrieval_forwards_snake_case_commit_id() -> None:
    """原生检索必须与工具保护层使用同一 ``commit_id`` 参数名。"""
    agent = NativeGeneralAgent()
    tool = _SearchTool()
    task = RuntimeMissionRecord(
        missionId="task-1", title="retrieve", input={"webSearchEnabled": False}
    )
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
    task = RuntimeMissionRecord(
        missionId="task-2",
        title="understand",
        input={"reasoningEffort": "high"},
    )
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
    assert model.kwargs[0]["reasoning_effort"] == "high"
    assert len(result.output["assumptions"]) == 20
    assert "\n".join(result.output["assumptions"]) == "\n".join(
        f"假设 {index}" for index in range(20)
    )


def test_native_agent_maps_persisted_fragments_and_reduces_as_balanced_tree(tmp_path) -> None:
    store = SQLiteContentManifestStore(tmp_path / "native-workset.sqlite3")
    material = store.create_from_bytes(
        content=b"abcdefghi",
        kind=ContentKind.MATERIAL,
        owner_type="user",
        owner_id="u1",
        max_fragment_bytes=3,
    )
    agent = NativeGeneralAgent()
    model = _WorksetModel()
    descriptor = build_default_capability_catalog().get("task_understanding")
    task = RuntimeMissionRecord(missionId="task-workset", title="understand all material")
    run = RuntimeRunRecord(
        missionId=task.mission_id, workflowId="native", domain="general", runtimeEngine="acg"
    )
    workflow = WorkflowDefinition(
        workflowId="native", name="native", domain="general", runtimeEngine="acg"
    )
    session = ContentWorksetSession(
        store=store,
        spec=WorksetSpec(sourceManifestRefs=[material.manifest_id]),
        run_id=run.run_id,
        step_id="understand",
        commit_id="commit:workset",
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
        contentWorksetSession=session,
        modelRuntime=model,
        capabilityDescriptor=descriptor,
        commitId="commit:workset",
    )

    result = asyncio.run(agent.run(context))

    assert session.result_manifest.fragment_count == 3
    assert session.result_manifest.sealed is True
    assert model.calls == 5  # 3 map calls + 2 pairwise reducer calls
    assert len(result.model_invocations) == 5
    assert "reduced in 2 level(s)" in result.summary


def test_artifact_output_exhaustion_uses_sections_and_deterministic_assembly() -> None:
    agent = NativeGeneralAgent()
    model = _ArtifactRecoveryModel()
    descriptor = build_default_capability_catalog().get("artifact_generation")
    task = RuntimeMissionRecord(
        missionId="task-artifact", title="生成完整报告",
        input={"constraints": ["全部覆盖"], "expectedArtifacts": ["完整报告"]},
    )
    run = RuntimeRunRecord(
        missionId=task.mission_id, workflowId="native", domain="general", runtimeEngine="acg"
    )
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=WorkflowDefinition(
            workflowId="native", name="native", domain="general", runtimeEngine="acg"
        ),
        step=WorkflowStep(
            stepId="artifact", name="artifact", goal="生成完整报告",
            agentName=agent.profile.agent_name, capability="artifact_generation",
            acceptanceCriteria=["全部覆盖"], sourceRefs=["source:1"],
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="artifact", evidenceRefs=["source:1"]),
        modelRuntime=model,
        capabilityDescriptor=descriptor,
        commitId="commit:artifact",
    )

    result = asyncio.run(agent.run(context))

    assert len(model.calls) == 5
    assert all(call["max_output_tokens"] == 65_536 for call in model.calls)
    assert len(result.output["deliverable"]["sections"]) == 2
    assert "## 第1章" in result.output["final_answer"]
    assert "完整内容 2" in result.output["artifact"]["content"]
    assert result.output["verification"]["status"] == "passed"
    assert len(result.model_invocations) == 5


def test_generic_output_exhaustion_decomposes_and_pairwise_reduces() -> None:
    agent = NativeGeneralAgent()
    model = _GenericRecoveryModel()
    descriptor = build_default_capability_catalog().get("task_understanding")
    task = RuntimeMissionRecord(missionId="task-recovery", title="understand a large mission")
    run = RuntimeRunRecord(
        missionId=task.mission_id, workflowId="native", domain="general", runtimeEngine="acg"
    )
    context = AgentRunContext(
        task=task, run=run,
        workflow=WorkflowDefinition(
            workflowId="native", name="native", domain="general", runtimeEngine="acg"
        ),
        step=WorkflowStep(
            stepId="understand", name="understand", agentName=agent.profile.agent_name,
            capability="task_understanding",
        ),
        memory=[], contextPack=ContextPack(runId=run.run_id, stepId="understand"),
        modelRuntime=model, capabilityDescriptor=descriptor, commitId="commit:recovery",
    )

    result = asyncio.run(agent.run(context))

    assert model.calls == 5
    assert result.output["task_summary"] == "merged"
    assert len(result.model_invocations) == 5
    assert result.model_invocations[0]["outputExhausted"] is True
