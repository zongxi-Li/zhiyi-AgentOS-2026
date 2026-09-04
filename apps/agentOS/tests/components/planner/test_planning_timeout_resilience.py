"""规划期模型调用超时韧性：显式超时预算 + 超时自动重试一次。

历史缺陷（2026-09-01 run_1a25f0d4ad89）：分解器调用沿 provider 默认 120s
读超时走，重型 Mission 的 outline 推理超过 120 秒即 ReadTimeout，且规划器
对超时零重试——一次瞬态超时直接 ``TASK_PLAN_STAGED_FAILED`` 判死整个 Run。

补充缺陷（2026-09-01 run_5c100bb2ec7a）：意图解析器（IntentParser）同样
裸走 120s 默认超时且重试通道也超时——``INTENT_PROFILE_CONTRACT_FAILED``
判死于更早的规划阶段。规划期的每一次模型调用都必须声明预算并具备有界重试。

锁定修复后的合同：
- 分解器与意图解析器发出的每一次模型调用都携带 ``timeout_seconds`` 规划
  预算（默认 480s，构造器可覆盖）；
- 单个调用点超时自动重试一次，并记入 ``last_audit["timeoutRetries"]`` 审计；
- 持续超时不得无限重试：同一调用点最多两次尝试，随后按既有失败路径上抛。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from components.planner.intent_analyzer import IntentParser
from components.planner.task_decomposer import (
    PLANNING_MODEL_TIMEOUT_SECONDS,
    TaskDecomposer,
    TaskDecompositionError,
)
from support.acg.models import (
    ComplexityLevel,
    TaskSemanticProfile,
    build_default_capability_catalog,
)


def _profile() -> TaskSemanticProfile:
    return TaskSemanticProfile(
        primaryGoal="Design the control logic rollout for the IC-200 industrial controller",
        requiredCapabilities=["task_understanding"],
        estimatedComplexity=ComplexityLevel.EXTREME,
        rawIntent="IC-200 controller design",
    )


def _task_row(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": f"Task {key}",
        "objective": f"Resolve the {key} boundary for the controller rollout",
        "capabilityId": "task_understanding",
        "acceptanceCriteria": [f"{key} boundary is explicit and verifiable"],
        "sourceRefs": [],
        "decompositionRationale": f"{key} is a separable deliverable",
    }


class _ScriptedTimeoutLLM:
    """按调用序次编排行为：超时若干次后放行，或一直超时。"""

    def __init__(self, *, timeouts_before_success: int = 0, payload: dict | None = None) -> None:
        self.timeouts_before_success = timeouts_before_success
        self.payload = payload or {}
        self.calls: list[dict] = []
        self.exhausted = False

    def generate_json(self, prompt: str, schema: dict, **kwargs) -> dict:
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        if self.timeouts_before_success <= 0:
            return self.payload
        self.timeouts_before_success -= 1
        raise RuntimeError("Request timed out.")


# --- 超时预算声明 -----------------------------------------------------------


def test_every_model_call_declares_planning_timeout_budget() -> None:
    llm = _ScriptedTimeoutLLM(payload={
        "tasks": [_task_row("understand")],
        "relations": [],
    })
    decomposer = TaskDecomposer(build_default_capability_catalog(), llm)

    decomposer.decompose(
        mission_id="mission_0123456789ab",
        profile=_profile(),
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert llm.calls, "decomposer must issue model calls"
    assert all(
        call.get("timeout_seconds") == PLANNING_MODEL_TIMEOUT_SECONDS
        for call in llm.calls
    ), f"missing planning timeout budget: {llm.calls[0]}"


def test_constructor_overrides_timeout_budget() -> None:
    llm = _ScriptedTimeoutLLM(payload={
        "tasks": [_task_row("understand")],
        "relations": [],
    })
    decomposer = TaskDecomposer(
        build_default_capability_catalog(), llm, model_timeout_seconds=240.0
    )

    decomposer.decompose(
        mission_id="mission_0123456789ab",
        profile=_profile(),
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert all(call.get("timeout_seconds") == 240.0 for call in llm.calls)


# --- 超时自动重试一次 --------------------------------------------------------


def test_timeout_on_first_call_retries_once_and_audits() -> None:
    llm = _ScriptedTimeoutLLM(
        timeouts_before_success=1,
        payload={"tasks": [_task_row("understand")], "relations": []},
    )
    decomposer = TaskDecomposer(build_default_capability_catalog(), llm)

    plan = decomposer.decompose(
        mission_id="mission_0123456789ab",
        profile=_profile(),
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert len(plan.nodes) == 1
    assert len(llm.calls) == 2, "timeout must trigger exactly one retry"
    assert decomposer.last_audit.get("timeoutRetries") == ["decompose"]


def test_staged_path_retries_each_timeout_stage_once() -> None:
    outline_payload = {
        "tasks": [
            {"key": "understand", "title": "Understand", "capabilityId": "task_understanding",
             "logicalRole": "analysis", "sourceRefs": []},
            {"key": "verify", "title": "Verify", "capabilityId": "task_understanding",
             "logicalRole": "verification", "sourceRefs": []},
        ],
    }
    llm = _ScriptedTimeoutLLM()
    decomposer = TaskDecomposer(
        build_default_capability_catalog(), llm, model_timeout_seconds=90.0
    )

    def scripted(prompt: str, schema: dict, **kwargs) -> dict:
        llm.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        if "STAGE OUTLINE" in prompt:
            if not getattr(scripted, "outline_done", False):
                scripted.outline_done = True
                raise RuntimeError("Request timed out.")
            return {"data": outline_payload}
        if "STAGE DETAIL" in prompt:
            if not getattr(scripted, "detail_done", False):
                scripted.detail_done = True
                raise RuntimeError("Request timed out.")
            batch = json.loads(prompt.split("Frozen outline batch: ", 1)[1])
            return {"data": {"tasks": [
                _task_row(item["key"]) | {"capabilityId": item["capabilityId"]}
                for item in batch
            ]}}
        if "STAGE RELATIONS" in prompt:
            if not getattr(scripted, "relations_done", False):
                scripted.relations_done = True
                raise RuntimeError("Request timed out.")
            return {"data": {"relations": [], "controlPolicies": []}}
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")

    llm.generate_json = scripted  # type: ignore[method-assign]

    plan = decomposer.decompose(
        mission_id="mission_0123456789ab",
        profile=_profile(),
        strategy="dynamic_generation",
        task_input={"_effectiveCapabilityProfile": "full"},
        use_llm=True,
    )

    assert {node.key for node in plan.nodes} == {"understand", "verify"}
    assert decomposer.last_audit.get("timeoutRetries") == ["outline", "detail", "relations"]


def test_persistent_timeout_makes_bounded_attempts_then_fails() -> None:
    llm = _ScriptedTimeoutLLM(timeouts_before_success=99)
    decomposer = TaskDecomposer(build_default_capability_catalog(), llm)

    with pytest.raises(TaskDecompositionError):
        decomposer.decompose(
            mission_id="mission_0123456789ab",
            profile=_profile(),
            strategy="dynamic_generation",
            task_input={},
            use_llm=True,
        )

    # 主调用 + 一次重试 + 修复通道同样预算耗尽：不得无限重试。
    assert len(llm.calls) <= 4, f"retry exploded: {len(llm.calls)} calls"
    assert decomposer.last_audit.get("mode") == "failed"


# --- 意图解析器（规划期第一跳）同合同 ----------------------------------------


_PROFILE_PAYLOAD = {
    "primaryGoal": "Design the control logic rollout for the IC-200 industrial controller",
    "requiredCapabilities": ["task_understanding"],
}


def _parser(llm: _ScriptedTimeoutLLM, **kwargs):
    return IntentParser(llm, build_default_capability_catalog(), **kwargs)


def test_intent_parser_declares_planning_timeout_budget() -> None:
    llm = _ScriptedTimeoutLLM(payload=dict(_PROFILE_PAYLOAD))
    parser = _parser(llm)

    parser.parse(intent="为 IC-200 设计控制逻辑上线方案", task_input={}, use_llm=True)

    assert llm.calls, "intent parser must issue model calls"
    assert all(
        call.get("timeout_seconds") == PLANNING_MODEL_TIMEOUT_SECONDS
        for call in llm.calls
    ), f"missing planning timeout budget: {llm.calls[0]}"


def test_intent_parser_retries_once_after_timeout_and_audits() -> None:
    llm = _ScriptedTimeoutLLM(
        timeouts_before_success=1,
        payload=dict(_PROFILE_PAYLOAD),
    )
    parser = _parser(llm)

    profile = parser.parse(intent="为 IC-200 设计控制逻辑上线方案", task_input={}, use_llm=True)

    assert profile.primary_goal
    assert len(llm.calls) == 2, "timeout must trigger exactly one retry"
    assert parser.last_audit.get("timeoutRetries") == ["intent_profile"]


def test_intent_parser_persistent_timeout_fails_bounded() -> None:
    llm = _ScriptedTimeoutLLM(timeouts_before_success=99)
    parser = _parser(llm)

    with pytest.raises(ValueError, match="INTENT_PROFILE_CONTRACT_FAILED"):
        parser.parse(intent="为 IC-200 设计控制逻辑上线方案", task_input={}, use_llm=True)

    # 主调用两次 + 修复通道两次：不得无限重试。
    assert len(llm.calls) <= 4, f"retry exploded: {len(llm.calls)} calls"
    assert parser.last_audit.get("mode") == "failed"
