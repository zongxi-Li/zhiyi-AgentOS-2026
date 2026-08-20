"""Repository Protocol 使 Runtime 不依赖具体数据库。"""

from __future__ import annotations

from typing import Protocol

from contracts.identity import AttemptId, BlueprintId, RunId, StepExecutionId, TaskNodeId, UserTaskId
from domain.models import (
    AcgBlueprint,
    Attempt,
    AttemptStatus,
    RunStatus,
    StepExecution,
    StepExecutionStatus,
    TaskNode,
    UserTask,
    UserTaskStatus,
    WorkflowRun,
)


class UserTaskRepository(Protocol):
    def add(self, task: UserTask) -> None: ...
    def get(self, task_id: UserTaskId) -> UserTask | None: ...
    def update_status(self, task_id: UserTaskId, status: UserTaskStatus) -> UserTask: ...


class TaskNodeRepository(Protocol):
    def add(self, node: TaskNode) -> None: ...
    def get(self, node_id: TaskNodeId) -> TaskNode | None: ...
    def list_for_task(self, task_id: UserTaskId) -> list[TaskNode]: ...


class BlueprintRepository(Protocol):
    def add(self, blueprint: AcgBlueprint) -> None: ...
    def get(self, blueprint_id: BlueprintId) -> AcgBlueprint | None: ...
    def list_for_task(self, task_id: UserTaskId) -> list[AcgBlueprint]: ...


class RunRepository(Protocol):
    def add(self, run: WorkflowRun) -> None: ...
    def get(self, run_id: RunId) -> WorkflowRun | None: ...
    def list_for_task(self, task_id: UserTaskId) -> list[WorkflowRun]: ...
    def update_status(self, run_id: RunId, status: RunStatus) -> WorkflowRun: ...


class AttemptRepository(Protocol):
    def add(self, attempt: Attempt) -> None: ...
    def get(self, attempt_id: AttemptId) -> Attempt | None: ...
    def list_for_run(self, run_id: RunId) -> list[Attempt]: ...
    def update_status(
        self,
        attempt_id: AttemptId,
        status: AttemptStatus,
        *,
        failure_reason: str | None = None,
    ) -> Attempt: ...


class StepExecutionRepository(Protocol):
    def add(self, execution: StepExecution) -> None: ...
    def get(self, step_execution_id: StepExecutionId) -> StepExecution | None: ...
    def list_for_attempt(self, attempt_id: AttemptId) -> list[StepExecution]: ...


class RepositorySet(Protocol):
    user_tasks: UserTaskRepository
    task_nodes: TaskNodeRepository
    blueprints: BlueprintRepository
    runs: RunRepository
    attempts: AttemptRepository
    step_executions: StepExecutionRepository

    def finish_execution(
        self,
        step_execution_id: StepExecutionId,
        attempt_id: AttemptId,
        *,
        step_status: StepExecutionStatus,
        attempt_status: AttemptStatus,
        output: dict,
        failure_reason: str | None = None,
    ) -> tuple[StepExecution, Attempt]: ...

    def close(self) -> None: ...


__all__ = [
    "AttemptRepository",
    "BlueprintRepository",
    "RepositorySet",
    "RunRepository",
    "StepExecutionRepository",
    "TaskNodeRepository",
    "UserTaskRepository",
]
