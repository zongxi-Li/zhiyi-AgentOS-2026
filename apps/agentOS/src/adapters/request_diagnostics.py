"""Bounded, body-free diagnostics of the messages actually sent to a provider."""
from __future__ import annotations

from typing import Any

from adapters.prompt_runtime import canonical_hash
from components.communicator.contracts import estimate_tokens
from contracts.request_budget import ModelRequestBudget


def resolve_request_budget(configured, capability, output_tokens: int | None, *, workset=False):
    """Keep frozen limits; fill unknown policy only from the exact model route.

    The 85/65 percent hysteresis follows the independent context core defaults.
    It is relative to this route's input allowance, never a GLM-specific cap.
    Immutable planning/approval/evidence inputs are observed, not summarized.
    Only an existing material-workset boundary can request local splitting.
    """
    budget = ModelRequestBudget.model_validate(configured) if configured is not None else None
    window = capability.context_window_tokens
    if budget is None:
        if not window or not output_tokens or output_tokens >= window:
            return None
        allowance = window - output_tokens
        trigger, target = int(allowance * .85), int(allowance * .65)
        budget = ModelRequestBudget(totalTokens=window, outputReserveTokens=output_tokens,
            **({"workingSetTriggerTokens": trigger, "workingSetTargetTokens": target} if 0 < target < trigger else {}))
    # A frozen budget cannot enlarge model capacity or reserve less than the
    # output allowance actually sent. No output limit is changed here.
    total = min(budget.total_tokens, window) if window else budget.total_tokens
    reserve = max(budget.output_reserve_tokens, output_tokens or 0)
    values = budget.model_dump(by_alias=True, exclude_none=True)
    values.update(totalTokens=total, outputReserveTokens=reserve,
                  workingSetMode="split" if workset else "observe")
    return ModelRequestBudget.model_validate(values)


def context_usage(diagnostics: dict, usage: dict, context_window: int | None = None) -> dict:
    """One request's input occupancy. Missing usage is never measured zero."""
    measured = next((usage[k] for k in ("input_tokens", "prompt_tokens", "inputTokens")
                     if type(usage.get(k)) is int and usage[k] >= 0), None)
    budget = diagnostics.get("requestBudget") or {}
    estimate = budget.get("estimatedInputTokens")
    estimate = estimate if type(estimate) is int and estimate >= 0 else None
    value = measured if measured is not None else estimate
    window = context_window or budget.get("totalTokens")
    return {"inputTokens": value, "contextWindowTokens": window,
            "measurement": "provider" if measured is not None else "estimate" if estimate is not None else "unknown",
            "estimator": None if measured is not None else budget.get("estimator"),
            "outputReserveTokens": budget.get("outputReserveTokens"),
            "workingSet": diagnostics.get("workingSet"),
            "ratio": value / window if value is not None and type(window) is int and window > 0 else None}


def request_diagnostics(payload: dict[str, Any], schema_index: int | None,
                        budget: ModelRequestBudget | None = None) -> dict[str, Any]:
    messages = payload.get("messages", [])
    shared = schema_index == 2 and len(messages) >= 4
    lengths = [len(message.get("content", "")) if isinstance(message.get("content", ""), str)
               else len(str(message.get("content", ""))) for message in messages]
    segments = []
    for index, message in enumerate(messages[:32]):
        segment = (
            ("sharedPolicy", "sharedTask", "capabilityAndSchema", "nodeInput")[index]
            if shared and index < 4 else "continuation" if shared else "message"
        )
        segments.append({
            "index": index,
            "role": message.get("role") if message.get("role") in {"system", "user", "assistant", "tool", "developer"} else "other",
            "segment": segment, "characters": lengths[index], "hash": canonical_hash(message),
        })
    # Count the complete context-bearing wire fields, after schema injection.
    # This includes tool definitions, arguments/results, memory and continuations.
    input_estimate = estimate_tokens({key: payload[key] for key in (
        "messages", "tools", "functions", "response_format",
    ) if key in payload})
    budget_diagnostics = {
        "estimator": "json-characters-div-3.2.v1",
        "estimatedInputTokens": input_estimate,
        "status": "notConfigured",
    }
    if budget is not None:
        budget_diagnostics.update({
            **budget.model_dump(by_alias=True, mode="json"),
            "estimatedTotalTokens": input_estimate + budget.output_reserve_tokens,
            "status": "exceeded" if input_estimate + budget.output_reserve_tokens > budget.total_tokens else "withinBudget",
        })
    working = {"status": "notConfigured", "mode": "observe"}
    if budget is not None and budget.working_set_trigger_tokens is not None:
        working = {"status": "exceeded" if input_estimate > budget.working_set_trigger_tokens else "withinBudget",
                   "triggerTokens": budget.working_set_trigger_tokens, "targetTokens": budget.working_set_target_tokens,
                   "mode": budget.working_set_mode, "measurement": "estimate",
                   "resolution": "materialSplit" if budget.working_set_mode == "split" else "protectedInputUnchanged"}
    return {
        "layoutVersion": "shared-execution.v1" if shared else "messages.v1",
        "lengthUnit": "characters",
        "messageCount": len(messages),
        "totalCharacters": sum(lengths),
        "omittedSegmentCount": max(0, len(messages) - len(segments)),
        "sharedPrefixHash": canonical_hash(messages[:2]) if shared else None,
        "sharedPrefixCharacters": sum(item["characters"] for item in segments[:2]) if shared else None,
        "segments": segments,
        "requestBudget": budget_diagnostics,
        "workingSet": working,
    }
