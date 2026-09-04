"""Planning budget steering: band-aware prompt anchor and audited task counts.

轻量化修复的红绿测试锚点：
1. 分解提示词必须携带复杂度档位的任务数预算区间（替代裸定性放权）；
2. 计划 metadata 必须记录预算三元组（budgetRange/actualTaskCount/withinBudget），
   只观测不拦截；
3. 确定性降级路径不得为凑预算而注水任务数。
"""

from __future__ import annotations

from components.planner.complexity import PLANNING_BUDGETS
from components.planner.task_decomposer import TASK_DECOMPOSITION_PROMPT_VERSION, TaskDecomposer
from support.acg.models import ComplexityLevel, TaskSemanticProfile, build_default_capability_catalog


class _PlanLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def generate_json(self, prompt: str, schema: dict, **kwargs) -> dict:
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        return self.payload


def _profile(level: ComplexityLevel = ComplexityLevel.EXTREME) -> TaskSemanticProfile:
    return TaskSemanticProfile(
        primaryGoal="Produce and compare three independently testable solution candidates",
        requiredCapabilities=["task_understanding"],
        estimatedComplexity=level,
        rawIntent="three alternatives and comparison",
    )


_PAYLOAD = {
    "tasks": [
        {
            "key": "understand",
            "title": "Understand",
            "objective": "Define the mission comparison boundary",
            "capabilityId": "task_understanding",
            "acceptanceCriteria": ["Mission boundary is explicit"],
        }
    ],
    "relations": [],
}


def _budget(level: ComplexityLevel) -> tuple[int, int]:
    lo, hi = PLANNING_BUDGETS[level]
    return int(lo), int(hi)


def test_prompt_injects_band_task_count_range() -> None:
    for level in (ComplexityLevel.COMPLEX, ComplexityLevel.EXTREME):
        lo, hi = _budget(level)
        prompt = TaskDecomposer(build_default_capability_catalog(), None).build_prompt(
            profile=_profile(level),
            task_input={},
        )
        assert f"approximately {lo}-{hi} tasks" in prompt, (
            f"{level.value} prompt must state its planning budget range"
        )
        assert "planning budget" in prompt.lower()
        assert TASK_DECOMPOSITION_PROMPT_VERSION in prompt


def test_model_plan_records_budget_audit_triple() -> None:
    llm = _PlanLLM(_PAYLOAD)
    plan = TaskDecomposer(build_default_capability_catalog(), llm).decompose(
        mission_id="mission_0123456789ab",
        profile=_profile(ComplexityLevel.EXTREME),
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )
    budget = plan.metadata["planningBudget"]
    lo, hi = _budget(ComplexityLevel.EXTREME)
    assert budget["budgetRange"] == [lo, hi]
    assert budget["actualTaskCount"] == len(plan.nodes)
    assert budget["withinBudget"] is (lo <= len(plan.nodes) <= hi)


def test_deterministic_fallback_is_audited_but_not_inflated() -> None:
    plan = TaskDecomposer(build_default_capability_catalog(), None).decompose(
        mission_id="mission_0123456789ab",
        profile=_profile(ComplexityLevel.EXTREME),
        strategy="dynamic_generation",
        task_input={},
        use_llm=False,
    )
    capabilities = set(_profile().required_capabilities)
    # 每个必需能力恰好一个任务：降级路径按能力枚举，不为凑 EXTREME 预算注水。
    assert len(plan.nodes) == len(capabilities)
    assert plan.metadata["degraded"] is True
    budget = plan.metadata["planningBudget"]
    lo, hi = _budget(ComplexityLevel.EXTREME)
    assert budget["budgetRange"] == [lo, hi]
    assert budget["actualTaskCount"] == len(plan.nodes)
    assert budget["withinBudget"] is False
