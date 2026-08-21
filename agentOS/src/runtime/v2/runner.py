"""只编排新身份链和持久化的 WorkflowRuntimeV2。"""

from __future__ import annotations

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
    """AgentOS V2 身份与生命周期控制面；实际执行始终由 WKN ACG 内核完成。"""

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
        task_id: UserTaskId | None = None,
    ) -> UserTask:
        task = UserTask(
            **({"taskId": task_id} if task_id is not None else {}),
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
        run_id: RunId | None = None,
    ) -> WorkflowRun:
        self._task(task_id)
        blueprint = self._blueprint(blueprint_id)
        if blueprint.task_id != task_id:
            raise IdentityConflictError("WorkflowRun cannot use another UserTask's Blueprint")
        run = WorkflowRun(
            **({"runId": run_id} if run_id is not None else {}),
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
        active = [
            execution.step_execution_id
            for attempt in attempts
            for execution in self.repositories.step_executions.list_for_attempt(
                attempt.attempt_id
            )
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

    def start_step_execution(
        self,
        context: ExecutionContext,
        *,
        input: dict[str, Any],
        attempt_id: AttemptId | None = None,
    ) -> StepExecution:
        selected_attempt_id = attempt_id or context.current_attempt
        if selected_attempt_id is None:
            raise ValueError("ExecutionContext has no current Attempt")
        run = self._run(context.run_id)
        attempt = self._attempt(selected_attempt_id)
        if (
            run.task_id != context.task_id
            or run.blueprint_id != context.blueprint_id
            or attempt.run_id != context.run_id
        ):
            raise IdentityConflictError("ExecutionContext identity chain is inconsistent")
        if self.repositories.execution_bindings.get_for_attempt(attempt.attempt_id) is None:
            raise EntityNotFoundError("WorkflowRuntimeV2 requires a persisted ExecutionBinding")
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
        return execution

    def complete_step_execution(
        self,
        context: ExecutionContext,
        step_execution_id: str,
        *,
        output: dict[str, Any],
    ) -> StepExecution:
        execution = self._active_execution(context, step_execution_id)
        execution, _ = self.repositories.finish_execution(
            execution.step_execution_id,
            execution.attempt_id,
            step_status=StepExecutionStatus.SUCCEEDED,
            attempt_status=AttemptStatus.SUCCEEDED,
            output=output,
        )
        context.active_executions.remove(execution.step_execution_id)
        return execution

    def fail_step_execution(
        self,
        context: ExecutionContext,
        step_execution_id: str,
        *,
        failure_reason: str,
        output: dict[str, Any] | None = None,
    ) -> StepExecution:
        execution = self._active_execution(context, step_execution_id)
        execution, _ = self.repositories.finish_execution(
            execution.step_execution_id,
            execution.attempt_id,
            step_status=StepExecutionStatus.FAILED,
            attempt_status=AttemptStatus.FAILED,
            output=output or {},
            failure_reason=failure_reason,
        )
        context.active_executions.remove(execution.step_execution_id)
        return execution

    def cancel_step_execution(
        self,
        context: ExecutionContext,
        step_execution_id: str,
        *,
        reason: str,
    ) -> StepExecution:
        execution = self._active_execution(context, step_execution_id)
        execution, _ = self.repositories.finish_execution(
            execution.step_execution_id,
            execution.attempt_id,
            step_status=StepExecutionStatus.CANCELLED,
            attempt_status=AttemptStatus.CANCELLED,
            output={},
            failure_reason=reason,
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
        if status is RunStatus.SUCCEEDED and task.status is UserTaskStatus.RUNNING:
            require_transition(task.status, UserTaskStatus.COMPLETED)
            self.repositories.user_tasks.update_status(task.task_id, UserTaskStatus.COMPLETED)
        elif (
            status in {RunStatus.FAILED, RunStatus.CANCELLED}
            and task.status is UserTaskStatus.RUNNING
        ):
            other_active_runs = any(
                item.run_id != run_id and item.status is RunStatus.RUNNING
                for item in self.repositories.runs.list_for_task(task.task_id)
            )
            if not other_active_runs:
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

    def _active_execution(
        self,
        context: ExecutionContext,
        step_execution_id: str,
    ) -> StepExecution:
        if step_execution_id not in context.active_executions:
            raise IdentityConflictError("StepExecution is not active in this ExecutionContext")
        execution = self.repositories.step_executions.get(step_execution_id)
        if execution is None:
            raise EntityNotFoundError(f"StepExecution not found: {step_execution_id}")
        if execution.run_id != context.run_id:
            raise IdentityConflictError("StepExecution identity chain is inconsistent")
        return execution


__all__ = ["WorkflowRuntimeV2"]
