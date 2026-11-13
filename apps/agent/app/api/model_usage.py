"""Provider usage aliases and cache grouping; never inspect request bodies."""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return int(value)
    return None


def cache_usage(usage: dict[str, Any]) -> tuple[int, bool]:
    # Use the first reported alias, including an explicit zero. Never add aliases.
    for key in ("cache_read_tokens", "cache_read_input_tokens", "cached_tokens", "cacheReadTokens", "prompt_cache_hit_tokens"):
        value = _number(usage.get(key))
        if value is not None:
            return value, True
    for key in ("prompt_tokens_details", "input_tokens_details"):
        details = usage.get(key)
        value = _number(details.get("cached_tokens")) if isinstance(details, dict) else None
        if value is not None:
            return value, True
    return 0, False


def cache_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    reported = [call for call in calls if call.get("cacheUsageReported")]
    measured_input = sum(call["usage"]["inputTokens"] for call in reported)
    hits = sum(call["usage"]["cacheReadTokens"] for call in reported)
    all_reported = bool(calls) and len(reported) == len(calls)
    return {
        "cacheUsageReportedCalls": len(reported),
        "cacheUsageMissingCalls": len(calls) - len(reported),
        "cacheMeasuredInputTokens": measured_input,
        "cacheMissTokens": max(0, measured_input - hits) if all_reported else None,
        "cacheHitRatio": round(hits / measured_input, 4) if all_reported and measured_input else None,
    }


def cache_groups(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for call in calls:
        diagnostics = call.get("requestDiagnostics") or {}
        key = (call.get("provider"), call.get("model"), call.get("modelVersion"), diagnostics.get("layoutVersion"),
               diagnostics.get("sharedPrefixHash") or call.get("stablePrefixHash"), call.get("capabilityId"))
        groups.setdefault(key, []).append(call)
    return [
        dict(zip(("provider", "model", "modelVersion", "layoutVersion", "sharedPrefixHash", "capabilityId"), key),
             callCount=len(items), inputTokens=sum(c["usage"]["inputTokens"] for c in items),
             cacheReadTokens=sum(c["usage"]["cacheReadTokens"] for c in items), **cache_summary(items))
        for key, items in groups.items()
    ]
