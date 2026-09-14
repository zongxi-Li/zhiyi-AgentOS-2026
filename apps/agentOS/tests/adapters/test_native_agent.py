"""原生 Agent 的外部工具调用合同测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from adapters.model_adapter import StructuredGenerationError, StructuredGenerationResult
from adapters.model.native import NativeGeneralAgent
from components.content import ContentWorksetSession, SQLiteContentManifestStore
from components.communicator.contracts import ContextPack
from contracts.content import ContentKind, WorksetSpec
from contracts.runtime_events import RuntimeEvent
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
        self.providers: list[str | None] = []

    async def execute(self, _name: str, _arguments: dict, **kwargs) -> _SearchResult:
        self.commit_id = kwargs.get("commit_id")
        self.providers.append(kwargs.get("provider"))
        return _SearchResult()


class _GlmModel:
    def describe_model(self):
        return SimpleNamespace(provider="openai-compatible", model="glm-5.3-flash")


class _StreamingUsageModel:
    def __init__(self) -> None:
        self.stream_kwargs: list[dict] = []

    def is_available(self) -> bool:
        return True

    def stream_generate_json(self, **kwargs):
        self.stream_kwargs.append(dict(kwargs))

        async def iterator():
            yield RuntimeEvent(
                eventType="model.started",
                runId="run-stream-usage",
                sequence=1,
                payload={"provider": "glm", "model": "glm-5.3-flash"},
            )
            yield RuntimeEvent(
                eventType="model.completed",
                runId="run-stream-usage",
                sequence=2,
                payload={
                    "data": {
                        "task_summary": "answer",
                        "constraints": [],
                        "success_criteria": [],
                        "assumptions": [],
                        "open_questions": [],
                    },
                    "provider": "glm",
                    "model": "glm-5.3-flash",
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 3,
                        "total_tokens": 15,
                    },
                    "finishReason": "stop",
                    "latencyMs": 17,
                },
            )
        return iterator()


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


class _JsonThenContractRepairModel:
    """Reproduce invalid JSON followed by a valid but incomplete payload."""

    def __init__(self, *, complete_contract_repair: bool = True) -> None:
        self.calls: list[dict] = []
        self.complete_contract_repair = complete_contract_repair

    def is_available(self) -> bool:
        return True

    async def generate_json(self, **kwargs) -> StructuredGenerationResult:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_INVALID_JSON",
                "provider returned invalid JSON",
            )
        if len(self.calls) == 2:
            data = {"solution_design": {"overview": "lightweight option"}}
        elif self.complete_contract_repair:
            data = {
                "solution_design": {
                    "overview": "lightweight option",
                    "phases": [
                        {
                            "name": "pilot",
                            "milestones": ["validated"],
                            "dependencies": ["baseline data"],
                            "deliverables": ["operating rules"],
                        }
                    ],
                }
            }
        else:
            data = {"solution_design": {"overview": "still incomplete"}}
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


def test_native_agent_preserves_stream_usage_and_latency_in_model_invocation_audit() -> None:
    agent = NativeGeneralAgent()
    descriptor = build_default_capability_catalog().get("task_understanding")
    task = RuntimeMissionRecord(missionId="task-stream-usage", title="understand")
    run = RuntimeRunRecord(
        missionId=task.mission_id,
        workflowId="native",
        domain="general",
        runtimeEngine="acg",
    )
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=WorkflowDefinition(
            workflowId="native", name="native", domain="general", runtimeEngine="acg"
        ),
        step=WorkflowStep(
            stepId="understand-stream-usage",
            name="understand",
            agentName=agent.profile.agent_name,
            capability="task_understanding",
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="understand-stream-usage"),
        modelRuntime=_StreamingUsageModel(),
        capabilityDescriptor=descriptor,
        commitId="commit:stream-usage",
    )

    result = asyncio.run(agent.run(context))

    assert result.model_invocations[0]["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    assert result.model_invocations[0]["latencyMs"] == 17
    assert result.model_invocations[0]["finishReason"] == "stop"


def test_native_agent_streams_reasoning_effort_to_model_runtime() -> None:
    """流式执行路径必须把任务声明的 reasoning_effort 一并传给模型运行时。

    历史缺陷：只有非流式回退路径携带该参数，生产流式路径把它丢在调用点。
    """
    agent = NativeGeneralAgent()
    descriptor = build_default_capability_catalog().get("task_understanding")
    model = _StreamingUsageModel()
    task = RuntimeMissionRecord(
        missionId="task-stream-effort", title="understand",
        input={"reasoningEffort": "max"},
    )
    run = RuntimeRunRecord(
        missionId=task.mission_id,
        workflowId="native",
        domain="general",
        runtimeEngine="acg",
    )
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=WorkflowDefinition(
            workflowId="native", name="native", domain="general", runtimeEngine="acg"
        ),
        step=WorkflowStep(
            stepId="understand-stream-effort",
            name="understand",
            agentName=agent.profile.agent_name,
            capability="task_understanding",
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="understand-stream-effort"),
        modelRuntime=model,
        capabilityDescriptor=descriptor,
        commitId="commit:stream-effort",
    )

    asyncio.run(agent.run(context))

    assert model.stream_kwargs, "streaming path was not used"
    assert model.stream_kwargs[0]["reasoning_effort"] == "max"


def test_native_retrieval_forwards_model_provider_to_web_tools() -> None:
    agent = NativeGeneralAgent()
    tool = _SearchTool()
    task = RuntimeMissionRecord(missionId="task-1b", title="retrieve", input={})
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
        modelRuntime=_GlmModel(),
        commitId="commit:run-1b:retrieve:0",
    )

    asyncio.run(agent.run(context))

    assert tool.providers == [None, "glm"]


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
            logicalRole="final_synthesis",
            outputSpec={
                "type": "object",
                "properties": {
                    "artifact": {
                        "type": "object",
                        "properties": {"type": {"type": "string", "enum": ["report"]}},
                    },
                },
            },
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="artifact", evidenceRefs=["source:1"]),
        modelRuntime=model,
        capabilityDescriptor=descriptor,
        commitId="commit:artifact",
    )

    result = asyncio.run(agent.run(context))

    assert len(model.calls) == 5
    # 输出预算不再人为设上限：节点调用不携带 max_output_tokens，输出能力由模型端点决定。
    assert all("max_output_tokens" not in call for call in model.calls)
    assert len(result.output["deliverable"]["sections"]) == 2
    assert "## 第1章" in result.output["final_answer"]
    assert "完整内容 2" in result.output["artifact"]["content"]
    assert result.output["artifact"]["artifactKey"] == "final"
    assert result.output["artifact"]["artifactType"] == "run_deliverable"
    assert result.output["artifact"]["metadata"]["logicalRole"] == "final_synthesis"
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


def test_invalid_json_repair_does_not_consume_contract_repair() -> None:
    agent = NativeGeneralAgent()
    model = _JsonThenContractRepairModel()
    descriptor = build_default_capability_catalog().get("solution_design")
    task = RuntimeMissionRecord(
        missionId="task-json-contract-repair",
        title="design a lightweight option",
    )
    run = RuntimeRunRecord(
        missionId=task.mission_id,
        workflowId="native",
        domain="general",
        runtimeEngine="acg",
    )
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=WorkflowDefinition(
            workflowId="native",
            name="native",
            domain="general",
            runtimeEngine="acg",
        ),
        step=WorkflowStep(
            stepId="design",
            name="design",
            agentName=agent.profile.agent_name,
            capability="solution_design",
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="design"),
        modelRuntime=model,
        capabilityDescriptor=descriptor,
        commitId="commit:json-contract-repair",
    )

    result = asyncio.run(agent.run(context))

    assert len(model.calls) == 3
    assert model.calls[1]["prompt_version"].endswith(".json-repair1")
    assert model.calls[2]["prompt_version"].endswith(".repair1")
    assert result.output["solution_design"]["phases"][0]["name"] == "pilot"
    assert len(result.model_invocations) == 2


def test_contract_repair_remains_bounded_after_invalid_json_repair() -> None:
    agent = NativeGeneralAgent()
    model = _JsonThenContractRepairModel(complete_contract_repair=False)
    descriptor = build_default_capability_catalog().get("solution_design")
    task = RuntimeMissionRecord(
        missionId="task-bounded-contract-repair",
        title="design a lightweight option",
    )
    run = RuntimeRunRecord(
        missionId=task.mission_id,
        workflowId="native",
        domain="general",
        runtimeEngine="acg",
    )
    context = AgentRunContext(
        task=task,
        run=run,
        workflow=WorkflowDefinition(
            workflowId="native",
            name="native",
            domain="general",
            runtimeEngine="acg",
        ),
        step=WorkflowStep(
            stepId="design",
            name="design",
            agentName=agent.profile.agent_name,
            capability="solution_design",
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="design"),
        modelRuntime=model,
        capabilityDescriptor=descriptor,
        commitId="commit:bounded-contract-repair",
    )

    with pytest.raises(StructuredGenerationError) as error:
        asyncio.run(agent.run(context))

    assert error.value.code == "OUTPUT_CONTRACT_VIOLATION"
    assert len(model.calls) == 3
