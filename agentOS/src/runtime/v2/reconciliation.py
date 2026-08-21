"""WKN 快照与 AgentOS 身份投影的启动对账。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from contracts.planning import TaskNodeImplementationBinding, TaskPlan
from contracts.workflow import AgentTask
from domain.models import RunStatus
from support.acg.models import WknBlueprintSpec

from .wkn_bridge import WknIdentityLifecycleAdapter


@dataclass
class IdentityReconciliationReport:
    examined_tasks: int = 0
    examined_runs: int = 0
    repaired_tasks: int = 0
    repaired_runs: int = 0
    replayed_events: int = 0
    inbox_backlog: int = 0
    failures: list[str] = field(default_factory=list)


class IdentityProjectionReconciler:
    """只恢复身份投影，不改变 WKN WorkflowRun 的执行状态。"""

    def __init__(self, adapter: WknIdentityLifecycleAdapter) -> None:
        self.adapter = adapter

    def reconcile_workflow_store(
        self,
        workflow_store: Any,
        *,
        limit: int = 200,
    ) -> IdentityReconciliationReport:
        report = IdentityReconciliationReport()
        self._consume_wkn_outbox(workflow_store, report, limit=limit)
        replay = self.adapter.replay_unapplied(limit=limit)
        report.replayed_events = replay["applied"]
        if replay["failed"]:
            report.failures.append(
                f"{replay['failed']} lifecycle projection events could not be replayed"
            )
        page = 1
        while True:
            task_page = workflow_store.list_tasks(page=page, page_size=max(1, limit))
            for task in task_page.items:
                report.examined_tasks += 1
                try:
                    if self.adapter.repositories.user_tasks.get(task.task_id) is None:
                        self.adapter.on_task_created(task)
                        report.repaired_tasks += 1
                except Exception as exc:
                    report.failures.append(f"{task.task_id}: {exc}")
            if page * task_page.page_size >= task_page.total:
                break
            page += 1
        runs = []
        offset = 0
        while True:
            run_page = workflow_store.list_all_runs(offset=offset, limit=max(1, limit))
            runs.extend(run_page)
            if len(run_page) < max(1, limit):
                break
            offset += len(run_page)
        for run in runs:
            report.examined_runs += 1
            try:
                task = workflow_store.get_task(run.task_id)
                if self.adapter.repositories.runs.get(run.run_id) is None:
                    raw_plan = run.execution_state.get("taskPlan")
                    raw_bindings = run.execution_state.get("taskNodeBindings")
                    if (
                        not isinstance(run.acg_blueprint, dict)
                        or not isinstance(raw_plan, dict)
                        or not isinstance(raw_bindings, list)
                    ):
                        raise ValueError(
                            "WKN run lacks persisted TaskPlan identity projection data"
                        )
                    self.adapter.on_run_prepared(
                        task,
                        run,
                        WknBlueprintSpec.model_validate(run.acg_blueprint),
                        TaskPlan.model_validate(raw_plan),
                        tuple(
                            TaskNodeImplementationBinding.model_validate(item)
                            for item in raw_bindings
                        ),
                    )
                    status = str(getattr(run.status, "value", run.status))
                    if status in {"completed", "failed", "cancelled"}:
                        self.adapter.on_run_finished(run.run_id, {
                            "completed": "succeeded",
                            "failed": "failed",
                            "cancelled": "cancelled",
                        }[status])
                    elif status == "superseded":
                        replacement = str(run.execution_state.get("supersededByRunId") or "")
                        if replacement:
                            self.adapter.on_run_superseded(run.run_id, replacement, str(run.execution_state.get("sourcePatchId") or "reconciliation"))
                    report.repaired_runs += 1
                self._audit_run(run)
            except Exception as exc:
                report.failures.append(f"{run.run_id}: {exc}")
        return report

    def _consume_wkn_outbox(
        self,
        workflow_store: Any,
        report: IdentityReconciliationReport,
        *,
        limit: int,
    ) -> None:
        if not hasattr(workflow_store, "list_outbox"):
            return
        events = workflow_store.list_outbox(limit=limit)
        report.inbox_backlog = len(events)
        for event in events:
            try:
                payload = json.loads(event["payload"])
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                payload_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                if event["event_type"] in {"task.snapshot", "task.created"}:
                    self.adapter.on_task_created(AgentTask.model_validate(payload))
                elif event["event_type"] in {"run.snapshot", "run.prepared", "run.finished", "run.superseded"}:
                    wkn_run = workflow_store.get_run(event["aggregate_id"])
                    task = workflow_store.get_task(wkn_run.task_id)
                    raw_plan = wkn_run.execution_state.get("taskPlan")
                    raw_bindings = wkn_run.execution_state.get("taskNodeBindings")
                    if not isinstance(wkn_run.acg_blueprint, dict) or not isinstance(raw_plan, dict) or not isinstance(raw_bindings, list):
                        raise ValueError("WKN run snapshot lacks Planner identity data")
                    self.adapter.on_run_prepared(
                        task,
                        wkn_run,
                        WknBlueprintSpec.model_validate(wkn_run.acg_blueprint),
                        TaskPlan.model_validate(raw_plan),
                        tuple(TaskNodeImplementationBinding.model_validate(item) for item in raw_bindings),
                    )
                    status = str(getattr(wkn_run.status, "value", wkn_run.status))
                    if event["event_type"] == "run.superseded":
                        replacement = str(wkn_run.execution_state.get("supersededByRunId") or "")
                        if replacement:
                            self.adapter.on_run_superseded(wkn_run.run_id, replacement, str(wkn_run.execution_state.get("sourcePatchId") or "outbox"))
                    elif status in {"completed", "failed", "cancelled"}:
                        self.adapter.on_run_finished(wkn_run.run_id, {
                            "completed": "succeeded",
                            "failed": "failed",
                            "cancelled": "cancelled",
                        }[status])
                    status = str(getattr(wkn_run.status, "value", wkn_run.status))
                    if status in {"completed", "failed", "cancelled"}:
                        self.adapter.on_run_finished(wkn_run.run_id, {
                            "completed": "succeeded",
                            "failed": "failed",
                            "cancelled": "cancelled",
                        }[status])
                    elif status == "superseded":
                        replacement = str(wkn_run.execution_state.get("supersededByRunId") or "")
                        if replacement:
                            self.adapter.on_run_superseded(wkn_run.run_id, replacement, str(wkn_run.execution_state.get("sourcePatchId") or "reconciliation"))
                else:
                    raise ValueError(f"unsupported WKN outbox event: {event['event_type']}")
                with self.adapter.repositories.storage.transaction() as conn:
                    existing = conn.execute(
                        "SELECT payload_hash FROM lifecycle_inbox WHERE event_id = ?",
                        (event["event_id"],),
                    ).fetchone()
                    if existing is not None and existing["payload_hash"] != payload_hash:
                        raise ValueError("inbox event id has different content")
                    conn.execute(
                        """INSERT INTO lifecycle_inbox(
                               event_id, event_type, aggregate_id, payload_json, payload_hash,
                               status, attempts, created_at, updated_at
                           ) VALUES (?, ?, ?, ?, ?, 'applied', 1, datetime('now'), datetime('now'))
                           ON CONFLICT(event_id) DO UPDATE SET
                               status='applied', attempts=attempts + 1, updated_at=datetime('now')""",
                        (event["event_id"], event["event_type"], event["aggregate_id"], encoded, payload_hash),
                    )
                workflow_store.mark_outbox(event["event_id"], applied=True)
            except Exception as exc:
                workflow_store.mark_outbox(event["event_id"], applied=False, error=str(exc))
                report.failures.append(f"outbox {event['event_id']}: {exc}")

    def _audit_run(self, wkn_run: Any) -> None:
        run = self.adapter.repositories.runs.get(wkn_run.run_id)
        if run is None:
            raise ValueError("identity WorkflowRun is missing after reconciliation")
        if run.task_id != wkn_run.task_id:
            raise ValueError("WKN and identity Run belong to different tasks")
        blueprint = self.adapter.repositories.blueprints.get(run.blueprint_id)
        if blueprint is None:
            raise ValueError("identity Run Blueprint is missing")
        if int(blueprint.version) != int(run.graph_version):
            raise ValueError("identity Run graphVersion is inconsistent")
        wkn_terminal = str(getattr(wkn_run.status, "value", wkn_run.status)) in {
            "completed", "failed", "cancelled"
        }
        if not wkn_terminal and run.status in {
            RunStatus.FAILED,
            RunStatus.SUCCEEDED,
            RunStatus.CANCELLED,
            RunStatus.SUPERSEDED,
        }:
            raise ValueError("non-terminal WKN Run points to terminal identity Run")


__all__ = ["IdentityProjectionReconciler", "IdentityReconciliationReport"]
