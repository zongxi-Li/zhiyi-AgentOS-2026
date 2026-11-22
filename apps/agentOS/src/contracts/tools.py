"""Provider-neutral tool discovery and model-safe execution results."""
from __future__ import annotations

from typing import Any
from dataclasses import dataclass
import re
from pydantic import BaseModel, ConfigDict, Field


HOST_TOOL_FAILURE_CODES = frozenset({
    "EXECUTION_LEASE_LOST", "SCHEDULER_UNAVAILABLE",
    "EXECUTION_RESOURCE_UNAVAILABLE", "EXECUTION_CAPACITY_UNAVAILABLE",
    "EXECUTION_AUTHORIZATION_LOST",
    "NO_ELIGIBLE_RESOURCE", "NO_MODEL_ENDPOINT",
})


def safe_tool_failure_details(value: object) -> dict[str, Any]:
    """Reference-only host facts; never tool arguments or provider messages."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("stepId", "attemptId", "commitId", "tool", "resourceId", "operationKey", "phase"):
        item = value.get(key)
        if (isinstance(item, str) and item and len(item) <= 1024
                and not any(c in item for c in "\x00\r\n")):
            result[key] = item
    reason = value.get("schedulingReason")
    if isinstance(reason, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", reason):
        result["schedulingReason"] = reason
    candidates = value.get("candidateReasons")
    if isinstance(candidates, (tuple, list)):
        safe_candidates = []
        for candidate in candidates[:16]:
            if not isinstance(candidate, dict):
                continue
            resource_id = candidate.get("resourceId")
            reasons = candidate.get("reasons")
            if (not isinstance(resource_id, str) or not resource_id or len(resource_id) > 1024
                    or any(c in resource_id for c in "\x00\r\n") or not isinstance(reasons, (tuple, list))):
                continue
            safe_reasons = list(dict.fromkeys(reason for reason in reasons
                if isinstance(reason, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", reason)))
            safe_candidates.append({"resourceId": resource_id, "reasons": safe_reasons})
        result["candidateReasons"] = safe_candidates
    return result


class HostToolExecutionError(RuntimeError):
    """A host-owned scheduling or execution failure, outside model correction."""

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = safe_tool_failure_details(details)


class ToolExecutionAuthorizationLost(PermissionError):
    """A live host authority changed; tool arguments cannot restore it."""

    code = "EXECUTION_AUTHORIZATION_LOST"


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    source: str
    description: str
    parameters: dict[str, Any]


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    source: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolExecutionResult:
    """Trusted execution result; record stays outside model observations."""
    data: dict[str, Any]
    record: dict[str, Any]

    def as_tool_result(self) -> ToolResult:
        return model_tool_result(self.record['tool'], self)


def hands_tools() -> tuple[ToolDefinition, ...]:
    """Fresh descriptions; callers cannot mutate another node's schema."""
    string = {"type": "string"}
    boolean = {"type": "boolean"}
    specs = [
        ("fs.read", "Read a workspace-relative file.",
         {"path": string, "binary": boolean, "versioned": boolean}, ["path"]),
        ("fs.list", "List a workspace-relative directory. Use path '.' for the bound workspace root; "
         "use returned relative names for child paths.", {"path": string}, ["path"]),
        ("fs.write", "Write a workspace-relative text file.",
         {"path": string, "content": string, "createIfAbsent": boolean, "expectedVersion": string}, ["path", "content"]),
        ("fs.patch", "Replace literal text in a workspace-relative file.",
         {"path": string, "oldText": string, "newText": string, "replaceAll": boolean, "expectedVersion": string},
         ["path", "oldText", "newText"]),
        ("shell.exec", "Execute a command through Hands, subject to workspace authorization and user approval. "
         "Use command/workdir for a command, or runner/path for a system-managed test run. "
         "Paths must be workspace-relative; executable and security settings are system-controlled.",
         {"command": string, "workdir": string, "path": string,
          "runner": {"type": "string", "enum": ["pytest", "node", "npm-test"]}}, []),
    ]
    definitions = tuple(ToolDefinition(name=name, source="hands", description=description,
        parameters={"type": "object", "properties": properties, "required": required, "additionalProperties": False})
        for name, description, properties, required in specs)
    definitions[-1].parameters['oneOf'] = [
        {'required': ['command'], 'not': {'anyOf': [{'required': ['runner']}, {'required': ['path']}]}},
        {'required': ['runner'], 'not': {'anyOf': [{'required': ['command']}, {'required': ['workdir']}]}}]
    return definitions


def model_tool_result(name: str, result: Any) -> ToolResult:
    """Project business observations only; never receipts, grants or host paths."""
    if isinstance(result, ToolResult):
        return result
    data = result.data
    fields = {"status", "path", "text", "content", "bytes", "binary", "encoding", "version",
              "entries", "exitCode", "stdout", "stderr", "timedOut", "aborted",
              "stdoutTruncated", "stderrTruncated", "created", "replacements",
              "terminationReason", "terminationMessage", "effectiveTimeoutSeconds", "timeoutSource"}
    output = {key: value for key, value in data.items() if key in fields}
    if getattr(result, 'record', {}).get('managedTest'):
        output['managedTest'] = True
    # Transport may enrich entries with host display paths. Only relative names
    # and business attributes belong in the model observation.
    if isinstance(output.get("entries"), list):
        output["entries"] = [{key: item[key] for key in ("name", "type", "size") if key in item}
                             for item in output["entries"] if isinstance(item, dict)]
    error = data.get("error")
    return ToolResult(name=name, source="hands", status=data.get("status", "failed"), output=output,
                      error={"code": error.get("code", "TOOL_EXECUTION_FAILED")} if error else None)
