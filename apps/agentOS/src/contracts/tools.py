"""Provider-neutral tool discovery and model-safe execution results."""
from __future__ import annotations

from typing import Any
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field


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
        ("fs.list", "List a workspace-relative directory.", {"path": string}, ["path"]),
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
              "stdoutTruncated", "stderrTruncated", "created", "replacements"}
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
