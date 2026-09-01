"""Deterministic, domain-neutral complexity scoring for planning budgets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from support.acg.models import ComplexityAssessment, ComplexityLevel


DIMENSIONS = (
    "goals_and_artifacts",
    "hard_constraints",
    "evidence_and_tools",
    "cross_stage_dependencies",
    "alternatives_parallel_iteration",
    "risk_and_review",
)


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if item not in (None, "", [], {})]
    return [value] if value not in ("", {}) else []


def _band(count: int, cuts: tuple[int, int, int]) -> int:
    return 0 if count == 0 else 1 if count <= cuts[0] else 2 if count <= cuts[1] else 3


def assess_complexity(
    *,
    intent: str,
    task_input: Mapping[str, Any] | None = None,
    profile_data: Mapping[str, Any] | None = None,
) -> ComplexityAssessment:
    """Score the six published axes; text length is deliberately not an input."""
    payload = dict(task_input or {})
    profile = dict(profile_data or {})
    artifacts = _items(payload.get("expectedArtifacts") or profile.get("expectedArtifacts"))
    constraints = _items(payload.get("constraints") or profile.get("keyConstraints"))
    verification = _items(profile.get("verificationRequirements"))
    capabilities = _items(profile.get("requiredCapabilities"))
    materials = _items(payload.get("sourceMaterials")) + _items(payload.get("materials"))
    lower = (intent or "").lower()

    alternatives = sum(lower.count(term) for term in ("方案", "alternative", "候选", "并行", "迭代", "对比", "比较"))
    risk_terms = sum(lower.count(term) for term in ("风险", "安全", "审计", "审核", "验收", "合规", "risk", "audit", "review"))
    evidence_terms = sum(lower.count(term) for term in ("证据", "数据", "资料", "检索", "计算", "evidence", "source", "metric"))
    external_tool_terms = sum(lower.count(term) for term in ("api", "tool", "工具", "外部检索", "数据库"))

    dimensions = {
        "goals_and_artifacts": _band(1 + len(artifacts), (3, 12, 20)),
        "hard_constraints": _band(len(constraints), (3, 12, 20)),
        "evidence_and_tools": min(3, _band(len(materials) + len(verification) + (1 if evidence_terms >= 2 else 0), (2, 8, 15)) + (1 if external_tool_terms >= 2 else 0)),
        "cross_stage_dependencies": _band(len(capabilities), (4, 12, 20)),
        "alternatives_parallel_iteration": 0 if alternatives == 0 else 1 if alternatives == 1 else 2 if alternatives <= 6 else 3,
        "risk_and_review": 0 if risk_terms == 0 else 1 if risk_terms == 1 else 2 if risk_terms <= 4 else 3,
    }
    score = sum(dimensions.values())
    level = (
        ComplexityLevel.SIMPLE if score <= 4 else
        ComplexityLevel.MEDIUM if score <= 8 else
        ComplexityLevel.COMPLEX if score <= 13 else
        ComplexityLevel.EXTREME
    )
    reasons = [f"{name}={value}" for name, value in dimensions.items()]
    return ComplexityAssessment(level=level, score=score, dimensions=dimensions, reasons=reasons)


PLANNING_BUDGETS = {
    ComplexityLevel.SIMPLE: (3, 6),
    ComplexityLevel.MEDIUM: (6, 12),
    ComplexityLevel.COMPLEX: (12, 24),
    ComplexityLevel.EXTREME: (20, 40),
}

# 规划期模型调用的传输层超时预算。重型 Mission 的意图解析/分阶段 outline 推理
# 常超 2 分钟（provider 客户端默认 120s 读超时不足以覆盖），规划调用必须
# 显式声明更大的每调用预算；该值随调用透传到 provider 连接层。
PLANNING_MODEL_TIMEOUT_SECONDS = 480.0


def is_model_timeout(exc: Exception) -> bool:
    """识别超时类异常（跨层不绑定具体错误类型，按稳定特征识别）。"""
    text = f"{getattr(exc, 'code', '')} {exc}".lower()
    return "timeout" in text or "timed out" in text


__all__ = [
    "DIMENSIONS",
    "PLANNING_BUDGETS",
    "PLANNING_MODEL_TIMEOUT_SECONDS",
    "assess_complexity",
    "is_model_timeout",
]
