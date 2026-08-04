"""Shared lifecycle enums for AgentOS core models and projections."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class WorkflowProgressPhase(str, Enum):
    """Persisted and projected phases of a workflow run lifecycle."""

    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    GRAPH_BUILDING = "graph_building"
    EXECUTING = "executing"
    RECOVERY = "recovery"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Shared persisted lifecycle for WorkflowStep projections and RuntimeNodes."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    RETRYING = "retrying"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SKIPPED_BY_CONDITION = "skipped_by_condition"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionPackageRef(BaseModel):
    """执行包的版本化引用；图的具体结构由 workflow 合同表达。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    package_id: StrictStr = Field(alias="packageId", min_length=1)
    graph: Any
    entry_node: Any | None = Field(default=None, alias="entryNode")
    checksum: StrictStr = Field(min_length=1)
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt")


class ExecutionOutcomeRef(BaseModel):
    """执行结果的轻量引用，输出正文由存储部件维护。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    execution_id: StrictStr = Field(alias="executionId", min_length=1)
    package_id: StrictStr = Field(alias="packageId", min_length=1)
    status: Literal["succeeded", "failed", "cancelled", "pending"]
    output_ref: StrictStr | None = Field(default=None, alias="outputRef")
    error_code: StrictStr | None = Field(default=None, alias="errorCode")
    metadata: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = Field(default=None, alias="completedAt")


__all__ = ["StepStatus", "WorkflowProgressPhase"]
