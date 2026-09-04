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
    return agent, context


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
    assert any("AT LEAST ONE" in prompt for prompt in runtime.prompts), (
        "corrective retry instruction was never issued"
    )
