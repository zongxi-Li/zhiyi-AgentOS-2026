"""Deterministic, domain-neutral complexity scoring for planning budgets."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Any, Callable

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
PLANNING_MODEL_TIMEOUT_SECONDS = float(os.getenv("AGENTOS_LLM_PLANNING_TIMEOUT_SECONDS", "480"))
PLANNING_TOTAL_TIMEOUT_SECONDS = float(os.getenv("AGENTOS_LLM_PLANNING_TOTAL_TIMEOUT_SECONDS", "660"))
PLANNING_RETRY_TIMEOUT_SECONDS = 180.0
PLANNING_MAX_RETRIES = min(1, max(0, int(os.getenv("AGENTOS_LLM_PLANNING_MAX_RETRIES", "1"))))


def is_model_timeout(exc: Exception) -> bool:
    """识别超时类异常（跨层不绑定具体错误类型，按稳定特征识别）。"""
    text = f"{getattr(exc, 'code', '')} {exc}".lower()
    return "timeout" in text or "timed out" in text


def transport_error_code(exc: BaseException) -> str | None:
    """Return the stable transport code from a wrapped exception chain."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = str(getattr(current, "code", "") or "").upper()
        if code in {"MODEL_CONNECTION_INTERRUPTED", "MODEL_TIMEOUT"}:
            return code
        text = f"{type(current).__name__} {current}".lower()
        if "timeout" in text or "timed out" in text:
            return "MODEL_TIMEOUT"
        if any(term in text for term in (
            "remoteprotocolerror", "apiconnectionerror", "connecterror",
            "connection error", "server disconnected", "connection reset",
        )):
            return "MODEL_CONNECTION_INTERRUPTED"
        current = current.__cause__ or current.__context__
    return None


def transport_error_metadata(exc: BaseException) -> dict[str, Any]:
    current: BaseException | None = exc
    while current is not None:
        metadata = getattr(current, "metadata", None)
        if isinstance(metadata, Mapping):
            return dict(metadata)
        current = current.__cause__ or current.__context__
    return {}


def call_planning_model(
    llm: Any, *, stage: str, prompt: str, schema: dict[str, Any],
    audit: dict[str, Any], model_timeout_seconds: float,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute one logical planning call inside a shared 660-second deadline."""
    started = monotonic()
    deadline = started + PLANNING_TOTAL_TIMEOUT_SECONDS
    max_attempts = 1 + PLANNING_MAX_RETRIES
    attempts = audit.setdefault("attemptsByStage", {})
    audit.setdefault("transportRetries", [])
    audit["timeoutBudget"] = {
        "initialSeconds": model_timeout_seconds,
        "retrySeconds": PLANNING_RETRY_TIMEOUT_SECONDS,
        "totalSeconds": PLANNING_TOTAL_TIMEOUT_SECONDS,
    }
    for attempt in range(1, max_attempts + 1):
        remaining = max(0.0, deadline - monotonic())
        cap = model_timeout_seconds if attempt == 1 else PLANNING_RETRY_TIMEOUT_SECONDS
        timeout = min(cap, remaining)
        if timeout <= 0:
            error = TimeoutError("planning model total timeout budget exhausted")
            setattr(error, "code", "MODEL_TIMEOUT")
            raise error
        call_kwargs = dict(kwargs)
        call_kwargs["timeout_seconds"] = timeout
        attempts[stage] = attempt
        if progress_callback:
            progress_callback({
                "stage": stage, "status": "started", "attempt": attempt,
                "retryCount": attempt - 1, "timeoutSeconds": timeout,
            })
        try:
            result = llm.generate_json(prompt, schema, **call_kwargs)
            if isinstance(result, Mapping):
                audit["streamUsed"] = bool(result.get("streamUsed", audit.get("streamUsed", False)))
            if progress_callback:
                progress_callback({
                    "stage": stage, "status": "completed", "attempt": attempt,
                    "retryCount": attempt - 1,
                })
            return result
        except Exception as exc:
            code = transport_error_code(exc)
            if code is None or attempt >= max_attempts:
                if code:
                    error_metadata = transport_error_metadata(exc)
                    error_metadata.update({"stage": stage, "attemptCount": attempt, "retryCount": attempt - 1})
                    if hasattr(exc, "metadata"):
                        exc.metadata = error_metadata
                    audit["lastTransportError"] = {
                        "code": code, "stage": stage,
                        **error_metadata,
                    }
                raise
            audit["transportRetries"].append(stage)
            if code == "MODEL_TIMEOUT":
                audit.setdefault("timeoutRetries", []).append(stage)
            audit["lastTransportError"] = {
                "code": code, "stage": stage,
                **transport_error_metadata(exc),
            }
            if progress_callback:
                progress_callback({
                    "stage": stage, "status": "retrying", "attempt": attempt,
                    "retryCount": attempt, "errorCode": code,
                })
    raise AssertionError("unreachable planning retry state")


__all__ = [
    "DIMENSIONS",
    "PLANNING_BUDGETS",
    "PLANNING_MODEL_TIMEOUT_SECONDS",
    "PLANNING_TOTAL_TIMEOUT_SECONDS",
    "PLANNING_MAX_RETRIES",
    "assess_complexity",
    "call_planning_model",
    "is_model_timeout",
    "transport_error_code",
    "transport_error_metadata",
]
