"""运行时配套的 SQLite 任务/运行存储，不包含跨部件业务实现。"""


from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from contracts.workflow import AgentTask, StepStatus, WorkflowRun, WorkflowStatus
from support.stores._policy import matches_run, matches_task, reject_terminal_overwrite, run_priority
from support.stores.workflow_store import (
    WorkflowRunDeleteResult,
    WorkflowRunNotTerminalError,
    WorkflowStore,
    WorkflowStorePage,
    paginate_items,
    status_value,
    status_values,
)


class SQLiteWorkflowStore(WorkflowStore):
    """基于 SQLite 的本地持久化 WorkflowStore。"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.busy_timeout_ms = int(os.getenv("AGENTOS_SQLITE_BUSY_TIMEOUT_MS", "5000"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def save_task(self, task: AgentTask) -> None:
        """以任务标识 UPSERT JSON 快照并提交事务；SQLite 错误由驱动层原样抛出。"""
        payload = json.dumps(task.model_dump(by_alias=True, mode="json"), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO tasks(task_id, payload, updated_at)
                   VALUES(?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       payload=excluded.payload, updated_at=excluded.updated_at""",
                (task.task_id, payload, task.updated_at.isoformat()),
            )
            self._append_outbox(conn, f"task:{task.task_id}:{task.updated_at.isoformat()}", "task.created", task.task_id, payload)
            conn.commit()

    def get_task(self, task_id: str) -> AgentTask:
        """读取并校验任务 JSON 快照；缺失时抛出 ``KeyError``。"""
        row = self._fetch_one("SELECT payload FROM tasks WHERE task_id = ?", (task_id,))
        if row is None:
            raise KeyError(f"task not found: {task_id}")
        return AgentTask.model_validate(json.loads(row["payload"]))

    def save_run(self, run: WorkflowRun) -> None:
        """在单连接事务中保存运行。

        要求父任务存在且 ``task_id`` 不可变；拒绝终态被旧/不同状态覆盖，验证明显状态冲突后
        执行 UPSERT 与提交。
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            task_row = conn.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (run.task_id,)
            ).fetchone()
            if task_row is None:
                raise ValueError(f"workflow run task does not exist: {run.task_id}")
            row = conn.execute(
                "SELECT task_id, payload FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone()
            if row is not None:
                if str(row["task_id"]) != run.task_id:
                    raise ValueError(
                        f"workflow run taskId cannot change: {run.run_id}"
                    )
                existing = WorkflowRun.model_validate(json.loads(row["payload"]))
                if reject_terminal_overwrite(existing, run):
                    return
            _validate_obvious_run_state_conflicts(run)
            conn.execute(
                """
                INSERT INTO runs(run_id, task_id, payload, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    task_id=excluded.task_id,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    run.run_id,
                    run.task_id,
                    json.dumps(run.model_dump(by_alias=True, mode="json"), ensure_ascii=False),
                    run.updated_at.isoformat(),
                ),
            )
            event_type = (
                "run.superseded" if run.status is WorkflowStatus.SUPERSEDED
                else "run.finished" if run.status in {
                    WorkflowStatus.COMPLETED,
                    WorkflowStatus.FAILED,
                    WorkflowStatus.CANCELLED,
                }
                else "run.prepared" if run.status is WorkflowStatus.PENDING
                else "run.snapshot"
            )
            self._append_outbox(
                conn,
                f"run:{run.run_id}:{run.updated_at.isoformat()}",
                event_type,
                run.run_id,
                json.dumps(run.model_dump(by_alias=True, mode="json"), ensure_ascii=False),
            )
            conn.commit()

    def list_outbox(self, *, limit: int = 200) -> list[dict]:
        rows = self._fetch_all(
            """SELECT event_id, event_type, aggregate_id, payload, attempts
               FROM lifecycle_outbox WHERE status != 'applied'
               ORDER BY created_at, event_id LIMIT ?""",
            (max(1, limit),),
        )
        return [dict(row) for row in rows]

    def outbox_stats(self) -> dict:
        row = self._fetch_one(
            """SELECT
                   SUM(CASE WHEN status != 'applied' THEN 1 ELSE 0 END) AS backlog,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                   MIN(CASE WHEN status != 'applied' THEN created_at END) AS oldest
               FROM lifecycle_outbox""",
            (),
        )
        return {
            "backlog": int(row["backlog"] or 0),
            "failed": int(row["failed"] or 0),
            "oldestEventAt": row["oldest"],
        }

    def mark_outbox(self, event_id: str, *, applied: bool, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE lifecycle_outbox
                   SET status = ?, attempts = attempts + 1, last_error = ?
                   WHERE event_id = ?""",
                ("applied" if applied else "failed", error, event_id),
            )
            conn.commit()

    def get_run(self, run_id: str) -> WorkflowRun:
        """读取并校验运行 JSON 快照；缺失时抛出 ``KeyError``。"""
        row = self._fetch_one("SELECT payload FROM runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise KeyError(f"workflow run not found: {run_id}")
        return WorkflowRun.model_validate(json.loads(row["payload"]))

    def list_tasks(
        self,
        *,
        status: WorkflowStatus | str | None = None,
        domain: str | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowStorePage[AgentTask]:
        """载入、筛选并按创建时间/标识降序分页任务，复杂度 ``O(T log T)``。"""
        expected_status = status_value(status)
        rows = self._fetch_all("SELECT payload FROM tasks")
        tasks = [
            task
            for task in (AgentTask.model_validate(json.loads(row["payload"])) for row in rows)
            if matches_task(task, status=expected_status, domain=domain, source=source)
        ]
        tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        return paginate_items(tasks, page=page, page_size=page_size)

    def list_runs(
        self,
        *,
        status: WorkflowStatus | str | None = None,
        statuses=None,
        domain: str | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        lifecycle_phase: str | None = None,
        source: str | None = None,
        sources=None,
        owner_user_id: str | None = None,
        owner_tenant_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowStorePage[WorkflowRun]:
        """载入、筛选并分页运行；多状态查询按运行优先级、更新时间和标识降序，复杂度 ``O(R log R)``。"""
        expected_status = status_value(status)
        expected_statuses = status_values(statuses)
        expected_sources = {str(item) for item in sources} if sources else None
        rows = self._fetch_all("SELECT payload FROM runs")
        runs = [
            run
            for run in (WorkflowRun.model_validate(json.loads(row["payload"])) for row in rows)
            if matches_run(
                run,
                status=expected_status,
                statuses=expected_statuses,
                domain=domain,
                workflow_id=workflow_id,
                task_id=task_id,
                lifecycle_phase=lifecycle_phase,
                source=source,
                sources=expected_sources,
                owner_user_id=owner_user_id,
                owner_tenant_id=owner_tenant_id,
            )
        ]
        runs.sort(
            key=lambda run: (run_priority(run) if expected_statuses else 0, run.updated_at, run.run_id),
            reverse=True,
        )
        return paginate_items(runs, page=page, page_size=page_size)

    def list_non_terminal_runs(self, *, limit: int = 200) -> tuple[WorkflowRun, ...]:
        """通过 SQLite JSON 条件返回最新优先的未终态运行；数量下限为 1。"""
        safe_limit = max(1, limit)
        rows = self._fetch_all(
            """
            SELECT payload FROM runs
            WHERE json_extract(payload, '$.status') NOT IN (?, ?, ?, ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                WorkflowStatus.COMPLETED.value,
                WorkflowStatus.FAILED.value,
                WorkflowStatus.CANCELLED.value,
                WorkflowStatus.SUPERSEDED.value,
                safe_limit,
            ),
        )
        return tuple(
            WorkflowRun.model_validate(json.loads(row["payload"])) for row in rows
        )

    def list_all_runs(self, *, offset: int = 0, limit: int = 200) -> tuple[WorkflowRun, ...]:
        rows = self._fetch_all(
            "SELECT payload FROM runs ORDER BY updated_at, run_id LIMIT ? OFFSET ?",
            (max(1, limit), max(0, offset)),
        )
        return tuple(WorkflowRun.model_validate(json.loads(row["payload"])) for row in rows)

    def find_run_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        """按幂等键返回更新时间最新的运行；无匹配时返回 ``None``。"""
        row = self._fetch_one(
            """
            SELECT payload FROM runs
            WHERE json_extract(payload, '$.idempotencyKey') = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (idempotency_key,),
        )
        if row is None:
            return None
        return WorkflowRun.model_validate(json.loads(row["payload"]))

    def delete_run(self, run_id: str, *, delete_orphan_task: bool = True) -> WorkflowRunDeleteResult:
        """事务删除终态运行并可清理孤立任务。

        非终态运行拒绝删除；提交前验证不会留下缺失父任务的运行，任何异常都会使连接上下文回滚。
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT task_id, payload FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"workflow run not found: {run_id}")
            task_id = str(row["task_id"])
            run = WorkflowRun.model_validate(json.loads(row["payload"]))
            if run.status not in {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            }:
                raise WorkflowRunNotTerminalError(run_id, run.status)
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            task_deleted = False
            if delete_orphan_task:
                referenced = conn.execute(
                    "SELECT 1 FROM runs WHERE task_id = ? LIMIT 1",
                    (task_id,),
                ).fetchone()
                if referenced is None:
                    cursor = conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
                    task_deleted = cursor.rowcount > 0
            orphan_runs = conn.execute(
                """
                SELECT COUNT(*)
                FROM runs r
                LEFT JOIN tasks t ON t.task_id = r.task_id
                WHERE t.task_id IS NULL
                """
            ).fetchone()[0]
            if int(orphan_runs) != 0:
                raise RuntimeError("workflow run deletion would leave missing task references")
            conn.commit()
        return WorkflowRunDeleteResult(
            run_id=run_id,
            task_id=task_id,
            task_deleted=task_deleted,
        )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise RuntimeError(f"SQLite WAL mode is required, got: {journal_mode}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS lifecycle_outbox (
                       event_id TEXT PRIMARY KEY,
                       event_type TEXT NOT NULL,
                       aggregate_id TEXT NOT NULL,
                       payload TEXT NOT NULL,
                       status TEXT NOT NULL DEFAULT 'pending',
                       attempts INTEGER NOT NULL DEFAULT 0,
                       last_error TEXT,
                       created_at TEXT NOT NULL
                   )"""
            )
            conn.commit()

    @staticmethod
    def _append_outbox(
        conn: sqlite3.Connection,
        event_id: str,
        event_type: str,
        aggregate_id: str,
        payload: str,
    ) -> None:
        conn.execute(
            """INSERT INTO lifecycle_outbox(
                   event_id, event_type, aggregate_id, payload, status, attempts, created_at
               ) VALUES (?, ?, ?, ?, 'pending', 0, datetime('now'))
               ON CONFLICT(event_id) DO UPDATE SET payload=excluded.payload""",
            (event_id, event_type, aggregate_id, payload),
        )

    def _execute(self, sql: str, params: tuple) -> None:
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _fetch_one(self, sql: str, params: tuple):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            return cursor.fetchone()

    def _fetch_all(self, sql: str, params: tuple = ()):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=max(self.busy_timeout_ms, 1) / 1000)
        conn.execute(f"PRAGMA busy_timeout={max(self.busy_timeout_ms, 1)}")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def checkpoint(self) -> tuple[int, int, int]:
        """在维护操作前刷写已提交 WAL 页，返回 SQLite checkpoint 三元计数。"""
        with self._connect() as conn:
            row = conn.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
            return tuple(int(value) for value in row)

    def backup_to(self, destination: str | Path) -> dict[str, int | str]:
        """创建并验证事务一致的 SQLite 备份。

        目标不得与源库相同；使用 SQLite 备份 API 后执行完整性校验，失败抛出 ``ValueError`` 或
        ``RuntimeError``，成功返回路径、完整性和记录数。
        """
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() == self.db_path.resolve():
            raise ValueError("backup destination must differ from source database")
        with self._connect() as source, sqlite3.connect(target) as dest:
            source.backup(dest)
            dest.commit()
        with sqlite3.connect(target) as verify:
            integrity = str(verify.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.lower() != "ok":
                raise RuntimeError(f"SQLite backup integrity check failed: {integrity}")
            task_count = int(verify.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
            run_count = int(verify.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        return {
            "source": str(self.db_path),
            "destination": str(target),
            "integrity": integrity,
            "taskCount": task_count,
            "runCount": run_count,
        }


def _validate_obvious_run_state_conflicts(run: WorkflowRun) -> None:
    statuses = {step.status for step in run.steps}

    if run.status == WorkflowStatus.COMPLETED:
        conflicts = {
            StepStatus.RUNNING,
            StepStatus.RETRYING,
            StepStatus.WAITING_REVIEW,
        }
        if statuses & conflicts:
            raise ValueError(
                f"completed workflow run has active or review steps: {run.run_id}"
            )
    elif run.status == WorkflowStatus.FAILED:
        if statuses & {StepStatus.RUNNING, StepStatus.RETRYING}:
            raise ValueError(f"failed workflow run has active steps: {run.run_id}")
    elif run.status == WorkflowStatus.WAITING_REVIEW:
        if StepStatus.WAITING_REVIEW not in statuses:
            raise ValueError(
                f"waiting_review workflow run has no waiting_review step: {run.run_id}"
            )


