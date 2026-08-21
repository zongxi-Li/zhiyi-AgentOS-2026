"""与旧 Runtime 并行存在的 AgentOS 六级身份领域模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.identity import (
    AttemptId,
    BlueprintId,
    RunId,
    StepExecutionId,
    TaskNodeId,
    UserTaskId,
    new_attempt_id,
    new_blueprint_id,
    new_run_id,
    new_step_execution_id,
    new_task_node_id,
    new_user_task_id,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", validate_assignment=True)


class UserTaskStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TaskNodeStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


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


class UserTask(DomainModel):
    """用户希望长期完成的目标，不承载 Run、Attempt 或 Step 生命周期。"""

    task_id: UserTaskId = Field(default_factory=new_user_task_id, alias="taskId")
    user_id: str = Field(alias="userId", min_length=1)
    goal: str = Field(min_length=1)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")
    status: UserTaskStatus = UserTaskStatus.CREATED


class TaskNode(DomainModel):
    """Planner 产生的任务分解节点；它不是 ACG 图节点或执行记录。"""

    node_id: TaskNodeId = Field(default_factory=new_task_node_id, alias="nodeId")
    task_id: UserTaskId = Field(alias="taskId")
    parent_node_id: TaskNodeId | None = Field(default=None, alias="parentNodeId")
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    status: TaskNodeStatus = TaskNodeStatus.CREATED
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_self_parent(self) -> "TaskNode":
        if self.parent_node_id == self.node_id:
            raise ValueError("TaskNode cannot be its own parent")
        return self


class AcgBlueprint(DomainModel):
    """版本化设计产物；blueprintId 与 Runtime graphId 是不同身份。"""

    blueprint_id: BlueprintId = Field(default_factory=new_blueprint_id, alias="blueprintId")
    task_id: UserTaskId = Field(alias="taskId")
    version: int = Field(default=1, ge=1)
    graph_id: str = Field(alias="graphId", min_length=1)
    graph: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRun(DomainModel):
    """AgentOS 中的一次执行身份；区别于 WKN 内核的 WknWorkflowRun。"""

    run_id: RunId = Field(default_factory=new_run_id, alias="runId")
    task_id: UserTaskId = Field(alias="taskId")
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
    node_id: TaskNodeId = Field(alias="nodeId")
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
    node_id: TaskNodeId = Field(alias="nodeId")
    attempt_id: AttemptId = Field(alias="attemptId")
    status: StepExecutionStatus = StepExecutionStatus.PENDING
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")


class IdentityOwnership:
    """在持久化迁移前提供显式的内存身份归属检查。"""

    def __init__(self) -> None:
        self._blueprint_tasks: dict[BlueprintId, UserTaskId] = {}
        self._run_tasks: dict[RunId, UserTaskId] = {}
        self._attempt_runs: dict[AttemptId, RunId] = {}
        self._blueprint_runs: dict[BlueprintId, set[RunId]] = {}

    def bind_blueprint(self, blueprint: AcgBlueprint) -> None:
        owner = self._blueprint_tasks.get(blueprint.blueprint_id)
        if owner is not None and owner != blueprint.task_id:
            raise ValueError("blueprintId cannot be shared by different taskIds")
        self._blueprint_tasks[blueprint.blueprint_id] = blueprint.task_id

    def bind_run(self, run: WorkflowRun) -> None:
        owner = self._run_tasks.get(run.run_id)
        if owner is not None and owner != run.task_id:
            raise ValueError("runId cannot be shared by different taskIds")
        blueprint_owner = self._blueprint_tasks.get(run.blueprint_id)
        if blueprint_owner is not None and blueprint_owner != run.task_id:
            raise ValueError("WorkflowRun taskId must match its Blueprint taskId")
        self._run_tasks[run.run_id] = run.task_id
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
    "Attempt",
    "AttemptStatus",
    "IdentityOwnership",
    "RunStatus",
    "StepExecution",
    "StepExecutionStatus",
    "TaskNode",
    "TaskNodeStatus",
    "UserTask",
    "UserTaskStatus",
    "WorkflowRun",
]
