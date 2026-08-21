"""运行时配套的内存任务/运行存储，面向开发和测试而非跨部件业务实现。"""


from __future__ import annotations

from typing import Dict
import hashlib
import json

from contracts.workflow import AgentTask, WorkflowRun, WorkflowStatus
from support.stores._policy import (
    TERMINAL_RUN_STATUSES,
    matches_run,
    matches_task,
    reject_terminal_overwrite,
    run_priority,
)
from support.stores.workflow_store import (
    WorkflowRunDeleteResult,
    WorkflowRunNotTerminalError,
    WorkflowStore,
    WorkflowStorePage,
    paginate_items,
    lifecycle_run_payload,
    status_value,
    status_values,
)


class MemoryWorkflowStore(WorkflowStore):
    """面向本地开发和测试的内存 WorkflowStore 适配器。"""

    def __init__(self):
        self._tasks: Dict[str, AgentTask] = {}
        self._runs: Dict[str, WorkflowRun] = {}
        self._terminal_run_statuses: Dict[str, WorkflowStatus] = {}
        self._lifecycle_outbox: Dict[str, dict] = {}

    def save_task(self, task: AgentTask) -> None:
        """按任务标识保存内存对象；调用方保留传入任务所有权。"""
        self._tasks[task.task_id] = task
        payload = task.model_dump(by_alias=True, mode="json")
        self._append_lifecycle_event(
            event_id=self._snapshot_event_id("task.created", task.task_id, payload),
            event_type="task.created",
            aggregate_id=task.task_id,
            payload=payload,
        )

    def get_task(self, task_id: str) -> AgentTask:
        """读取任务引用；缺失时抛出带上下文的 ``KeyError``。"""
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"task not found: {task_id}") from exc

    def save_run(self, run: WorkflowRun) -> None:
        """深复制保存运行，并拒绝终态被不同状态或更旧快照覆盖。

        失败到重试是唯一允许的终态回退兼容路径；该内存实现不提供线程同步。
        """
        if not self._save_run_snapshot(run):
            return
        event_type = (
            "run.superseded" if run.status is WorkflowStatus.SUPERSEDED
            else "run.finished" if run.status in TERMINAL_RUN_STATUSES
            else "run.prepared" if run.status is WorkflowStatus.PENDING
            else "run.snapshot"
        )
        payload = lifecycle_run_payload(run)
        self._append_lifecycle_event(
            event_id=self._snapshot_event_id(event_type, run.run_id, payload),
            event_type=event_type,
            aggregate_id=run.run_id,
            payload=payload,
        )

    def _save_run_snapshot(self, run: WorkflowRun) -> bool:
        if run.task_id not in self._tasks:
            raise ValueError(f"workflow run task does not exist: {run.task_id}")
        existing = self._runs.get(run.run_id)
        terminal_status = self._terminal_run_statuses.get(run.run_id)
        if terminal_status is not None and _reject_terminal_status_overwrite(terminal_status, run.status):
            return False
        if existing is not None and reject_terminal_overwrite(existing, run):
            return False
        if run.status in TERMINAL_RUN_STATUSES:
            self._terminal_run_statuses[run.run_id] = run.status
        elif terminal_status == WorkflowStatus.FAILED and run.status == WorkflowStatus.RETRYING:
            self._terminal_run_statuses.pop(run.run_id, None)
        self._runs[run.run_id] = run.model_copy(deep=True)
        return True

    def save_run_with_events(self, run: WorkflowRun, events) -> None:
        outbox_snapshot = dict(self._lifecycle_outbox)
        run_snapshot = dict(self._runs)
        terminal_snapshot = dict(self._terminal_run_statuses)
        try:
            if not self._save_run_snapshot(run):
                return
            for event in events:
                event_id = str(event["eventId"])
                current = self._lifecycle_outbox.get(event_id)
                payload = {
                    "event_id": event_id,
                    "event_type": str(event["eventType"]),
                    "aggregate_id": str(event.get("aggregateId") or run.run_id),
                    "payload": json.dumps(event.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                    "attempts": 0,
                }
                if current is not None and current != payload:
                    raise ValueError(f"lifecycle event payload conflict: {event_id}")
                self._lifecycle_outbox[event_id] = payload
        except Exception:
            self._lifecycle_outbox = outbox_snapshot
            self._runs = run_snapshot
            self._terminal_run_statuses = terminal_snapshot
            raise

    def save_graph_patch_transition(
        self, old_run: WorkflowRun, new_run: WorkflowRun, event: dict
    ) -> None:
        runs_snapshot = dict(self._runs)
        terminal_snapshot = dict(self._terminal_run_statuses)
        outbox_snapshot = dict(self._lifecycle_outbox)
        try:
            self._save_run_snapshot(new_run)
            self._save_run_snapshot(old_run)
            event_id = str(event["eventId"])
            payload = {
                "event_id": event_id,
                "event_type": str(event["eventType"]),
                "aggregate_id": str(event.get("aggregateId") or old_run.run_id),
                "payload": json.dumps(event.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                "attempts": 0,
            }
            current = self._lifecycle_outbox.get(event_id)
            if current is not None and current != payload:
                raise ValueError(f"lifecycle event payload conflict: {event_id}")
            self._lifecycle_outbox[event_id] = payload
        except Exception:
            self._runs = runs_snapshot
            self._terminal_run_statuses = terminal_snapshot
            self._lifecycle_outbox = outbox_snapshot
            raise

    def _append_lifecycle_event(
        self,
        *,
        event_id: str,
        event_type: str,
        aggregate_id: str,
        payload: dict,
    ) -> None:
        encoded = {
            "event_id": event_id,
            "event_type": event_type,
            "aggregate_id": aggregate_id,
            "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "attempts": 0,
        }
        current = self._lifecycle_outbox.get(event_id)
        if current is not None and current != encoded:
            raise ValueError(f"lifecycle event payload conflict: {event_id}")
        self._lifecycle_outbox[event_id] = encoded

    @staticmethod
    def _snapshot_event_id(event_type: str, aggregate_id: str, payload: dict) -> str:
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{event_type}:{aggregate_id}:{digest}"

    def list_outbox(self, *, limit: int = 200) -> list[dict]:
        return [dict(item) for item in list(self._lifecycle_outbox.values())[:max(1, limit)]]

    def mark_outbox(self, event_id: str, *, applied: bool, error: str | None = None) -> None:
        if applied:
            self._lifecycle_outbox.pop(event_id, None)

    def get_run(self, run_id: str) -> WorkflowRun:
        """返回运行的深复制快照，避免调用方绕过存储修改内部状态。"""
        try:
            return self._runs[run_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"workflow run not found: {run_id}") from exc

    def delete_run(self, run_id: str, *, delete_orphan_task: bool = True) -> WorkflowRunDeleteResult:
        """删除终态运行，并可清理无剩余运行引用的任务；非终态时抛出专用错误。"""
        try:
            run = self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"workflow run not found: {run_id}") from exc
        if run.status not in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }:
            raise WorkflowRunNotTerminalError(run_id, run.status)
        self._runs.pop(run_id)
        self._terminal_run_statuses.pop(run_id, None)
        task_deleted = False
        if delete_orphan_task and not any(item.task_id == run.task_id for item in self._runs.values()):
            task_deleted = self._tasks.pop(run.task_id, None) is not None
        return WorkflowRunDeleteResult(
            run_id=run_id,
            task_id=run.task_id,
            task_deleted=task_deleted,
        )

    def list_tasks(
        self,
        *,
        status: WorkflowStatus | str | None = None,
        domain: str | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowStorePage[AgentTask]:
        """筛选并按 ``(created_at, task_id)`` 降序分页返回任务深复制，复杂度 ``O(T)``。"""
        expected_status = status_value(status)
        tasks = [
            task.model_copy(deep=True)
            for task in self._tasks.values()
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
        """筛选并分页返回运行深复制。

        有多状态筛选时等待审核、非终态、终态依次优先，再按更新时间和标识降序，复杂度
        ``O(R log R)``。
        """
        expected_status = status_value(status)
        expected_statuses = status_values(statuses)
        expected_sources = {str(item) for item in sources} if sources else None
        runs = [
            run.model_copy(deep=True)
            for run in self._runs.values()
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
        """返回最新优先的未终态运行深复制，数量下限为 1，复杂度 ``O(R log R)``。"""
        runs = [
            run.model_copy(deep=True)
            for run in self._runs.values()
            if run.status not in TERMINAL_RUN_STATUSES
        ]
        runs.sort(key=lambda run: (run.updated_at, run.run_id), reverse=True)
        return tuple(runs[: max(1, limit)])

    def list_all_runs(self, *, offset: int = 0, limit: int = 200) -> tuple[WorkflowRun, ...]:
        runs = sorted(
            (run.model_copy(deep=True) for run in self._runs.values()),
            key=lambda run: (run.created_at, run.run_id),
        )
        start = max(0, offset)
        return tuple(runs[start:start + max(1, limit)])

    def find_run_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        """按幂等键返回创建时间最新的运行深复制；无匹配时返回 ``None``。"""
        matches = [
            run.model_copy(deep=True)
            for run in self._runs.values()
            if run.idempotency_key == idempotency_key
        ]
        if not matches:
            return None
        return max(matches, key=lambda run: (run.created_at, run.run_id))


def _reject_terminal_status_overwrite(
    existing: WorkflowStatus,
    incoming: WorkflowStatus,
) -> bool:
    if existing == WorkflowStatus.FAILED and incoming == WorkflowStatus.RETRYING:
        return False
    return incoming != existing
