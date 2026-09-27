"""Stable northbound contracts for the AgentOS v2 control plane.

These models are HTTP projections.  They intentionally do not mirror
``RuntimeRunRecord`` or expose canonical ACG, checkpoint, binding, or scheduler
state.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.workflow import RuntimeRunRecord


class PublicContractModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PublicRunStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    RETRYING = "retrying"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class PublicLifecyclePhase(str, Enum):
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    GRAPH_BUILDING = "graph_building"
    EXECUTING = "executing"
    RECOVERY = "recovery"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorDetail(PublicContractModel):
    code: str
    message: str


class AgentOsErrorResponse(ErrorDetail):
    request_id: str | None = Field(default=None, alias="requestId")


class RunResponse(PublicContractModel):
    run_id: str = Field(alias="runId")
    mission_id: str = Field(alias="missionId")
    workflow_id: str = Field(alias="workflowId")
    status: PublicRunStatus
    lifecycle_phase: PublicLifecyclePhase | None = Field(default=None, alias="lifecyclePhase")
    lifecycle_message: str | None = Field(default=None, alias="lifecycleMessage")
    current_step_id: str | None = Field(default=None, alias="currentStepId")
    runtime_revision: int = Field(alias="runtimeRevision", ge=0)
    parent_run_id: str | None = Field(default=None, alias="parentRunId")
    source_run_id: str | None = Field(default=None, alias="sourceRunId")
    supersedes_run_id: str | None = Field(default=None, alias="supersedesRunId")
    superseded_by_run_id: str | None = Field(default=None, alias="supersededByRunId")
    review_state: str | None = Field(default=None, alias="reviewState")
    error: ErrorDetail | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")


class MissionResponse(RunResponse):
    """Accepted Mission command and its initial Run projection."""


class MissionSummary(PublicContractModel):
    mission_id: str = Field(alias="missionId")
    title: str
    status: str
    latest_run_id: str | None = Field(default=None, alias="latestRunId")
    latest_run_status: PublicRunStatus | None = Field(default=None, alias="latestRunStatus")
    run_count: int = Field(default=0, alias="runCount", ge=0)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class RunSummary(PublicContractModel):
    run_id: str = Field(alias="runId")
    mission_id: str = Field(alias="missionId")
    workflow_id: str = Field(alias="workflowId")
    status: PublicRunStatus
    lifecycle_phase: PublicLifecyclePhase | None = Field(default=None, alias="lifecyclePhase")
    current_step_id: str | None = Field(default=None, alias="currentStepId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ReviewResponse(RunResponse):
    operation_id: str = Field(alias="operationId")
    decision: str


class OperationResponse(RunResponse):
    operation: str


def _public_error(value: Any) -> ErrorDetail | None:
    if value is None:
        return None
    if isinstance(value, dict):
        code = str(value.get("code") or "RUN_FAILED")
        message = str(value.get("message") or "Run failed.")
        return ErrorDetail(code=code, message=message[:500])
    return ErrorDetail(code="RUN_FAILED", message=str(value)[:500])


def project_control_run(run: RuntimeRunRecord, model: type[RunResponse] = RunResponse, **extra: Any) -> RunResponse:
    """Project one Runtime Run without exposing its internal execution state."""

    state = run.execution_state
    review_state = "waiting" if run.status.value == "waiting_review" else None
    return model(
        runId=run.run_id,
        missionId=run.mission_id,
        workflowId=run.workflow_id,
        status=run.status.value,
        lifecyclePhase=(run.lifecycle_phase.value if run.lifecycle_phase else None),
        lifecycleMessage=run.lifecycle_message,
        currentStepId=run.current_step_id,
        runtimeRevision=run.runtime_revision,
        parentRunId=state.get("parentRunId"),
        sourceRunId=state.get("sourceRunId"),
        supersedesRunId=state.get("supersedesRunId"),
        supersededByRunId=state.get("supersededByRunId"),
        reviewState=review_state,
        error=_public_error(run.error),
        createdAt=run.created_at,
        updatedAt=run.updated_at,
        startedAt=run.started_at,
        **extra,
    )


__all__ = [
    "AgentOsErrorResponse",
    "ErrorDetail",
    "MissionResponse",
    "MissionSummary",
    "OperationResponse",
    "PublicLifecyclePhase",
    "PublicRunStatus",
    "ReviewResponse",
    "RunResponse",
    "RunSummary",
    "project_control_run",
]
