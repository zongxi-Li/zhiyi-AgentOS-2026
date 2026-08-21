"""Repository Protocol 使 Runtime 不依赖具体数据库。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

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
from domain.lifecycle_projection import LifecycleProjectionEvent
from contracts.planning import TaskPlan
if TYPE_CHECKING:
    from domain.identity_graph.bindings import (
        BlueprintNodeBinding,
        ExecutionBinding,
        ProvenanceLink,
        TaskNodeBinding,
    )


class UserTaskRepository(Protocol):
    def add(self, task: UserTask) -> None: ...
    def get(self, task_id: UserTaskId) -> UserTask | None: ...
    def list(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: UserTaskStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[UserTask], int]: ...
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
    def update_blueprint(
        self, run_id: RunId, blueprint_id: BlueprintId, graph_version: int
    ) -> WorkflowRun: ...
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


class TaskNodeBindingRepository(Protocol):
    def add(self, binding: TaskNodeBinding) -> None: ...
    def get(self, binding_id: str) -> TaskNodeBinding | None: ...
    def find_for_task_node(
        self, task_node_id: TaskNodeId, blueprint_id: BlueprintId
    ) -> list[TaskNodeBinding]: ...
    def find_for_acg_node(
        self, acg_node_id: str, blueprint_id: BlueprintId
    ) -> list[TaskNodeBinding]: ...


class BlueprintNodeBindingRepository(Protocol):
    def add(self, binding: BlueprintNodeBinding) -> None: ...
    def list_for_blueprint(self, blueprint_id: BlueprintId) -> list[BlueprintNodeBinding]: ...


class ExecutionBindingRepository(Protocol):
    def add(self, binding: ExecutionBinding) -> None: ...
    def get_for_attempt(self, attempt_id: AttemptId) -> ExecutionBinding | None: ...


class ProvenanceLinkRepository(Protocol):
    def add(self, link: ProvenanceLink) -> None: ...
    def list_from(self, source_id: str) -> list[ProvenanceLink]: ...
    def list_to(self, target_id: str) -> list[ProvenanceLink]: ...


class LifecycleProjectionEventRepository(Protocol):
    def begin(self, event: LifecycleProjectionEvent) -> LifecycleProjectionEvent: ...
    def mark_applied(self, event_id: str) -> LifecycleProjectionEvent: ...
    def mark_failed(self, event_id: str, error: str) -> LifecycleProjectionEvent: ...
    def get(self, event_id: str) -> LifecycleProjectionEvent | None: ...
    def list_unapplied(self, *, limit: int = 200) -> list[LifecycleProjectionEvent]: ...
    def stats(self) -> dict[str, Any]: ...


class RepositorySet(Protocol):
    user_tasks: UserTaskRepository
    task_nodes: TaskNodeRepository
    blueprints: BlueprintRepository
    runs: RunRepository
    attempts: AttemptRepository
    step_executions: StepExecutionRepository
    task_node_bindings: TaskNodeBindingRepository
    blueprint_node_bindings: BlueprintNodeBindingRepository
    execution_bindings: ExecutionBindingRepository
    provenance_links: ProvenanceLinkRepository
    projection_events: LifecycleProjectionEventRepository
    inbox_events: LifecycleProjectionEventRepository
    task_plans: Any

    def persist_task_plan(self, plan: TaskPlan) -> dict[str, TaskNode]: ...

    def ensure_attempt(
        self,
        run_id: RunId,
        node_id: TaskNodeId,
        *,
        attempt_number: int | None = None,
        resource_binding: dict | None = None,
    ) -> Attempt: ...

    def ensure_step_execution(
        self,
        run_id: RunId,
        node_id: TaskNodeId,
        attempt_id: AttemptId,
        *,
        input: dict,
    ) -> StepExecution: ...

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
    "BlueprintNodeBindingRepository",
    "BlueprintRepository",
    "ExecutionBindingRepository",
    "LifecycleProjectionEventRepository",
    "ProvenanceLinkRepository",
    "RepositorySet",
    "RunRepository",
    "StepExecutionRepository",
    "TaskNodeRepository",
    "TaskNodeBindingRepository",
    "UserTaskRepository",
]
