"""只编排新身份链和持久化的 WorkflowRuntimeV2。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.identity import AttemptId, BlueprintId, RunId, TaskNodeId, UserTaskId
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
from domain.repository import EntityNotFoundError, IdentityConflictError, RepositorySet
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage

from .context import ExecutionContext
from .state import require_transition


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowRuntimeV2:
    """新执行真源的基础编排器，不调用旧 Executor 或 Scheduler。"""

    def __init__(self, repositories: RepositorySet) -> None:
        self.repositories = repositories

    @classmethod
    def from_sqlite(
        cls,
        db_path: str | Path = "data/agentos_v2.sqlite3",
    ) -> "WorkflowRuntimeV2":
        return cls(SQLiteV2Repositories(SQLiteV2Storage(db_path)))

    def close(self) -> None:
        self.repositories.close()

    def create_task(
        self,
        *,
        user_id: str,
        goal: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> UserTask:
        task = UserTask(
            userId=user_id,
            goal=goal,
            description=description,
            metadata=metadata or {},
        )
        self.repositories.user_tasks.add(task)
        return task

    def create_task_node(
        self,
        *,
        task_id: UserTaskId,
        title: str,
        objective: str,
        parent_node_id: TaskNodeId | None = None,
        constraints: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskNode:
        task = self._task(task_id)
        if task.status is UserTaskStatus.CREATED:
            require_transition(task.status, UserTaskStatus.PLANNING)
            self.repositories.user_tasks.update_status(task_id, UserTaskStatus.PLANNING)
        node = TaskNode(
            taskId=task_id,
            parentNodeId=parent_node_id,
            title=title,
            objective=objective,
            constraints=constraints or [],
            metadata=metadata or {},
        )
        self.repositories.task_nodes.add(node)
        return node

    def create_blueprint(
        self,
        *,
        task_id: UserTaskId,
        version: int,
        graph_id: str,
        graph: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> AcgBlueprint:
        task = self._task(task_id)
        if not self.repositories.task_nodes.list_for_task(task_id):
            raise ValueError("AcgBlueprint requires at least one TaskNode")
        blueprint = AcgBlueprint(
            taskId=task_id,
            version=version,
            graphId=graph_id,
            graph=graph,
            metadata=metadata or {},
        )
        self.repositories.blueprints.add(blueprint)
        if task.status is UserTaskStatus.PLANNING:
            require_transition(task.status, UserTaskStatus.READY)
            self.repositories.user_tasks.update_status(task_id, UserTaskStatus.READY)
        return blueprint

    def create_run(
        self,
        *,
        task_id: UserTaskId,
        blueprint_id: BlueprintId,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        self._task(task_id)
        blueprint = self._blueprint(blueprint_id)
        if blueprint.task_id != task_id:
            raise IdentityConflictError("WorkflowRun cannot use another UserTask's Blueprint")
        run = WorkflowRun(
            taskId=task_id,
            blueprintId=blueprint_id,
            graphVersion=blueprint.version,
            metadata=metadata or {},
        )
        self.repositories.runs.add(run)
        return run

    def create_context(self, run_id: RunId) -> ExecutionContext:
        run = self._run(run_id)
        attempts = self.repositories.attempts.list_for_run(run_id)
        current = attempts[-1].attempt_id if attempts else None
        active = []
        if current is not None:
            active = [
                execution.step_execution_id
                for execution in self.repositories.step_executions.list_for_attempt(current)
                if execution.status is StepExecutionStatus.RUNNING
            ]
        return ExecutionContext(
            runId=run.run_id,
            taskId=run.task_id,
            blueprintId=run.blueprint_id,
            currentAttempt=current,
            activeExecutions=active,
        )

    def create_attempt(
        self,
        *,
        run_id: RunId,
        node_id: TaskNodeId,
        resource_binding: dict[str, Any] | None = None,
    ) -> Attempt:
        run = self._run(run_id)
        node = self._node(node_id)
        if node.task_id != run.task_id:
            raise IdentityConflictError("Attempt cannot use another UserTask's TaskNode")
        prior = [
            item for item in self.repositories.attempts.list_for_run(run_id)
            if item.node_id == node_id
        ]
        attempt = Attempt(
            runId=run_id,
            nodeId=node_id,
            attemptNumber=len(prior) + 1,
            resourceBinding=resource_binding,
        )
        self.repositories.attempts.add(attempt)
        if run.status is RunStatus.PENDING:
            require_transition(run.status, RunStatus.RUNNING)
            self.repositories.runs.update_status(run_id, RunStatus.RUNNING)
        task = self._task(run.task_id)
        if task.status is UserTaskStatus.READY:
            require_transition(task.status, UserTaskStatus.RUNNING)
            self.repositories.user_tasks.update_status(task.task_id, UserTaskStatus.RUNNING)
        return attempt

    def execute_step(
        self,
        context: ExecutionContext,
        *,
        input: dict[str, Any],
        operation: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> StepExecution:
        if context.current_attempt is None:
            raise ValueError("ExecutionContext has no current Attempt")
        run = self._run(context.run_id)
        attempt = self._attempt(context.current_attempt)
        if (
            run.task_id != context.task_id
            or run.blueprint_id != context.blueprint_id
            or attempt.run_id != context.run_id
        ):
            raise IdentityConflictError("ExecutionContext identity chain is inconsistent")
        require_transition(attempt.status, AttemptStatus.RUNNING)
        self.repositories.attempts.update_status(attempt.attempt_id, AttemptStatus.RUNNING)
        started_at = _now()
        execution = StepExecution(
            runId=run.run_id,
            nodeId=attempt.node_id,
            attemptId=attempt.attempt_id,
            status=StepExecutionStatus.RUNNING,
            input=input,
            output={},
            startedAt=started_at,
        )
        self.repositories.step_executions.add(execution)
        context.active_executions.append(execution.step_execution_id)
        try:
            output = operation(dict(input))
            if not isinstance(output, dict):
                raise TypeError("step operation must return a dictionary")
        except Exception as exc:
            execution, _ = self.repositories.finish_execution(
                execution.step_execution_id,
                attempt.attempt_id,
                step_status=StepExecutionStatus.FAILED,
                attempt_status=AttemptStatus.FAILED,
                output={},
                failure_reason=str(exc),
            )
            context.active_executions.remove(execution.step_execution_id)
            raise
        execution, _ = self.repositories.finish_execution(
            execution.step_execution_id,
            attempt.attempt_id,
            step_status=StepExecutionStatus.SUCCEEDED,
            attempt_status=AttemptStatus.SUCCEEDED,
            output=output,
        )
        context.active_executions.remove(execution.step_execution_id)
        return execution

    def finish_run(self, run_id: RunId, status: RunStatus) -> WorkflowRun:
        if status not in {RunStatus.FAILED, RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
            raise ValueError("finish_run requires a terminal RunStatus")
        run = self._run(run_id)
        require_transition(run.status, status)
        finished = self.repositories.runs.update_status(run_id, status)
        task = self._task(run.task_id)
        if status is RunStatus.SUCCEEDED:
            require_transition(task.status, UserTaskStatus.COMPLETED)
            self.repositories.user_tasks.update_status(task.task_id, UserTaskStatus.COMPLETED)
        elif status is RunStatus.FAILED and task.status is UserTaskStatus.RUNNING:
            require_transition(task.status, UserTaskStatus.READY)
            self.repositories.user_tasks.update_status(task.task_id, UserTaskStatus.READY)
        return finished

    def _task(self, task_id: UserTaskId) -> UserTask:
        task = self.repositories.user_tasks.get(task_id)
        if task is None:
            raise EntityNotFoundError(f"UserTask not found: {task_id}")
        return task

    def _node(self, node_id: TaskNodeId) -> TaskNode:
        node = self.repositories.task_nodes.get(node_id)
        if node is None:
            raise EntityNotFoundError(f"TaskNode not found: {node_id}")
        return node

    def _blueprint(self, blueprint_id: BlueprintId) -> AcgBlueprint:
        blueprint = self.repositories.blueprints.get(blueprint_id)
        if blueprint is None:
            raise EntityNotFoundError(f"AcgBlueprint not found: {blueprint_id}")
        return blueprint

    def _run(self, run_id: RunId) -> WorkflowRun:
        run = self.repositories.runs.get(run_id)
        if run is None:
            raise EntityNotFoundError(f"WorkflowRunV2 not found: {run_id}")
        return run

    def _attempt(self, attempt_id: AttemptId) -> Attempt:
        attempt = self.repositories.attempts.get(attempt_id)
        if attempt is None:
            raise EntityNotFoundError(f"Attempt not found: {attempt_id}")
        return attempt


__all__ = ["WorkflowRuntimeV2"]
