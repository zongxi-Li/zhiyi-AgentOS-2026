"""AgentOS V2 身份图 Repository 的 SQLite 实现。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Sequence

from contracts.identity import (
    AttemptId,
    ArtifactId,
    BlueprintId,
    RunId,
    StepExecutionId,
    TaskId,
    MissionId,
    new_attempt_id,
    new_task_id,
    new_step_execution_id,
    validate_logical_key,
)
from contracts.planning import TaskPlan, PlannedTask, TaskPlanRelation
from contracts.attachments import InputAttachment, InputAttachmentStatus
from domain.models import (
    AcgBlueprint,
    Attempt,
    AttemptStatus,
    Artifact,
    RunStatus,
    StepExecution,
    StepExecutionStatus,
    SemanticTask,
    Mission,
    MissionStatus,
    WorkflowRun,
)
from domain.identity_graph.bindings import (
    BlueprintNodeBinding,
    ExecutionBinding,
    ProvenanceLink,
    ResourceUsageRecord,
    RunArtifactBinding,
    RunArtifactDisposition,
    TaskBinding,
)
from domain.lifecycle_projection import LifecycleProjectionEvent
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


class SQLiteInputAttachmentRepository(_SQLiteRepository):
    """Identity and Mission/Run reference authority for uploaded inputs."""

    def add(self, attachment: InputAttachment) -> InputAttachment:
        self._insert(
            """INSERT INTO input_attachments
            (attachment_id, owner_user_id, owner_tenant_id, original_filename,
             storage_key, mime_type, extension, size_bytes, sha256, status,
             extracted_content_ref, character_count, parser, metadata_json,
             parse_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attachment.attachment_id, attachment.owner_user_id,
                attachment.owner_tenant_id, attachment.original_filename,
                attachment.storage_key, attachment.mime_type, attachment.extension,
                attachment.size_bytes, attachment.sha256, attachment.status.value,
                attachment.extracted_content_ref, attachment.character_count,
                attachment.parser, _json(attachment.metadata), attachment.parse_error,
                _iso(attachment.created_at), _iso(attachment.updated_at),
            ),
            entity="InputAttachment",
        )
        return self.get_required(attachment.attachment_id)

    def get(self, attachment_id: str) -> InputAttachment | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM input_attachments WHERE attachment_id = ?", (attachment_id,)
            ).fetchone()
        return self._attachment(row) if row is not None else None

    def get_required(self, attachment_id: str) -> InputAttachment:
        attachment = self.get(attachment_id)
        if attachment is None:
            raise EntityNotFoundError(f"InputAttachment not found: {attachment_id}")
        return attachment

    def update_status(self, attachment_id: str, status: InputAttachmentStatus) -> None:
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                "UPDATE input_attachments SET status = ?, updated_at = ? WHERE attachment_id = ?",
                (status.value, _iso(_now()), attachment_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"InputAttachment not found: {attachment_id}")

    def mark_ready(self, attachment_id: str, *, extracted_content_ref: str,
                   character_count: int, parser: str, metadata: dict[str, Any]) -> None:
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                """UPDATE input_attachments SET status = 'READY', extracted_content_ref = ?,
                character_count = ?, parser = ?, metadata_json = ?, parse_error = NULL,
                updated_at = ? WHERE attachment_id = ?""",
                (extracted_content_ref, character_count, parser, _json(metadata),
                 _iso(_now()), attachment_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"InputAttachment not found: {attachment_id}")

    def mark_failed(self, attachment_id: str, parse_error: str) -> None:
        with self.storage.transaction() as conn:
            conn.execute(
                """UPDATE input_attachments SET status = 'FAILED', parse_error = ?,
                updated_at = ? WHERE attachment_id = ?""",
                (parse_error[:1000], _iso(_now()), attachment_id),
            )

    def bind_mission(self, mission_id: str, attachment_ids: Sequence[str]) -> None:
        requested = list(dict.fromkeys(attachment_ids))
        with self.storage.transaction() as conn:
            current = [str(row["attachment_id"]) for row in conn.execute(
                "SELECT attachment_id FROM mission_input_attachments WHERE mission_id = ? ORDER BY ordinal",
                (mission_id,),
            ).fetchall()]
            if current and current != requested:
                raise IdentityConflictError("Mission input attachment references changed unexpectedly")
            for ordinal, attachment_id in enumerate(requested):
                conn.execute(
                    """INSERT OR IGNORE INTO mission_input_attachments
                    (mission_id, attachment_id, ordinal, created_at) VALUES (?, ?, ?, ?)""",
                    (mission_id, attachment_id, ordinal, _iso(_now())),
                )

    def bind_run(self, run_id: str, attachment_ids: Sequence[str]) -> None:
        requested = list(dict.fromkeys(attachment_ids))
        with self.storage.transaction() as conn:
            current = [str(row["attachment_id"]) for row in conn.execute(
                "SELECT attachment_id FROM run_input_attachments WHERE run_id = ? ORDER BY ordinal",
                (run_id,),
            ).fetchall()]
            if current and current != requested:
                raise IdentityConflictError("Run input attachment snapshot is immutable")
            for ordinal, attachment_id in enumerate(requested):
                conn.execute(
                    """INSERT OR IGNORE INTO run_input_attachments
                    (run_id, attachment_id, ordinal, created_at) VALUES (?, ?, ?, ?)""",
                    (run_id, attachment_id, ordinal, _iso(_now())),
                )

    def list_for_mission(self, mission_id: str) -> list[InputAttachment]:
        return self._list_join(
            """SELECT a.* FROM mission_input_attachments b JOIN input_attachments a
            ON a.attachment_id = b.attachment_id WHERE b.mission_id = ?
            ORDER BY b.ordinal""", mission_id)

    def list_for_run(self, run_id: str) -> list[InputAttachment]:
        return self._list_join(
            """SELECT a.* FROM run_input_attachments b JOIN input_attachments a
            ON a.attachment_id = b.attachment_id WHERE b.run_id = ? ORDER BY b.ordinal""",
            run_id)

    def _list_join(self, sql: str, identity: str) -> list[InputAttachment]:
        with self.storage.read() as conn:
            return [self._attachment(row) for row in conn.execute(sql, (identity,)).fetchall()]

    def total_unbound_bytes(self, owner_user_id: str) -> int:
        with self.storage.read() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(a.size_bytes), 0) AS total FROM input_attachments a
                WHERE a.owner_user_id = ?
                AND NOT EXISTS (SELECT 1 FROM mission_input_attachments m WHERE m.attachment_id = a.attachment_id)
                AND NOT EXISTS (SELECT 1 FROM run_input_attachments r WHERE r.attachment_id = a.attachment_id)""",
                (owner_user_id,),
            ).fetchone()
        return int(row["total"])

    def is_referenced(self, attachment_id: str) -> bool:
        with self.storage.read() as conn:
            row = conn.execute(
                """SELECT EXISTS(SELECT 1 FROM mission_input_attachments WHERE attachment_id = ?)
                OR EXISTS(SELECT 1 FROM run_input_attachments WHERE attachment_id = ?) AS used""",
                (attachment_id, attachment_id),
            ).fetchone()
        return bool(row["used"])

    def delete(self, attachment_id: str) -> None:
        with self.storage.transaction() as conn:
            cursor = conn.execute("DELETE FROM input_attachments WHERE attachment_id = ?", (attachment_id,))
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"InputAttachment not found: {attachment_id}")

    @staticmethod
    def _attachment(row: sqlite3.Row) -> InputAttachment:
        return InputAttachment(
            attachmentId=row["attachment_id"], ownerUserId=row["owner_user_id"],
            ownerTenantId=row["owner_tenant_id"], originalFilename=row["original_filename"],
            storageKey=row["storage_key"], mimeType=row["mime_type"], extension=row["extension"],
            sizeBytes=row["size_bytes"], sha256=row["sha256"], status=row["status"],
            extractedContentRef=row["extracted_content_ref"], characterCount=row["character_count"],
            parser=row["parser"], metadata=_load_json(row["metadata_json"], {}),
            parseError=row["parse_error"], createdAt=row["created_at"], updatedAt=row["updated_at"],
        )


class SQLiteMissionRepository(_SQLiteRepository):
    @staticmethod
    def _from_row(row: sqlite3.Row) -> Mission:
        return Mission(
            missionId=row["mission_id"],
            userId=row["user_id"],
            goal=row["goal"],
            description=row["description"],
            status=row["status"],
            metadata=_load_json(row["metadata_json"], {}),
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    def add(self, task: Mission) -> None:
        self._insert(
            """INSERT INTO missions(
                mission_id, user_id, goal, description, status, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.mission_id,
                task.user_id,
                task.goal,
                task.description,
                task.status.value,
                _json(task.metadata),
                _iso(task.created_at),
                _iso(task.updated_at),
            ),
            entity="Mission",
        )

    def get(self, mission_id: MissionId) -> Mission | None:
        with self.storage.read() as conn:
            row = conn.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,)).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def list(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: MissionStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Mission], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if tenant_id is not None:
            clauses.append(
                "(json_extract(metadata_json, '$.tenantId') IS NULL "
                "OR json_extract(metadata_json, '$.tenantId') = '' "
                "OR json_extract(metadata_json, '$.tenantId') = ?)"
            )
            params.append(tenant_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.storage.read() as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM missions{where}",
                tuple(params),
            ).fetchone()[0])
            rows = conn.execute(
                f"""SELECT * FROM missions{where}
                    ORDER BY updated_at DESC, mission_id DESC LIMIT ? OFFSET ?""",
                (*params, max(1, limit), max(0, offset)),
            ).fetchall()
        return ([self._from_row(row) for row in rows], total)

    def update_status(self, mission_id: MissionId, status: MissionStatus) -> Mission:
        updated_at = _now()
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                "UPDATE missions SET status = ?, updated_at = ? WHERE mission_id = ?",
                (status.value, _iso(updated_at), mission_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"Mission not found: {mission_id}")
        task = self.get(mission_id)
        assert task is not None
        return task


class SQLiteSemanticTaskRepository(_SQLiteRepository):
    def add(self, node: SemanticTask) -> None:
        self._insert(
            """INSERT INTO semantic_tasks(
                task_id, mission_id, semantic_key, parent_task_id, title, objective,
                constraints_json, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                node.task_id,
                node.mission_id,
                node.semantic_task_key,
                node.parent_task_id,
                node.title,
                node.objective,
                _json(node.constraints),
                node.status.value,
                _json(node.metadata),
            ),
            entity="SemanticTask",
        )

    def get(self, task_id: TaskId) -> SemanticTask | None:
        with self.storage.read() as conn:
            row = conn.execute("SELECT * FROM semantic_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_mission(self, mission_id: MissionId) -> list[SemanticTask]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM semantic_tasks WHERE mission_id = ? ORDER BY rowid", (mission_id,)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> SemanticTask:
        return SemanticTask(
            taskId=row["task_id"],
            missionId=row["mission_id"],
            parentTaskId=row["parent_task_id"],
            semanticTaskKey=row["semantic_key"],
            title=row["title"],
            objective=row["objective"],
            constraints=_load_json(row["constraints_json"], []),
            status=row["status"],
            metadata=_load_json(row["metadata_json"], {}),
        )


class SQLiteTaskPlanRepository(_SQLiteRepository):
    """Immutable, versioned semantic plan snapshots."""

    def add(self, plan: TaskPlan, node_ids: dict[str, str]) -> None:
        payload = plan.model_dump(by_alias=True, mode="json")
        encoded = _json(payload)
        import hashlib
        content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self.storage.transaction() as conn:
            conn.execute(
                """INSERT INTO task_plans(mission_id, plan_version, payload_json, content_hash, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (plan.mission_id, plan.plan_version, encoded, content_hash, _iso(_now())),
            )
            for node in plan.nodes:
                conn.execute(
                    """INSERT INTO task_plan_nodes(
                           mission_id, plan_version, semantic_key, task_id, payload_json
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        plan.mission_id,
                        plan.plan_version,
                        node.key,
                        node_ids.get(node.key),
                        _json(node.model_dump(by_alias=True, mode="json")),
                    ),
                )
            for relation in plan.relations:
                conn.execute(
                    """INSERT INTO task_plan_relations(
                           mission_id, plan_version, source_key, target_key, relation_type
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        plan.mission_id,
                        plan.plan_version,
                        relation.source_key,
                        relation.target_key,
                        relation.relation_type.value,
                    ),
                )

    def get(self, mission_id: MissionId, plan_version: int) -> TaskPlan | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT payload_json FROM task_plans WHERE mission_id = ? AND plan_version = ?",
                (mission_id, plan_version),
            ).fetchone()
        return TaskPlan.model_validate(_load_json(row["payload_json"], {})) if row else None

    def latest(self, mission_id: MissionId) -> TaskPlan | None:
        with self.storage.read() as conn:
            row = conn.execute(
                """SELECT payload_json FROM task_plans
                   WHERE mission_id = ? ORDER BY plan_version DESC LIMIT 1""",
                (mission_id,),
            ).fetchone()
        return TaskPlan.model_validate(_load_json(row["payload_json"], {})) if row else None

    def list_for_mission(self, mission_id: MissionId) -> list[TaskPlan]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM task_plans WHERE mission_id = ? ORDER BY plan_version",
                (mission_id,),
            ).fetchall()
        return [TaskPlan.model_validate(_load_json(row["payload_json"], {})) for row in rows]

class SQLiteBlueprintRepository(_SQLiteRepository):
    def add(self, blueprint: AcgBlueprint) -> None:
        self._insert(
            """INSERT INTO acg_blueprints(
                blueprint_id, mission_id, version, graph_id, graph_json, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                blueprint.blueprint_id,
                blueprint.mission_id,
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

    def list_for_mission(self, mission_id: MissionId) -> list[AcgBlueprint]:
        with self.storage.read() as conn:
            rows = conn.execute(
                "SELECT * FROM acg_blueprints WHERE mission_id = ? ORDER BY version", (mission_id,)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AcgBlueprint:
        return AcgBlueprint(
            blueprintId=row["blueprint_id"],
            missionId=row["mission_id"],
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
                run_id, mission_id, blueprint_id, status, graph_version, checkpoint_json,
                started_at, finished_at, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.run_id,
                run.mission_id,
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

    def list_for_mission(self, mission_id: MissionId) -> list[WorkflowRun]:
        with self.storage.read() as conn:
            rows = conn.execute(
                """SELECT * FROM workflow_runs_v2
                   WHERE mission_id = ?
                     AND COALESCE(json_extract(metadata_json, '$.recordState'), 'active') != 'deleted'
                   ORDER BY rowid""",
                (mission_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_for_missions(
        self, mission_ids: Sequence[MissionId]
    ) -> dict[MissionId, list[WorkflowRun]]:
        requested_ids = tuple(dict.fromkeys(mission_ids))
        if not requested_ids:
            return {}
        placeholders = ", ".join("?" for _ in requested_ids)
        with self.storage.read() as conn:
            rows = conn.execute(
                f"""SELECT * FROM workflow_runs_v2
                    WHERE mission_id IN ({placeholders})
                      AND COALESCE(json_extract(metadata_json, '$.recordState'), 'active') != 'deleted'
                    ORDER BY mission_id, rowid""",
                requested_ids,
            ).fetchall()
        result: dict[MissionId, list[WorkflowRun]] = {mission_id: [] for mission_id in requested_ids}
        for row in rows:
            result[row["mission_id"]].append(self._from_row(row))
        return result

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
            RunStatus.SUPERSEDED,
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

    def reopen_failed(self, run_id: RunId) -> WorkflowRun:
        """Reopen one failed Run for an explicit in-place retry."""
        now = _now()
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                """UPDATE workflow_runs_v2
                   SET status = ?, finished_at = NULL, updated_at = ?
                   WHERE run_id = ? AND status = ?""",
                (RunStatus.PENDING.value, _iso(now), run_id, RunStatus.FAILED.value),
            )
            if cursor.rowcount != 1:
                raise IdentityConflictError("only a failed WorkflowRunV2 can be retried in place")
        run = self.get(run_id)
        assert run is not None
        return run

    def merge_metadata(self, run_id: RunId, metadata: dict[str, Any]) -> WorkflowRun:
        immutable_keys = {
            "compiledPackageId",
            "compiledPackageChecksum",
            "compiledPackageVersion",
            "compiledPackageBlueprintHash",
            "taskPlanVersion",
            "parentRunId",
            "supersedesRunId",
            "sourcePatchId",
        }
        now = _now()
        with self.storage.transaction() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM workflow_runs_v2 WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise EntityNotFoundError(f"WorkflowRunV2 not found: {run_id}")
            current = _load_json(row["metadata_json"], {})
            for key in immutable_keys:
                if (
                    key in current
                    and key in metadata
                    and current[key] != metadata[key]
                ):
                    raise IdentityConflictError(
                        f"immutable Run metadata changed: {key}"
                    )
            merged = {**current, **metadata}
            conn.execute(
                """UPDATE workflow_runs_v2
                   SET metadata_json = ?, updated_at = ? WHERE run_id = ?""",
                (_json(merged), _iso(now), run_id),
            )
        run = self.get(run_id)
        assert run is not None
        return run

    def mark_deleted(self, run_id: RunId) -> WorkflowRun:
        """软删除：把 ``recordState=deleted`` 并入 Run metadata，使其退出全部列表查询。

        只合并不覆盖，后续 lifecycle 投影只更新状态/时间列，不会冲掉该标记。
        """
        return self.merge_metadata(run_id, {"recordState": "deleted"})

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowRun:
        return WorkflowRun(
            runId=row["run_id"],
            missionId=row["mission_id"],
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
                attempt_id, run_id, task_id, attempt_number, status, started_at,
                finished_at, failure_reason, resource_binding_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt.attempt_id,
                attempt.run_id,
                attempt.task_id,
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
            taskId=row["task_id"],
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
                step_execution_id, attempt_id, run_id, task_id, input_json,
                output_json, status, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                execution.step_execution_id,
                execution.attempt_id,
                execution.run_id,
                execution.task_id,
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
            taskId=row["task_id"],
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


class SQLiteTaskBindingRepository(_SQLiteRepository):
    def add(self, binding: TaskBinding) -> None:
        try:
            with self.storage.transaction() as conn:
                if binding.acg_node_id not in _blueprint_node_ids(conn, binding.blueprint_id):
                    raise IdentityConflictError("ACGNode is not contained by the Blueprint")
                conn.execute(
                    """INSERT INTO task_bindings(
                        binding_id, task_id, blueprint_id, acg_node_id,
                        binding_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        binding.binding_id,
                        binding.task_id,
                        binding.blueprint_id,
                        binding.acg_node_id,
                        binding.binding_type.value,
                        _iso(binding.created_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityConflictError(f"cannot persist TaskBinding: {exc}") from exc

    def get(self, binding_id: str) -> TaskBinding | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM task_bindings WHERE binding_id = ?", (binding_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def find_for_task(
        self, task_id: TaskId, blueprint_id: BlueprintId
    ) -> list[TaskBinding]:
        with self.storage.read() as conn:
            rows = conn.execute(
                """SELECT * FROM task_bindings
                   WHERE task_id = ? AND blueprint_id = ? ORDER BY created_at, binding_id""",
                (task_id, blueprint_id),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def find_for_acg_node(
        self, acg_node_id: str, blueprint_id: BlueprintId
    ) -> list[TaskBinding]:
        with self.storage.read() as conn:
            rows = conn.execute(
                """SELECT * FROM task_bindings
                   WHERE acg_node_id = ? AND blueprint_id = ? ORDER BY created_at, binding_id""",
                (acg_node_id, blueprint_id),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TaskBinding:
        return TaskBinding(
            bindingId=row["binding_id"],
            taskId=row["task_id"],
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

    def list_for_resource(self, resource_id: str, *, limit: int = 10) -> list[ResourceUsageRecord]:
        """按绑定时间倒序返回某资源最近的 attempt 使用记录。

        身份图内直接 JOIN attempts 与 semantic_tasks，不触工作流库：
        资源目录只需 runId/attempt 事实，运行状态细节由运行记忆页承担。
        """
        if limit < 1:
            raise ValueError("resource usage limit must be positive")
        with self.storage.read() as conn:
            rows = conn.execute(
                """
                SELECT b.binding_id, b.attempt_id, b.acg_node_id, b.agent_id,
                       b.model_id, b.created_at AS bound_at,
                       a.run_id, a.task_id, a.attempt_number, a.status AS attempt_status,
                       a.started_at, a.finished_at,
                       t.mission_id, t.title AS task_title, t.semantic_key
                FROM execution_bindings b
                JOIN attempts a ON a.attempt_id = b.attempt_id
                LEFT JOIN semantic_tasks t ON t.task_id = a.task_id
                WHERE b.resource_id = ?
                ORDER BY b.created_at DESC, b.binding_id DESC
                LIMIT ?
                """,
                (resource_id, limit),
            ).fetchall()
        return [
            ResourceUsageRecord(
                bindingId=row["binding_id"],
                attemptId=row["attempt_id"],
                runId=row["run_id"],
                taskId=row["task_id"],
                missionId=row["mission_id"],
                taskTitle=row["task_title"],
                semanticTaskKey=row["semantic_key"],
                acgNodeId=row["acg_node_id"],
                agentId=row["agent_id"],
                modelId=row["model_id"],
                attemptNumber=int(row["attempt_number"]),
                attemptStatus=str(row["attempt_status"]),
                startedAt=row["started_at"],
                finishedAt=row["finished_at"],
                boundAt=row["bound_at"],
            )
            for row in rows
        ]


class SQLiteArtifactRepository(_SQLiteRepository):
    """Append-only repository for immutable Artifact domain identities."""

    def add(self, artifact: Artifact) -> Artifact:
        encoded = artifact.model_dump(by_alias=True, mode="json")
        with self.storage.transaction() as conn:
            existing_row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ? OR content_ref = ?",
                (artifact.artifact_id, artifact.content_ref),
            ).fetchone()
            if existing_row is not None:
                existing = self._from_row(existing_row)
                if existing.model_dump(by_alias=True, mode="json") != encoded:
                    raise IdentityConflictError(
                        "Artifact identity or contentRef already belongs to different immutable data"
                    )
                return existing
            try:
                conn.execute(
                    """INSERT INTO artifacts(
                           artifact_id, mission_id, origin_run_id, task_id,
                           semantic_task_key, artifact_key, acg_node_id,
                           producer_attempt_id, name, artifact_type, media_type,
                           content_ref, checksum, created_at, metadata_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        artifact.artifact_id,
                        artifact.mission_id,
                        artifact.origin_run_id,
                        artifact.task_id,
                        artifact.semantic_task_key,
                        artifact.artifact_key,
                        artifact.acg_node_id,
                        artifact.producer_attempt_id,
                        artifact.name,
                        artifact.artifact_type,
                        artifact.media_type,
                        artifact.content_ref,
                        artifact.checksum,
                        _iso(artifact.created_at),
                        _json(artifact.metadata),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdentityConflictError(f"cannot persist Artifact: {exc}") from exc
        return artifact

    def get(self, artifact_id: ArtifactId) -> Artifact | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_mission(self, mission_id: MissionId) -> list[Artifact]:
        return self._list("mission_id", mission_id)

    def list_for_origin_run(self, run_id: RunId) -> list[Artifact]:
        return self._list("origin_run_id", run_id)

    def list_for_attempt(self, attempt_id: AttemptId) -> list[Artifact]:
        return self._list("producer_attempt_id", attempt_id)

    def _list(self, column: str, value: str) -> list[Artifact]:
        with self.storage.read() as conn:
            rows = conn.execute(
                f"SELECT * FROM artifacts WHERE {column} = ? ORDER BY created_at, artifact_id",
                (value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Artifact:
        return Artifact(
            artifactId=row["artifact_id"],
            missionId=row["mission_id"],
            originRunId=row["origin_run_id"],
            taskId=row["task_id"],
            semanticTaskKey=row["semantic_task_key"],
            artifactKey=row["artifact_key"],
            acgNodeId=row["acg_node_id"],
            producerAttemptId=row["producer_attempt_id"],
            name=row["name"],
            artifactType=row["artifact_type"],
            mediaType=row["media_type"],
            contentRef=row["content_ref"],
            checksum=row["checksum"],
            createdAt=row["created_at"],
            metadata=_load_json(row["metadata_json"], {}),
        )


class SQLiteRunArtifactBindingRepository(_SQLiteRepository):
    """Append-only usage relation; slot replacement is deliberately rejected."""

    def add(self, binding: RunArtifactBinding) -> RunArtifactBinding:
        encoded = binding.model_dump(by_alias=True, mode="json")
        with self.storage.transaction() as conn:
            existing_row = conn.execute(
                """SELECT * FROM run_artifact_bindings
                   WHERE binding_id = ?
                      OR (run_id = ? AND semantic_task_key = ? AND artifact_key = ?)""",
                (
                    binding.binding_id,
                    binding.run_id,
                    binding.semantic_task_key,
                    binding.artifact_key,
                ),
            ).fetchone()
            if existing_row is not None:
                existing = self._from_row(existing_row)
                if existing.model_dump(by_alias=True, mode="json") != encoded:
                    raise IdentityConflictError(
                        "RunArtifactBinding slot already belongs to different immutable binding"
                    )
                return existing
            if binding.artifact_key.strip().lower() == "final":
                existing_final = conn.execute(
                    """SELECT b.binding_id FROM run_artifact_bindings b
                       JOIN artifacts a ON a.artifact_id = b.artifact_id
                       WHERE b.run_id = ? AND lower(trim(b.artifact_key)) = 'final'
                         AND a.artifact_type = 'run_deliverable'""",
                    (binding.run_id,),
                ).fetchone()
                if existing_final is not None:
                    raise IdentityConflictError(
                        "a Run may contain at most one run_deliverable artifact"
                    )
            try:
                conn.execute(
                    """INSERT INTO run_artifact_bindings(
                           binding_id, run_id, task_id, semantic_task_key,
                           artifact_key, artifact_id, disposition, source_run_id, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        binding.binding_id,
                        binding.run_id,
                        binding.task_id,
                        binding.semantic_task_key,
                        binding.artifact_key,
                        binding.artifact_id,
                        binding.disposition.value,
                        binding.source_run_id,
                        _iso(binding.created_at),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdentityConflictError(
                    f"cannot persist RunArtifactBinding: {exc}"
                ) from exc
        return binding

    def get(self, binding_id: str) -> RunArtifactBinding | None:
        with self.storage.read() as conn:
            row = conn.execute(
                "SELECT * FROM run_artifact_bindings WHERE binding_id = ?",
                (binding_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_run(self, run_id: RunId) -> list[RunArtifactBinding]:
        return self._list("run_id", run_id)

    def list_for_artifact(self, artifact_id: ArtifactId) -> list[RunArtifactBinding]:
        return self._list("artifact_id", artifact_id)

    def find_for_slot(
        self, run_id: RunId, semantic_task_key: str, artifact_key: str
    ) -> RunArtifactBinding | None:
        with self.storage.read() as conn:
            row = conn.execute(
                """SELECT * FROM run_artifact_bindings
                   WHERE run_id = ? AND semantic_task_key = ? AND artifact_key = ?""",
                (run_id, semantic_task_key, artifact_key),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def _list(self, column: str, value: str) -> list[RunArtifactBinding]:
        with self.storage.read() as conn:
            rows = conn.execute(
                f"""SELECT * FROM run_artifact_bindings
                    WHERE {column} = ?
                    ORDER BY created_at, binding_id""",
                (value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RunArtifactBinding:
        return RunArtifactBinding(
            bindingId=row["binding_id"],
            runId=row["run_id"],
            taskId=row["task_id"],
            semanticTaskKey=row["semantic_task_key"],
            artifactKey=row["artifact_key"],
            artifactId=row["artifact_id"],
            disposition=row["disposition"],
            sourceRunId=row["source_run_id"],
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


class SQLiteLifecycleProjectionEventRepository(_SQLiteRepository):
    table_name = "lifecycle_projection_events"

    """持久化投影意图；相同事件 ID 只能对应完全相同的事实。"""

    def begin(self, event: LifecycleProjectionEvent) -> LifecycleProjectionEvent:
        with self.storage.transaction() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.table_name} WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    f"""INSERT INTO {self.table_name}(
                        event_id, event_type, aggregate_id, payload_json, payload_hash,
                        status, attempts, last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.event_id,
                        event.event_type,
                        event.aggregate_id,
                        _json(event.payload),
                        event.payload_hash,
                        event.status.value,
                        event.attempts,
                        event.last_error,
                        _iso(event.created_at),
                        _iso(event.updated_at),
                    ),
                )
            else:
                if (
                    row["payload_hash"] != event.payload_hash
                    or row["event_type"] != event.event_type
                    or row["aggregate_id"] != event.aggregate_id
                ):
                    raise IdentityConflictError(
                        f"projection event id already has different content: {event.event_id}"
                    )
                if row["status"] != "applied":
                    conn.execute(
                        f"""UPDATE {self.table_name}
                           SET status = 'pending', attempts = attempts + 1,
                               last_error = NULL, updated_at = ?
                           WHERE event_id = ?""",
                        (_iso(_now()), event.event_id),
                    )
        stored = self.get(event.event_id)
        assert stored is not None
        return stored

    def mark_applied(self, event_id: str) -> LifecycleProjectionEvent:
        return self._mark(event_id, "applied", None)

    def mark_failed(self, event_id: str, error: str) -> LifecycleProjectionEvent:
        return self._mark(event_id, "failed", error[:2000])

    def record_replay_failure(self, event_id: str, error: str) -> LifecycleProjectionEvent:
        """Count one failed journal replay so dead-letter caps can engage."""
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                f"""UPDATE {self.table_name}
                   SET status = 'failed', attempts = attempts + 1,
                       last_error = ?, updated_at = ?
                   WHERE event_id = ?""",
                (error[:2000], _iso(_now()), event_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"projection event not found: {event_id}")
        stored = self.get(event_id)
        assert stored is not None
        return stored

    def get(self, event_id: str) -> LifecycleProjectionEvent | None:
        with self.storage.read() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.table_name} WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_unapplied(self, *, limit: int = 200) -> list[LifecycleProjectionEvent]:
        with self.storage.read() as conn:
            rows = conn.execute(
                f"""SELECT * FROM {self.table_name}
                   WHERE status != 'applied'
                   ORDER BY created_at, event_id LIMIT ?""",
                (max(1, limit),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.storage.read() as conn:
            row = conn.execute(
                f"""SELECT
                        SUM(CASE WHEN status != 'applied' THEN 1 ELSE 0 END) AS backlog,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                        MIN(CASE WHEN status != 'applied' THEN created_at END) AS oldest
                    FROM {self.table_name}"""
            ).fetchone()
        return {
            "backlog": int(row["backlog"] or 0),
            "failed": int(row["failed"] or 0),
            "oldestEventAt": row["oldest"],
        }

    def _mark(
        self,
        event_id: str,
        status: str,
        last_error: str | None,
    ) -> LifecycleProjectionEvent:
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                f"""UPDATE {self.table_name}
                   SET status = ?, last_error = ?, updated_at = ?
                   WHERE event_id = ?""",
                (status, last_error, _iso(_now()), event_id),
            )
            if cursor.rowcount != 1:
                raise EntityNotFoundError(f"projection event not found: {event_id}")
        stored = self.get(event_id)
        assert stored is not None
        return stored

    @staticmethod
    def _from_row(row: sqlite3.Row) -> LifecycleProjectionEvent:
        return LifecycleProjectionEvent(
            eventId=row["event_id"],
            eventType=row["event_type"],
            aggregateId=row["aggregate_id"],
            payload=_load_json(row["payload_json"], {}),
            payloadHash=row["payload_hash"],
            status=row["status"],
            attempts=row["attempts"],
            lastError=row["last_error"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )


class SQLiteLifecycleInboxRepository(SQLiteLifecycleProjectionEventRepository):
    """Durable identity-side receipt log for Execution Runtime lifecycle outbox events."""

    table_name = "lifecycle_inbox"


class SQLiteV2Repositories:
    """显式聚合领域 Repository，供 ACG 身份生命周期服务依赖注入。"""

    def __init__(self, storage: SQLiteV2Storage) -> None:
        self.storage = storage
        self.input_attachments = SQLiteInputAttachmentRepository(storage)
        self.missions = SQLiteMissionRepository(storage)
        self.semantic_tasks = SQLiteSemanticTaskRepository(storage)
        self.blueprints = SQLiteBlueprintRepository(storage)
        self.runs = SQLiteRunRepository(storage)
        self.attempts = SQLiteAttemptRepository(storage)
        self.step_executions = SQLiteStepExecutionRepository(storage)
        self.task_bindings = SQLiteTaskBindingRepository(storage)
        self.blueprint_node_bindings = SQLiteBlueprintNodeBindingRepository(storage)
        self.execution_bindings = SQLiteExecutionBindingRepository(storage)
        self.artifacts = SQLiteArtifactRepository(storage)
        self.run_artifact_bindings = SQLiteRunArtifactBindingRepository(storage)
        self.provenance_links = SQLiteProvenanceLinkRepository(storage)
        self.projection_events = SQLiteLifecycleProjectionEventRepository(storage)
        self.inbox_events = SQLiteLifecycleInboxRepository(storage)
        self.task_plans = SQLiteTaskPlanRepository(storage)

    def persist_task_plan(self, plan: TaskPlan) -> dict[str, SemanticTask]:
        """Persist a plan snapshot while reusing its canonical logical task identities."""
        import hashlib

        for node in plan.nodes:
            validate_logical_key(node.key, field_name="semanticTaskKey")
        payload = plan.model_dump(by_alias=True, mode="json")
        encoded = _json(payload)
        content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        parent_by_key = {
            relation.target_key: relation.source_key
            for relation in plan.relations
            if relation.relation_type.value == "parent"
        }
        parent_by_key.update({node.key: node.parent_key for node in plan.nodes if node.parent_key})
        with self.storage.transaction() as conn:
            mission = conn.execute(
                "SELECT status FROM missions WHERE mission_id = ?", (plan.mission_id,)
            ).fetchone()
            if mission is None:
                raise EntityNotFoundError(f"Mission not found: {plan.mission_id}")
            existing_plan = conn.execute(
                "SELECT content_hash FROM task_plans WHERE mission_id = ? AND plan_version = ?",
                (plan.mission_id, plan.plan_version),
            ).fetchone()
            if existing_plan is not None:
                if existing_plan["content_hash"] != content_hash:
                    raise IdentityConflictError(
                        "Planner semantic key changed meaning: planVersion already contains a different TaskPlan"
                    )
                return {
                    node.key: self.semantic_tasks.get(
                        self._task_plan_node_id(conn, plan, node.key)
                    )
                    for node in plan.nodes
                }

            rows = conn.execute(
                "SELECT * FROM semantic_tasks WHERE mission_id = ? ORDER BY rowid",
                (plan.mission_id,),
            ).fetchall()
            by_key: dict[str, sqlite3.Row] = {}
            legacy_candidates: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                key = row["semantic_key"]
                if isinstance(key, str) and key:
                    by_key[key] = row
                    continue
                metadata_key = _load_json(row["metadata_json"], {}).get("plannerSemanticKey")
                if isinstance(metadata_key, str) and metadata_key:
                    legacy_candidates.setdefault(metadata_key, []).append(row)
            for key, candidates in legacy_candidates.items():
                if key not in by_key and len(candidates) == 1:
                    row = candidates[0]
                    conn.execute(
                        "UPDATE semantic_tasks SET semantic_key = ? WHERE task_id = ?",
                        (key, row["task_id"]),
                    )
                    by_key[key] = row
            node_ids: dict[str, str] = {}
            pending = list(plan.nodes)
            while pending:
                ready = [
                    node for node in pending
                    if parent_by_key.get(node.key) is None
                    or parent_by_key.get(node.key) in node_ids
                ]
                if not ready:
                    raise IdentityConflictError("TaskPlan parent relations cannot be resolved")
                for node in ready:
                    parent_id = node_ids.get(parent_by_key.get(node.key))
                    existing = by_key.get(node.key)
                    semantic_metadata = {
                        **node.metadata,
                        "plannerSemanticKey": node.key,
                        "plannerPlanVersion": plan.plan_version,
                        "capabilityRequirements": list(node.capability_requirements),
                        "acceptanceCriteria": list(node.acceptance_criteria),
                    }
                    if existing is not None:
                        node_id = str(existing["task_id"])
                        conn.execute(
                            """UPDATE semantic_tasks
                               SET semantic_key = ?, parent_task_id = ?, title = ?, objective = ?,
                                   constraints_json = ?, status = 'created', metadata_json = ?
                               WHERE task_id = ?""",
                            (
                                node.key,
                                parent_id,
                                node.title,
                                node.objective,
                                _json(node.constraints),
                                _json(semantic_metadata),
                                node_id,
                            ),
                        )
                    else:
                        if legacy_candidates.get(node.key):
                            raise IdentityConflictError(
                                f"semanticTaskKey is ambiguous in legacy data: {node.key}"
                            )
                        node_id = new_task_id()
                        conn.execute(
                            """INSERT INTO semantic_tasks(
                                   task_id, mission_id, semantic_key, parent_task_id, title, objective,
                                   constraints_json, status, metadata_json
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?)""",
                            (
                                node_id, plan.mission_id, node.key, parent_id, node.title, node.objective,
                                _json(node.constraints), _json(semantic_metadata),
                            ),
                        )
                    node_ids[node.key] = node_id
                    pending.remove(node)
            for key, row in by_key.items():
                if key not in node_ids:
                    conn.execute(
                        "UPDATE semantic_tasks SET status = 'retired' WHERE task_id = ?",
                        (row["task_id"],),
                    )
            if mission["status"] == "created":
                conn.execute(
                    "UPDATE missions SET status = 'planning', updated_at = ? WHERE mission_id = ?",
                    (_iso(_now()), plan.mission_id),
                )
            conn.execute(
                """INSERT INTO task_plans(mission_id, plan_version, payload_json, content_hash, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (plan.mission_id, plan.plan_version, encoded, content_hash, _iso(_now())),
            )
            for node in plan.nodes:
                conn.execute(
                    """INSERT INTO task_plan_nodes(
                           mission_id, plan_version, semantic_key, task_id, payload_json
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (plan.mission_id, plan.plan_version, node.key, node_ids[node.key],
                     _json(node.model_dump(by_alias=True, mode="json"))),
                )
            for relation in plan.relations:
                conn.execute(
                    """INSERT INTO task_plan_relations(
                           mission_id, plan_version, source_key, target_key, relation_type
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (plan.mission_id, plan.plan_version, relation.source_key,
                     relation.target_key, relation.relation_type.value),
                )
        return {
            key: self.semantic_tasks.get(node_id)
            for key, node_id in node_ids.items()
            if self.semantic_tasks.get(node_id) is not None
        }

    @staticmethod
    def _task_plan_node_id(conn: sqlite3.Connection, plan: TaskPlan, key: str) -> str:
        row = conn.execute(
            """SELECT task_id FROM task_plan_nodes
               WHERE mission_id = ? AND plan_version = ? AND semantic_key = ?""",
            (plan.mission_id, plan.plan_version, key),
        ).fetchone()
        if row is None or row["task_id"] is None:
            raise EntityNotFoundError(f"TaskPlan node not found: {key}")
        return str(row["task_id"])

    def ensure_attempt(
        self,
        run_id: RunId,
        task_id: TaskId,
        *,
        attempt_number: int | None = None,
        attempt_id: AttemptId | None = None,
        resource_binding: dict | None = None,
    ) -> Attempt:
        """在一个事务内分配连续编号；相同期望编号的并发重放返回同一 Attempt。"""
        now = _now()
        with self.storage.transaction() as conn:
            owner = conn.execute(
                """SELECT r.mission_id AS run_mission_id, n.mission_id AS task_mission_id
                   FROM workflow_runs_v2 r, semantic_tasks n
                   WHERE r.run_id = ? AND n.task_id = ?""",
                (run_id, task_id),
            ).fetchone()
            if owner is None:
                raise EntityNotFoundError("Run or SemanticTask not found for Attempt")
            if owner["run_mission_id"] != owner["task_mission_id"]:
                raise IdentityConflictError(
                    "Attempt cannot use another Mission's SemanticTask"
                )
            rows = conn.execute(
                """SELECT * FROM attempts
                   WHERE run_id = ? AND task_id = ? ORDER BY attempt_number""",
                (run_id, task_id),
            ).fetchall()
            # The emitter's attemptId is the idempotency anchor.  A replay of
            # the same attempt must return the persisted row even when its
            # attemptNumber drifted (resumed Runs, later loop iterations), so
            # the identity check runs before any numbering validation.
            if attempt_id is not None:
                by_attempt_id = next(
                    (row for row in rows if str(row["attempt_id"]) == attempt_id),
                    None,
                )
                if by_attempt_id is not None:
                    return SQLiteAttemptRepository._from_row(by_attempt_id)
            expected = attempt_number or (len(rows) + 1)
            existing = next(
                (row for row in rows if int(row["attempt_number"]) == expected),
                None,
            )
            if existing is not None:
                if attempt_id is not None and str(existing["attempt_id"]) != attempt_id:
                    raise IdentityConflictError("Attempt number already uses a different attemptId")
                return SQLiteAttemptRepository._from_row(existing)
            if expected != len(rows) + 1:
                raise IdentityConflictError("Attempt number is not contiguous")
            attempt = Attempt(
                attemptId=attempt_id or new_attempt_id(),
                runId=run_id,
                taskId=task_id,
                attemptNumber=expected,
                resourceBinding=resource_binding,
            )
            conn.execute(
                """INSERT INTO attempts(
                    attempt_id, run_id, task_id, attempt_number, status, started_at,
                    finished_at, failure_reason, resource_binding_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt.attempt_id,
                    attempt.run_id,
                    attempt.task_id,
                    attempt.attempt_number,
                    attempt.status.value,
                    None,
                    None,
                    None,
                    _json(resource_binding) if resource_binding is not None else None,
                ),
            )
            conn.execute(
                """UPDATE workflow_runs_v2
                   SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
                   WHERE run_id = ? AND status = 'pending'""",
                (_iso(now), _iso(now), run_id),
            )
            conn.execute(
                """UPDATE missions SET status = 'running', updated_at = ?
                   WHERE mission_id = ? AND status = 'ready'""",
                (_iso(now), owner["run_mission_id"]),
            )
            return attempt

    def ensure_step_execution(
        self,
        run_id: RunId,
        task_id: TaskId,
        attempt_id: AttemptId,
        *,
        input: dict,
        step_execution_id: StepExecutionId | None = None,
    ) -> StepExecution:
        """在 Attempt 状态切换的同一事务内幂等创建唯一 StepExecution。"""
        started_at = _now()
        with self.storage.transaction() as conn:
            attempt_row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if attempt_row is None:
                raise EntityNotFoundError(f"Attempt not found: {attempt_id}")
            if attempt_row["run_id"] != run_id or attempt_row["task_id"] != task_id:
                raise IdentityConflictError(
                    "StepExecution identity does not match Attempt"
                )
            if conn.execute(
                "SELECT 1 FROM execution_bindings WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone() is None:
                raise EntityNotFoundError(
                    "AcgIdentityLifecycleService requires a persisted ExecutionBinding"
                )
            existing = conn.execute(
                "SELECT * FROM step_executions WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                execution = SQLiteStepExecutionRepository._from_row(existing)
                if step_execution_id is not None and execution.step_execution_id != step_execution_id:
                    raise IdentityConflictError("Attempt already uses a different stepExecutionId")
                if execution.input != input:
                    raise IdentityConflictError(
                        "Attempt already has a StepExecution with different input"
                    )
                return execution
            if attempt_row["status"] != AttemptStatus.PENDING.value:
                raise IdentityConflictError(
                    "only a pending Attempt can start a StepExecution"
                )
            execution = StepExecution(
                stepExecutionId=step_execution_id or new_step_execution_id(),
                runId=run_id,
                taskId=task_id,
                attemptId=attempt_id,
                status=StepExecutionStatus.RUNNING,
                input=input,
                output={},
                startedAt=started_at,
            )
            conn.execute(
                """INSERT INTO step_executions(
                    step_execution_id, attempt_id, run_id, task_id, input_json,
                    output_json, status, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    execution.step_execution_id,
                    attempt_id,
                    run_id,
                    task_id,
                    _json(input),
                    _json({}),
                    execution.status.value,
                    _iso(started_at),
                    None,
                ),
            )
            conn.execute(
                """UPDATE attempts SET status = 'running', started_at = ?
                   WHERE attempt_id = ? AND status = 'pending'""",
                (_iso(started_at), attempt_id),
            )
            return execution

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
            current_execution = conn.execute(
                "SELECT * FROM step_executions WHERE step_execution_id = ? AND attempt_id = ?",
                (step_execution_id, attempt_id),
            ).fetchone()
            current_attempt = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if current_execution is None or current_attempt is None:
                raise EntityNotFoundError(
                    f"StepExecution or Attempt not found: {step_execution_id}"
                )
            if (
                current_execution["status"] == step_status.value
                and current_attempt["status"] == attempt_status.value
            ):
                persisted_output = _load_json(current_execution["output_json"], {})
                if persisted_output != output:
                    raise IdentityConflictError(
                        "terminal StepExecution replay changed its output"
                    )
                existing_execution = SQLiteStepExecutionRepository._from_row(
                    current_execution
                )
                existing_attempt = SQLiteAttemptRepository._from_row(current_attempt)
                return existing_execution, existing_attempt
            if (
                current_execution["status"] != StepExecutionStatus.RUNNING.value
                or current_attempt["status"] != AttemptStatus.RUNNING.value
            ):
                raise IdentityConflictError(
                    "terminal execution state cannot be rewritten"
                )
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
    "SQLiteArtifactRepository",
    "SQLiteBlueprintNodeBindingRepository",
    "SQLiteBlueprintRepository",
    "SQLiteExecutionBindingRepository",
    "SQLiteLifecycleProjectionEventRepository",
    "SQLiteProvenanceLinkRepository",
    "SQLiteRunRepository",
    "SQLiteRunArtifactBindingRepository",
    "SQLiteStepExecutionRepository",
    "SQLiteSemanticTaskRepository",
    "SQLiteTaskBindingRepository",
    "SQLiteMissionRepository",
    "SQLiteV2Repositories",
]
