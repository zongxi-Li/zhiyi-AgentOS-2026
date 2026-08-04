"""不可变执行包与本地调用分发边界。"""

from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StepExecutionPackage(BaseModel):
    """调度时冻结的执行输入，工作线程不得回写该快照。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    run_id: str = Field(alias="runId")
    task_id: str = Field(alias="taskId")
    graph_id: str = Field(alias="graphId")
    graph_version: int = Field(alias="graphVersion")
    runtime_node_id: str = Field(alias="runtimeNodeId")
    attempt_id: str = Field(alias="attemptId")
    attempt_number: int = Field(alias="attemptNumber")
    binding: dict[str, Any] = Field(default_factory=dict)
    node_spec: dict[str, Any] = Field(alias="nodeSpec")
    run_input: dict[str, Any] = Field(alias="runInput")
    upstream_outputs: dict[str, dict[str, Any]] = Field(alias="upstreamOutputs")
    context_metadata: dict[str, Any] = Field(default_factory=dict, alias="contextMetadata")
    timeout: int = 0
    run_snapshot: dict[str, Any] = Field(alias="runSnapshot")


class StepExecutionOutcome(BaseModel):
    """与执行包分离的结果；只允许屏障在匹配的 attempt 上合并。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    run_id: str = Field(alias="runId")
    graph_id: str = Field(alias="graphId")
    scheduled_graph_version: int = Field(alias="scheduledGraphVersion")
    runtime_node_id: str = Field(alias="runtimeNodeId")
    attempt_id: str = Field(alias="attemptId")
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    resolved_input: dict[str, Any] = Field(default_factory=dict, alias="resolvedInput")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="startedAt")
    ended_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="endedAt")
    trace_events: list[dict[str, Any]] = Field(default_factory=list, alias="traceEvents")
    provenance_events: dict[str, Any] = Field(default_factory=dict, alias="provenanceEvents")
    review_required: bool = Field(default=False, alias="reviewRequired")
    recoverable: bool = False
    runtime_signals: list[dict[str, Any]] = Field(default_factory=list, alias="runtimeSignals")
    error_type: str = Field(default="", alias="errorType")
    error_code: str = Field(default="", alias="errorCode")
    error_direction: str = Field(default="", alias="errorDirection")


def dispatch(handler: Callable[..., Any], payload: dict[str, Any]) -> Any:
    """同步调用注入的处理器；远程调用必须经 adapters.remote_agent 提供。"""
    return handler(**payload)


# TODO: 接入远程 Agent HTTP/gRPC 适配器，并传播可审计的超时和取消信号。


__all__ = ["StepExecutionOutcome", "StepExecutionPackage", "dispatch"]
