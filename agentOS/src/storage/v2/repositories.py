"""六类新领域 Repository 的 SQLite 实现。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

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
from domain.identity_graph.bindings import (
    BlueprintNodeBinding,
    ExecutionBinding,
    ProvenanceLink,
    TaskNodeBinding,
)
from domain.repository.errors import EntityNotFoundError, IdentityConflictError

from .sqlite import SQLiteV2Storage


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _SQLiteRepository:
    def __init__(self, storage: SQLiteV2Storage) -> None:
        self.storage = storage

    def _insert(self, sql: str, params: tuple[Any, ...], *, entity: str) -> None:
        try:
            with self.storage.transaction() as conn:
                conn.execute(sql, params)
        except sqlite3.IntegrityError as exc:
            raise IdentityConflictError(f"cannot persist {entity}: {exc}") from exc


class SQLiteUserTaskRepository(_SQLiteRepository):
    def add(self, task: UserTask) -> None:
        self._insert(
            """INSERT INTO user_tasks(
                task_id, user_id, goal, description, status, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.task_id,
                task.user_id,
                task.goal,
                task.description,
                task.status.value,
                _json(task.metadata),
                _iso(task.created_at),
                _iso(task.updated_at),
            ),
            entity="UserTask",
        )

    def get(self, task_id: UserTaskId) -> UserTask | None:
        with self.storage.read() as conn:
            row = conn.execute("SELECT * FROM user_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return UserTask(
            taskId=row["task_id"],
            userId=row["user_id"],
            goal=row["goal"],
            description=row["description"],
            status=row["status"],
            metadata=_load_json(row["metadata_json"], {}),
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    def update_status(self, task_id: UserTaskId, status: UserTaskStatus) -> UserTask:
        updated_at = _now()
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                "UPDATE user_tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status.value, _iso(updated_at), task_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"UserTask not found: {task_id}")
        task = self.get(task_id)
        assert task is not None
        return task


class SQLiteTaskNodeRepository(_SQLiteRepository):
    def add(self, node: TaskNode) -> None:
        self._insert(
            """INSERT INTO task_nodes(
                node_id, task_id, parent_node_id, title, objective,
                constraints_json, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                node.node_id,
                node.task_id,
                node.parent_node_id,
                node.title,
                node.objective,
                _json(node.constraints),
                node.status.value,
                _json(node.metadata),
            ),
            entity="TaskNode",
        )

    def get(self, node_id: TaskNodeId) -> TaskNode | None:
        with self.storage.read() as conn:
            row = conn.execute("SELECT * FROM task_nodes WHERE node_id = ?", (node_id,)).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_task(self, task_id: UserTaskId) -> list[TaskNode]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM task_nodes WHERE task_id = ? ORDER BY rowid", (task_id,)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TaskNode:
        return TaskNode(
            nodeId=row["node_id"],
            taskId=row["task_id"],
            parentNodeId=row["parent_node_id"],
            title=row["title"],
            objective=row["objective"],
            constraints=_load_json(row["constraints_json"], []),
            status=row["status"],
            metadata=_load_json(row["metadata_json"], {}),
        )


class SQLiteBlueprintRepository(_SQLiteRepository):
    def add(self, blueprint: AcgBlueprint) -> None:
        self._insert(
            """INSERT INTO acg_blueprints(
                blueprint_id, task_id, version, graph_id, graph_json, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                blueprint.blueprint_id,
                blueprint.task_id,
                blueprint.version,
                blueprint.graph_id,
                _json(blueprint.graph),
                _iso(blueprint.created_at),
                _json(blueprint.metadata),
            ),
            entity="AcgBlueprint",
        )

    def get(self, blueprint_id: BlueprintId) -> AcgBlueprint | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM acg_blueprints WHERE blueprint_id = ?", (blueprint_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_task(self, task_id: UserTaskId) -> list[AcgBlueprint]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM acg_blueprints WHERE task_id = ? ORDER BY version", (task_id,)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AcgBlueprint:
        return AcgBlueprint(
            blueprintId=row["blueprint_id"],
            taskId=row["task_id"],
            version=row["version"],
            graphId=row["graph_id"],
            graph=_load_json(row["graph_json"], {}),
            createdAt=row["created_at"],
            metadata=_load_json(row["metadata_json"], {}),
        )


class SQLiteRunRepository(_SQLiteRepository):
    def add(self, run: WorkflowRun) -> None:
        self._insert(
            """INSERT INTO workflow_runs_v2(
                run_id, task_id, blueprint_id, status, graph_version, checkpoint_json,
                started_at, finished_at, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.run_id,
                run.task_id,
                run.blueprint_id,
                run.status.value,
                run.graph_version,
                _json(run.checkpoint) if run.checkpoint is not None else None,
                _iso(run.started_at),
                _iso(run.finished_at),
                _iso(run.created_at),
                _iso(run.updated_at),
                _json(run.metadata),
            ),
            entity="WorkflowRunV2",
        )

    def get(self, run_id: RunId) -> WorkflowRun | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs_v2 WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_task(self, task_id: UserTaskId) -> list[WorkflowRun]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs_v2 WHERE task_id = ? ORDER BY created_at, run_id",
                (task_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update_blueprint(
        self, run_id: RunId, blueprint_id: BlueprintId, graph_version: int
    ) -> WorkflowRun:
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                """UPDATE workflow_runs_v2
                   SET blueprint_id = ?, graph_version = ?, updated_at = ?
                   WHERE run_id = ?""",
                (blueprint_id, graph_version, _iso(_now()), run_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"WorkflowRunV2 not found: {run_id}")
        run = self.get(run_id)
        assert run is not None
        return run

    def update_status(self, run_id: RunId, status: RunStatus) -> WorkflowRun:
        now = _now()
        started_at = _iso(now) if status is RunStatus.RUNNING else None
        finished_at = _iso(now) if status in {
            RunStatus.FAILED,
            RunStatus.SUCCEEDED,
            RunStatus.CANCELLED,
        } else None
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                """UPDATE workflow_runs_v2
                   SET status = ?,
                       started_at = COALESCE(started_at, ?),
                       finished_at = COALESCE(?, finished_at),
                       updated_at = ?
                   WHERE run_id = ?""",
                (status.value, started_at, finished_at, _iso(now), run_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"WorkflowRunV2 not found: {run_id}")
        run = self.get(run_id)
        assert run is not None
        return run

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowRun:
        return WorkflowRun(
            runId=row["run_id"],
            taskId=row["task_id"],
            blueprintId=row["blueprint_id"],
            status=row["status"],
            graphVersion=row["graph_version"],
            checkpoint=_load_json(row["checkpoint_json"], None),
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
            metadata=_load_json(row["metadata_json"], {}),
        )


class SQLiteAttemptRepository(_SQLiteRepository):
    def add(self, attempt: Attempt) -> None:
        self._insert(
            """INSERT INTO attempts(
                attempt_id, run_id, node_id, attempt_number, status, started_at,
                finished_at, failure_reason, resource_binding_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt.attempt_id,
                attempt.run_id,
                attempt.node_id,
                attempt.attempt_number,
                attempt.status.value,
                _iso(attempt.started_at),
                _iso(attempt.finished_at),
                attempt.failure_reason,
                _json(attempt.resource_binding) if attempt.resource_binding is not None else None,
            ),
            entity="Attempt",
        )

    def get(self, attempt_id: AttemptId) -> Attempt | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_run(self, run_id: RunId) -> list[Attempt]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM attempts WHERE run_id = ? ORDER BY attempt_number, rowid",
                (run_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update_status(
        self,
        attempt_id: AttemptId,
        status: AttemptStatus,
        *,
        failure_reason: str | None = None,
    ) -> Attempt:
        now = _now()
        started_at = _iso(now) if status is AttemptStatus.RUNNING else None
        finished_at = _iso(now) if status in {
            AttemptStatus.FAILED,
            AttemptStatus.SUCCEEDED,
            AttemptStatus.CANCELLED,
        } else None
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                """UPDATE attempts
                   SET status = ?,
                       started_at = COALESCE(started_at, ?),
                       finished_at = COALESCE(?, finished_at),
                       failure_reason = COALESCE(?, failure_reason)
                   WHERE attempt_id = ?""",
                (status.value, started_at, finished_at, failure_reason, attempt_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"Attempt not found: {attempt_id}")
        attempt = self.get(attempt_id)
        assert attempt is not None
        return attempt

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Attempt:
        return Attempt(
            attemptId=row["attempt_id"],
            runId=row["run_id"],
            nodeId=row["node_id"],
            attemptNumber=row["attempt_number"],
            status=row["status"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            failureReason=row["failure_reason"],
            resourceBinding=_load_json(row["resource_binding_json"], None),
        )


class SQLiteStepExecutionRepository(_SQLiteRepository):
    def add(self, execution: StepExecution) -> None:
        self._insert(
            """INSERT INTO step_executions(
                step_execution_id, attempt_id, run_id, node_id, input_json,
                output_json, status, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                execution.step_execution_id,
                execution.attempt_id,
                execution.run_id,
                execution.node_id,
                _json(execution.input),
                _json(execution.output),
                execution.status.value,
                _iso(execution.started_at),
                _iso(execution.finished_at),
            ),
            entity="StepExecution",
        )

    def get(self, step_execution_id: StepExecutionId) -> StepExecution | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM step_executions WHERE step_execution_id = ?",
                (step_execution_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_attempt(self, attempt_id: AttemptId) -> list[StepExecution]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM step_executions WHERE attempt_id = ? ORDER BY rowid",
                (attempt_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StepExecution:
        return StepExecution(
            stepExecutionId=row["step_execution_id"],
            attemptId=row["attempt_id"],
            runId=row["run_id"],
            nodeId=row["node_id"],
            input=_load_json(row["input_json"], {}),
            output=_load_json(row["output_json"], {}),
            status=row["status"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
        )


def _blueprint_node_ids(conn: sqlite3.Connection, blueprint_id: BlueprintId) -> set[str]:
    row = conn.execute(
        "SELECT graph_json FROM acg_blueprints WHERE blueprint_id = ?", (blueprint_id,)
    ).fetchone()
    if row is None:
        return set()
    graph = _load_json(row["graph_json"], {})
    return {
        str(node.get("nodeId") or "")
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("nodeId")
    }


class SQLiteTaskNodeBindingRepository(_SQLiteRepository):
    def add(self, binding: TaskNodeBinding) -> None:
        try:
            with self.storage.transaction() as conn:
                if binding.acg_node_id not in _blueprint_node_ids(conn, binding.blueprint_id):
                    raise IdentityConflictError("ACGNode is not contained by the Blueprint")
                conn.execute(
                    """INSERT INTO task_node_bindings(
                        binding_id, task_node_id, blueprint_id, acg_node_id,
                        binding_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        binding.binding_id,
                        binding.task_node_id,
                        binding.blueprint_id,
                        binding.acg_node_id,
                        binding.binding_type.value,
                        _iso(binding.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityConflictError(f"cannot persist TaskNodeBinding: {exc}") from exc

    def get(self, binding_id: str) -> TaskNodeBinding | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM task_node_bindings WHERE binding_id = ?", (binding_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def find_for_task_node(
        self, task_node_id: TaskNodeId, blueprint_id: BlueprintId
    ) -> list[TaskNodeBinding]:
        with self.storage.read() as conn:
            rows = conn.execute(
                """SELECT * FROM task_node_bindings
                   WHERE task_node_id = ? AND blueprint_id = ? ORDER BY created_at, binding_id""",
                (task_node_id, blueprint_id),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def find_for_acg_node(
        self, acg_node_id: str, blueprint_id: BlueprintId
    ) -> list[TaskNodeBinding]:
        with self.storage.read() as conn:
            rows = conn.execute(
                """SELECT * FROM task_node_bindings
                   WHERE acg_node_id = ? AND blueprint_id = ? ORDER BY created_at, binding_id""",
                (acg_node_id, blueprint_id),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TaskNodeBinding:
        return TaskNodeBinding(
            bindingId=row["binding_id"],
            taskNodeId=row["task_node_id"],
            blueprintId=row["blueprint_id"],
            acgNodeId=row["acg_node_id"],
            bindingType=row["binding_type"],
            createdAt=row["created_at"],
        )


class SQLiteBlueprintNodeBindingRepository(_SQLiteRepository):
    def add(self, binding: BlueprintNodeBinding) -> None:
        try:
            with self.storage.transaction() as conn:
                nodes = _blueprint_node_ids(conn, binding.blueprint_id)
                if binding.source_node_id not in nodes or binding.target_node_id not in nodes:
                    raise IdentityConflictError("Blueprint relation endpoint is not contained by Blueprint")
                conn.execute(
                    """INSERT INTO blueprint_node_bindings(
                        binding_id, blueprint_id, source_node_id, target_node_id, relation_type
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        binding.binding_id,
                        binding.blueprint_id,
                        binding.source_node_id,
                        binding.target_node_id,
                        binding.relation_type.value,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityConflictError(f"cannot persist BlueprintNodeBinding: {exc}") from exc

    def list_for_blueprint(self, blueprint_id: BlueprintId) -> list[BlueprintNodeBinding]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM blueprint_node_bindings WHERE blueprint_id = ? ORDER BY rowid",
                (blueprint_id,),
            ).fetchall()
        return [
            BlueprintNodeBinding(
                bindingId=row["binding_id"],
                blueprintId=row["blueprint_id"],
                sourceNodeId=row["source_node_id"],
                targetNodeId=row["target_node_id"],
                relationType=row["relation_type"],
            )
            for row in rows
        ]


class SQLiteExecutionBindingRepository(_SQLiteRepository):
    def add(self, binding: ExecutionBinding) -> None:
        self._insert(
            """INSERT INTO execution_bindings(
                binding_id, attempt_id, acg_node_id, resource_id, agent_id,
                model_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                binding.binding_id,
                binding.attempt_id,
                binding.acg_node_id,
                binding.resource_id,
                binding.agent_id,
                binding.model_id,
                _json(binding.metadata),
                _iso(binding.created_at),
            ),
            entity="ExecutionBinding",
        )

    def get_for_attempt(self, attempt_id: AttemptId) -> ExecutionBinding | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM execution_bindings WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            return None
        return ExecutionBinding(
            bindingId=row["binding_id"],
            attemptId=row["attempt_id"],
            acgNodeId=row["acg_node_id"],
            resourceId=row["resource_id"],
            agentId=row["agent_id"],
            modelId=row["model_id"],
            metadata=_load_json(row["metadata_json"], {}),
            createdAt=row["created_at"],
        )


class SQLiteProvenanceLinkRepository(_SQLiteRepository):
    def add(self, link: ProvenanceLink) -> None:
        self._insert(
            """INSERT INTO provenance_links(
                source_id, target_id, relation_type, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                link.source_id,
                link.target_id,
                link.relation_type.value,
                _json(link.metadata),
                _iso(link.created_at),
            ),
            entity="ProvenanceLink",
        )

    def list_from(self, source_id: str) -> list[ProvenanceLink]:
        return self._list("source_id", source_id)

    def list_to(self, target_id: str) -> list[ProvenanceLink]:
        return self._list("target_id", target_id)

    def _list(self, column: str, identity: str) -> list[ProvenanceLink]:
        with self.storage.read() as conn:
            rows = conn.execute(
                f"SELECT * FROM provenance_links WHERE {column} = ? ORDER BY created_at, rowid",
                (identity,),
            ).fetchall()
        return [
            ProvenanceLink(
                sourceId=row["source_id"],
                targetId=row["target_id"],
                relationType=row["relation_type"],
                metadata=_load_json(row["metadata_json"], {}),
                createdAt=row["created_at"],
            )
            for row in rows
        ]


class SQLiteV2Repositories:
    """显式聚合六个 Repository，供 WorkflowRuntimeV2 依赖注入。"""

    def __init__(self, storage: SQLiteV2Storage) -> None:
        self.storage = storage
        self.user_tasks = SQLiteUserTaskRepository(storage)
        self.task_nodes = SQLiteTaskNodeRepository(storage)
        self.blueprints = SQLiteBlueprintRepository(storage)
        self.runs = SQLiteRunRepository(storage)
        self.attempts = SQLiteAttemptRepository(storage)
        self.step_executions = SQLiteStepExecutionRepository(storage)
        self.task_node_bindings = SQLiteTaskNodeBindingRepository(storage)
        self.blueprint_node_bindings = SQLiteBlueprintNodeBindingRepository(storage)
        self.execution_bindings = SQLiteExecutionBindingRepository(storage)
        self.provenance_links = SQLiteProvenanceLinkRepository(storage)

    def finish_execution(
        self,
        step_execution_id: StepExecutionId,
        attempt_id: AttemptId,
        *,
        step_status: StepExecutionStatus,
        attempt_status: AttemptStatus,
        output: dict,
        failure_reason: str | None = None,
    ) -> tuple[StepExecution, Attempt]:
        if step_status not in {
            StepExecutionStatus.FAILED,
            StepExecutionStatus.SUCCEEDED,
            StepExecutionStatus.CANCELLED,
        }:
            raise ValueError("execution transaction requires a terminal StepExecution status")
        if attempt_status not in {
            AttemptStatus.FAILED,
            AttemptStatus.SUCCEEDED,
            AttemptStatus.CANCELLED,
        }:
            raise ValueError("execution transaction requires a terminal Attempt status")
        finished_at = _iso(_now())
        with self.storage.transaction() as conn:
            execution_cursor = conn.execute(
                """UPDATE step_executions
                   SET status = ?, output_json = ?, finished_at = ?
                   WHERE step_execution_id = ? AND attempt_id = ? AND status = 'running'""",
                (step_status.value, _json(output), finished_at, step_execution_id, attempt_id),
            )
            if execution_cursor.rowcount != 1:
                raise EntityNotFoundError(
                    f"running StepExecution not found: {step_execution_id}"
                )
            attempt_cursor = conn.execute(
                """UPDATE attempts
                   SET status = ?, finished_at = ?, failure_reason = COALESCE(?, failure_reason)
                   WHERE attempt_id = ? AND status = 'running'""",
                (attempt_status.value, finished_at, failure_reason, attempt_id),
            )
            if attempt_cursor.rowcount != 1:
                raise EntityNotFoundError(f"running Attempt not found: {attempt_id}")
        execution = self.step_executions.get(step_execution_id)
        attempt = self.attempts.get(attempt_id)
        assert execution is not None and attempt is not None
        return execution, attempt

    def close(self) -> None:
        self.storage.close()


__all__ = [
    "SQLiteAttemptRepository",
    "SQLiteBlueprintNodeBindingRepository",
    "SQLiteBlueprintRepository",
    "SQLiteExecutionBindingRepository",
    "SQLiteProvenanceLinkRepository",
    "SQLiteRunRepository",
    "SQLiteStepExecutionRepository",
    "SQLiteTaskNodeRepository",
    "SQLiteTaskNodeBindingRepository",
    "SQLiteUserTaskRepository",
    "SQLiteV2Repositories",
]
