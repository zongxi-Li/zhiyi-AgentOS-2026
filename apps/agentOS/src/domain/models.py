"""与旧 Runtime 并行存在的 AgentOS 六级身份领域模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.timestamps import UTCTimestamp

from contracts.identity import (
    AttemptId,
    ArtifactId,
    ArtifactKey,
    BlueprintId,
    RunId,
    SemanticTaskKey,
    StepExecutionId,
    TaskId,
    MissionId,
    new_attempt_id,
    new_artifact_id,
    new_blueprint_id,
    new_run_id,
    new_step_execution_id,
    new_task_id,
    new_mission_id,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", validate_assignment=True)


class MissionStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SemanticTaskStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class AttemptStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class StepExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class Mission(DomainModel):
    """用户希望长期完成的目标，不承载 Run、Attempt 或 Step 生命周期。"""

    mission_id: MissionId = Field(default_factory=new_mission_id, alias="missionId")
    user_id: str = Field(alias="userId", min_length=1)
    goal: str = Field(min_length=1)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")
    status: MissionStatus = MissionStatus.CREATED


class SemanticTask(DomainModel):
    """Planner 产生的任务分解节点；它不是 ACG 图节点或执行记录。"""

    task_id: TaskId = Field(default_factory=new_task_id, alias="taskId")
    mission_id: MissionId = Field(alias="missionId")
    # Legacy rows and direct domain fixtures may not have this value yet.  The
    # Planner/TaskPlan persistence path requires it before a new Run is projected.
    semantic_task_key: SemanticTaskKey | None = Field(
        default=None,
        alias="semanticTaskKey",
    )
    parent_task_id: TaskId | None = Field(default=None, alias="parentTaskId")
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    status: SemanticTaskStatus = SemanticTaskStatus.CREATED
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_self_parent(self) -> "SemanticTask":
        if self.parent_task_id == self.task_id:
            raise ValueError("SemanticTask cannot be its own parent")
        return self


class Artifact(DomainModel):
    """Immutable domain identity for content produced by one Attempt.

    Content and fragments remain in ContentManifest.  This entity only records
    the Mission-scoped logical slot and the producer relationship.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        validate_assignment=False,
        frozen=True,
    )

    artifact_id: ArtifactId = Field(default_factory=new_artifact_id, alias="artifactId")
    mission_id: MissionId = Field(alias="missionId")
    origin_run_id: RunId = Field(alias="originRunId")
    task_id: TaskId = Field(alias="taskId")
    semantic_task_key: SemanticTaskKey = Field(alias="semanticTaskKey")
    artifact_key: ArtifactKey = Field(alias="artifactKey")
    acg_node_id: str = Field(alias="acgNodeId", min_length=1)
    producer_attempt_id: AttemptId = Field(alias="producerAttemptId")
    name: str = Field(min_length=1)
    artifact_type: str = Field(alias="artifactType", min_length=1)
    media_type: str = Field(alias="mediaType", min_length=1)
    content_ref: str = Field(alias="contentRef", min_length=1)
    checksum: str = Field(min_length=64, max_length=64)
    created_at: UTCTimestamp = Field(default_factory=utc_now, alias="createdAt")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_usage_state(self) -> "Artifact":
        forbidden = {
            "stale",
            "invalidated",
            "current",
            "disposition",
        }.intersection(self.metadata)
        if forbidden:
            raise ValueError(
                "Artifact metadata cannot contain usage state: "
                + ", ".join(sorted(forbidden))
            )
        return self


class AcgBlueprint(DomainModel):
    """版本化设计产物；blueprintId 与 Runtime graphId 是不同身份。"""

    blueprint_id: BlueprintId = Field(default_factory=new_blueprint_id, alias="blueprintId")
    mission_id: MissionId = Field(alias="missionId")
    version: int = Field(default=1, ge=1)
    graph_id: str = Field(alias="graphId", min_length=1)
    graph: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRun(DomainModel):
    """AgentOS 中的一次执行身份；区别于 Execution Runtime 内核的 RuntimeRunRecord。"""

    run_id: RunId = Field(default_factory=new_run_id, alias="runId")
    mission_id: MissionId = Field(alias="missionId")
    blueprint_id: BlueprintId = Field(alias="blueprintId")
    status: RunStatus = RunStatus.PENDING
    graph_version: int = Field(default=1, alias="graphVersion", ge=1)
    checkpoint: dict[str, Any] | None = None
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")
    metadata: dict[str, Any] = Field(default_factory=dict)


class Attempt(DomainModel):
    """一个 Run 中某个任务节点的一次独立尝试。"""

    attempt_id: AttemptId = Field(default_factory=new_attempt_id, alias="attemptId")
    run_id: RunId = Field(alias="runId")
    task_id: TaskId = Field(alias="taskId")
    status: AttemptStatus = AttemptStatus.PENDING
    attempt_number: int = Field(alias="attemptNumber", ge=1)
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    failure_reason: str | None = Field(default=None, alias="failureReason")
    resource_binding: dict[str, Any] | None = Field(default=None, alias="resourceBinding")


class StepExecution(DomainModel):
    """节点在指定 Attempt 中的执行实例；不复用 nodeId 作为主键。"""

    step_execution_id: StepExecutionId = Field(
        default_factory=new_step_execution_id,
        alias="stepExecutionId",
    )
    run_id: RunId = Field(alias="runId")
    task_id: TaskId = Field(alias="taskId")
    attempt_id: AttemptId = Field(alias="attemptId")
    status: StepExecutionStatus = StepExecutionStatus.PENDING
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")


class IdentityOwnership:
    """在持久化迁移前提供显式的内存身份归属检查。"""

    def __init__(self) -> None:
        self._blueprint_tasks: dict[BlueprintId, MissionId] = {}
        self._run_tasks: dict[RunId, MissionId] = {}
        self._attempt_runs: dict[AttemptId, RunId] = {}
        self._blueprint_runs: dict[BlueprintId, set[RunId]] = {}

    def bind_blueprint(self, blueprint: AcgBlueprint) -> None:
        owner = self._blueprint_tasks.get(blueprint.blueprint_id)
        if owner is not None and owner != blueprint.mission_id:
            raise ValueError("blueprintId cannot be shared by different missionIds")
        self._blueprint_tasks[blueprint.blueprint_id] = blueprint.mission_id

    def bind_run(self, run: WorkflowRun) -> None:
        owner = self._run_tasks.get(run.run_id)
        if owner is not None and owner != run.mission_id:
            raise ValueError("runId cannot be shared by different missionIds")
        blueprint_owner = self._blueprint_tasks.get(run.blueprint_id)
        if blueprint_owner is not None and blueprint_owner != run.mission_id:
            raise ValueError("WorkflowRun missionId must match its Blueprint missionId")
        self._run_tasks[run.run_id] = run.mission_id
        self._blueprint_runs.setdefault(run.blueprint_id, set()).add(run.run_id)

    def bind_attempt(self, attempt: Attempt) -> None:
        owner = self._attempt_runs.get(attempt.attempt_id)
        if owner is not None and owner != attempt.run_id:
            raise ValueError("attemptId cannot be shared by different runIds")
        self._attempt_runs[attempt.attempt_id] = attempt.run_id

    def runs_for_blueprint(self, blueprint_id: BlueprintId) -> frozenset[RunId]:
        return frozenset(self._blueprint_runs.get(blueprint_id, set()))


__all__ = [
    "AcgBlueprint",
    "Artifact",
    "Attempt",
    "AttemptStatus",
    "IdentityOwnership",
    "RunStatus",
    "StepExecution",
    "StepExecutionStatus",
    "SemanticTask",
    "SemanticTaskStatus",
    "Mission",
    "MissionStatus",
    "WorkflowRun",
]
