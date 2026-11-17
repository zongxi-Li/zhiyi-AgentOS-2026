"""L4 自愈阶梯的回归测试：workset 边界、空拆分纠偏与兜底。

历史缺陷（mission_a2da5f8d46e4）：
1. workset 分片单元内部发生 ``MODEL_OUTPUT_EXHAUSTED`` 时，语义子任务拆分先于
   外层材料二分被触发；拆分返回空列表抛出 ``MODEL_OUTPUT_NO_PROGRESS``，
   外层只认 EXHAUSTED——材料二分永远没有机会执行，整条运行被误杀。
2. 拆分合同允许 ``{"subtasks": []}``：schema 未声明 minItems，空拆分在合同层
   合法通过后才被业务代码判死。

锁定修复后的合同：
- workset 边界内的 EXHAUSTED 必须原样上抛给外层二分，不得触发内层语义拆分；
- 空拆分必须先做一次带明确指令的纠偏重试，仍为空才允许上报 NO_PROGRESS。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from adapters.model_adapter import StructuredGenerationError, StructuredGenerationResult
from adapters.model.native import NativeGeneralAgent
from components.communicator.contracts import ContextPack
from support.acg.models import build_default_capability_catalog
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from service.agents import AgentRunContext


class _ScriptedRuntime:
    """按脚本回放的假模型运行时；记录每一次收到的 prompt。"""

    def __init__(self, script):
        self.script = list(script)
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    async def generate_json(self, *, prompt: str, **_kwargs) -> StructuredGenerationResult:
        self.prompts.append(prompt)
        if self.script:
            kind, payload = self.script.pop(0)
        else:
            # 脚本耗尽后的安全默认：返回可合并的最小合规输出，避免队列错位时
            # 用无关异常掩盖断言目标。
            kind, payload = "ok", {"summary": f"tail-{len(self.prompts)}"}
        if kind == "exhausted":
            raise StructuredGenerationError(
                "MODEL_OUTPUT_EXHAUSTED",
                "capacity",
                audit={"finishReason": "length", "outputExhausted": True, "usage": {}},
            )
        if kind == "invalid_json":
            raise StructuredGenerationError(
                "MODEL_OUTPUT_INVALID_JSON", "invalid JSON",
                audit={"candidateFingerprint": payload, "provider": "test", "model": "test"},
            )
        return StructuredGenerationResult(data=payload, provider="test", model="test")


def _context(*, capability: str | None = None, pack_data: dict | None = None,
             runtime=None) -> tuple[NativeGeneralAgent, AgentRunContext]:
    cap_id = capability or "task_understanding"
    agent = NativeGeneralAgent()
    task = RuntimeMissionRecord(missionId="task-ladder", title="ladder probe")
    run = RuntimeRunRecord(
        missionId=task.mission_id, workflowId="native", domain="general", runtimeEngine="acg"
    )
    workflow = WorkflowDefinition(workflowId="native", name="native", domain="general", runtimeEngine="acg")
    return agent, AgentRunContext(
        task=task,
        run=run,
        workflow=workflow,
        step=WorkflowStep(
            stepId="analysis",
            name="analysis",
            agentName=agent.profile.agent_name,
            capability=cap_id,
        ),
        memory=[],
        contextPack=ContextPack(runId=run.run_id, stepId="analysis", data=dict(pack_data or {})),
        modelRuntime=runtime,
        capabilityDescriptor=build_default_capability_catalog().get(cap_id),
        commitId="commit:task-ladder:analysis:0",
    )


def test_workset_boundary_defers_exhausted_to_outer_bisection() -> None:
    """边界内的超限必须原样上抛（外层二分接管），绝不允许内层语义拆分截胡。"""
    # 永远返回截断错误：若修复正确，只有原始生成这一次调用。
    runtime = _ScriptedRuntime([("exhausted", None)])
    agent, context = _context(pack_data={"recoveryBoundary": "workset"}, runtime=runtime)

    raised = None
    try:
        asyncio.run(agent.run(context))
    except StructuredGenerationError as exc:
        raised = exc

    assert raised is not None, "expected exhaustion to propagate out of workset unit"
    assert raised.code == "MODEL_OUTPUT_EXHAUSTED", (
        f"inner recovery hijacked the exhaustion: code={raised.code} message={raised}"
    )
    assert len(runtime.prompts) == 1, (
        "semantic subtask-split ran inside a workset-bounded unit; "
        f"prompts={len(runtime.prompts)}"
    )


def test_empty_split_gets_corrective_retry_before_no_progress() -> None:
    """空拆分先用纠偏指令重试一次；仍为空才允许上报无进展。"""
    runtime = _ScriptedRuntime([
        ("ok", {"subtasks": []}),                                   # 第一次拆分：空（历史死穴）
        ("ok", {"subtasks": [                                       # 纠偏重试：给出拆分
            {"title": "A", "goal": "do A", "sourceScope": ["a"]},
        ]}),
        ("ok", {"summary": "part-A"}),                              # 子任务执行
        ("ok", {"summary": "merged"}),                              # 归并
    ])
    agent, context = _context(runtime=runtime)

    recovered = asyncio.run(agent._recover_capability_by_subtasks(
        context=context,
        runtime=runtime,
        original_prompt="produce the report",
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
        thinking_mode="disabled",
        timeout_seconds=30.0,
        prompt_version="probe.v1",
        exhausted_audit={"finishReason": "length"},
    ))

    output, _audits = recovered
    assert output.get("summary"), f"expected recovered output, got {output!r}"
    assert any('"operation":"capacity_split_repair"' in prompt for prompt in runtime.prompts), (
        "structured corrective retry operation was never issued"
    )


def test_plain_json_correction_continues_for_distinct_candidates() -> None:
    runtime = _ScriptedRuntime([
        *[("invalid_json", f"{index:064x}") for index in range(5)],
        ("ok", {"task_summary": "accepted", "constraints": []}),
    ])
    agent, context = _context(runtime=runtime)

    result = asyncio.run(agent.run(context))

    assert result.output["task_summary"] == "accepted"
    assert len(runtime.prompts) == len(result.model_invocations) == 6
    assert all(item["effectiveReason"] == "invalid_json_before_repair"
               for item in result.model_invocations[:-1])


def test_plain_json_correction_stops_on_the_same_invalid_candidate() -> None:
    runtime = _ScriptedRuntime([("invalid_json", "a" * 64)] * 2)
    agent, context = _context(runtime=runtime)

    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(agent.run(context))

    assert caught.value.code == "AGENT_NO_PROGRESS"
    assert len(runtime.prompts) == 2
    assert len(caught.value.audit["modelInvocations"]) == 2


def test_plain_contract_correction_can_exceed_the_old_single_repair_limit() -> None:
    runtime = _ScriptedRuntime([
        *[("ok", {"task_summary": {"correction": index}, "constraints": []}) for index in range(5)],
        ("ok", {"task_summary": "accepted", "constraints": []}),
    ])
    agent, context = _context(runtime=runtime)

    result = asyncio.run(agent.run(context))

    assert result.output["task_summary"] == "accepted"
    assert len(runtime.prompts) == len(result.model_invocations) == 6
    assert all(item["effectiveReason"] == "retry_contract_repair"
               for item in result.model_invocations[1:])


def test_semantic_recovery_can_deepen_past_the_old_eight_level_limit() -> None:
    script = []
    for index in range(12):
        script.append(("ok", {"subtasks": [{"title": f"part {index}", "goal": f"goal {index}",
                                            "sourceScope": [f"scope {index}"]}]}))
        script.append(("exhausted", None) if index < 11 else ("ok", {"summary": "accepted"}))
    runtime = _ScriptedRuntime(script)
    agent, context = _context(runtime=runtime)

    output, _ = asyncio.run(agent._recover_capability_by_subtasks(
        context=context, runtime=runtime, original_prompt="root request",
        output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        thinking_mode="disabled", timeout_seconds=30, prompt_version="deep.v1", exhausted_audit={},
    ))

    assert output["summary"] == "accepted"
    assert len(runtime.prompts) == 24


def test_semantic_recovery_stops_repeated_goal_and_scope_even_if_the_title_changes() -> None:
    runtime = _ScriptedRuntime([
        ("ok", {"subtasks": [{"title": title, "goal": "same goal", "sourceScope": ["same source"]}]})
        if index % 2 == 0 else ("exhausted", None)
        for index, title in enumerate(("first", "", "renamed", ""))
    ])
    agent, context = _context(runtime=runtime)

    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(agent._recover_capability_by_subtasks(
            context=context, runtime=runtime, original_prompt="root request", output_schema={"type": "object"},
            thinking_mode="disabled", timeout_seconds=30, prompt_version="repeat.v1", exhausted_audit={},
        ))

    assert caught.value.code == "MODEL_OUTPUT_NO_PROGRESS"
    assert len(runtime.prompts) == 4


def test_artifact_recovery_can_deepen_past_the_old_eight_level_limit() -> None:
    script = []
    for index in range(1, 12):
        script.extend([("exhausted", None), ("ok", {"sections": [{
            "title": f"section {index}", "goal": f"goal {index}", "sourceFields": [f"field {index}"],
        }]})])
    script.append(("ok", {"title": "accepted", "content": "complete", "sourceFields": ["field 11"]}))
    runtime = _ScriptedRuntime(script)
    agent, context = _context(runtime=runtime)

    output, _ = asyncio.run(agent._generate_artifact_section(
        context=context, runtime=runtime, original_prompt="root request",
        section={"title": "root", "goal": "goal 0", "sourceFields": ["field 0"]},
        thinking_mode="disabled", timeout_seconds=30, prompt_version="deep.v1", path="root",
    ))

    assert output[0]["content"] == "complete"
    assert len(runtime.prompts) == 23


def test_artifact_recovery_stops_repeated_goal_and_source_fields() -> None:
    runtime = _ScriptedRuntime([("exhausted", None), ("ok", {"sections": [{
        "title": "renamed", "goal": "same goal", "sourceFields": ["same source"],
    }]})])
    agent, context = _context(runtime=runtime)

    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(agent._generate_artifact_section(
            context=context, runtime=runtime, original_prompt="root request",
            section={"title": "root", "goal": "same goal", "sourceFields": ["same source"]},
            thinking_mode="disabled", timeout_seconds=30, prompt_version="repeat.v1", path="root",
        ))

    assert caught.value.code == "MODEL_OUTPUT_NO_PROGRESS"
    assert len(runtime.prompts) == 2


def test_full_text_retrieval_extracts_all_discovered_urls() -> None:
    class Tools:
        extracted_urls = []

        async def execute(self, name, arguments, **kwargs):
            rows = []
            if name == "web_search":
                rows = [{"url": f"https://example.org/{index}", "snippet": f"source {index}"}
                        for index in range(7)]
            elif name == "web_extract":
                self.extracted_urls = arguments["urls"]
                rows = [{"content": f"complete {url}"} for url in arguments["urls"]]
            sources = [] if name == "knowledge_search" else [SimpleNamespace(
                citation_id="web:source", public_dict=lambda: {"citationId": "web:source"},
            )]
            return SimpleNamespace(text=json.dumps({"ok": True, "data": {"results": rows}}),
                                   sources=sources, tool_executions=[])

    agent, context = _context(capability="information_retrieval")
    context.run.acg_blueprint = {"metadata": {"webExtraction": "full_text"}}
    context.tool_runtime = tools = Tools()

    output = asyncio.run(agent.run(context))

    assert tools.extracted_urls == [f"https://example.org/{index}" for index in range(7)]
    assert sum(item.startswith("complete ") for item in output.output["retrieved_information"]) == 7


def test_requested_industrial_calculations_are_all_executed() -> None:
    class Tools:
        calls = []

        async def execute(self, name, arguments, **kwargs):
            self.calls.append((name, arguments))
            return SimpleNamespace(text=json.dumps({"ok": True, "data": {"value": arguments["index"]}}),
                                   tool_executions=[])

    runtime = _ScriptedRuntime([("ok", {"task_summary": "accepted", "constraints": []})])
    agent, context = _context(runtime=runtime)
    context.step.capability = "industrial_capacity_analysis"
    context.task.input["industrialCalculations"] = [{"index": index} for index in range(9)]
    context.tool_runtime = tools = Tools()

    asyncio.run(agent.run(context))

    assert tools.calls == [("industrial_calculator", {"index": index}) for index in range(9)]
