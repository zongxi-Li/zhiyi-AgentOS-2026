"""Application helpers for one-shot, read-only tool calls used by domain packs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4


def network_tools_enabled(task_input: dict[str, Any] | None) -> bool:
    value = (task_input or {}).get("webSearchEnabled", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "disabled", "no"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return value is not False


def _public_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    public = getattr(value, "public_dict", None)
    if callable(public):
        result = public()
        return dict(result) if isinstance(result, dict) else {}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(by_alias=True, mode="json", exclude_none=True)
        return dict(result) if isinstance(result, dict) else {}
    return {}


@dataclass
class ToolCallOutcome:
    name: str
    envelope: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.envelope.get("ok")) and not self.error_code

    @property
    def results(self) -> list[dict[str, Any]]:
        data = self.envelope.get("data")
        rows = data.get("results") if isinstance(data, dict) else []
        return [dict(item) for item in (rows or []) if isinstance(item, dict)]


def _failed_execution(name: str, error_code: str, duration_ms: int) -> dict[str, Any]:
    return {
        "callId": f"call_acg_{uuid4().hex}",
        "toolName": name,
        "status": "failed",
        "durationMs": max(0, duration_ms),
        "inputSummary": "query",
        "outputSummary": "Tool execution failed.",
        "sourceRefs": [],
        "errorCode": error_code,
    }


async def execute_read_only_tool(runtime: Any, name: str, arguments: dict[str, Any]) -> ToolCallOutcome:
    """Execute one injected tool call and preserve failures as safe audit metadata."""
    started = perf_counter()
    if runtime is None:
        error = "TOOL_RUNTIME_UNAVAILABLE"
        return ToolCallOutcome(name=name, executions=[_failed_execution(name, error, 0)], error_code=error)
    try:
        result = await runtime.execute(name, arguments)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        error = "TOOL_TIMEOUT"
        return ToolCallOutcome(name=name, executions=[_failed_execution(name, error, int((perf_counter() - started) * 1000))], error_code=error)
    except Exception as exc:
        error = str(getattr(exc, "code", "") or type(exc).__name__.upper())[:120]
        return ToolCallOutcome(name=name, executions=[_failed_execution(name, error, int((perf_counter() - started) * 1000))], error_code=error)

    sources = [item for item in (_public_dict(value) for value in getattr(result, "sources", []) or []) if item]
    executions = [item for item in (_public_dict(value) for value in getattr(result, "tool_executions", []) or []) if item]
    try:
        envelope = json.loads(str(getattr(result, "text", "") or ""))
        if not isinstance(envelope, dict):
            raise ValueError("tool result must be an object")
    except (TypeError, ValueError, json.JSONDecodeError):
        error = "INVALID_TOOL_RESPONSE"
        if not executions:
            executions.append(_failed_execution(name, error, int((perf_counter() - started) * 1000)))
        return ToolCallOutcome(name=name, sources=sources, executions=executions, error_code=error)

    error_code = None if envelope.get("ok") else str(envelope.get("error") or "TOOL_FAILED")
    if error_code and not executions:
        executions.append(_failed_execution(name, error_code, int((perf_counter() - started) * 1000)))
    return ToolCallOutcome(name=name, envelope=envelope, sources=sources, executions=executions, error_code=error_code)


__all__ = ["ToolCallOutcome", "execute_read_only_tool", "network_tools_enabled"]
