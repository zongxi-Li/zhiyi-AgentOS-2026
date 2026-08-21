"""WorkflowStore adapters共享的纯筛选、排序与终态覆盖策略。"""

from __future__ import annotations

from contracts.workflow import AgentTask, WorkflowRun, WorkflowStatus


TERMINAL_RUN_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.SUPERSEDED,
    }
)


def matches_task(
    task: AgentTask,
    *,
    status: str | None,
    domain: str | None,
    source: str | None,
) -> bool:
    if status is not None and task.status.value != status:
        return False
    if domain is not None and task.domain != domain:
        return False
    return source is None or task.input.get("source") == source


def matches_run(
    run: WorkflowRun,
    *,
    status: str | None,
    statuses: set[str] | None,
    domain: str | None,
    workflow_id: str | None,
    task_id: str | None,
    lifecycle_phase: str | None,
    source: str | None,
    sources: set[str] | None,
    owner_user_id: str | None,
    owner_tenant_id: str | None,
) -> bool:
    if status is not None and run.status.value != status:
        return False
    if statuses is not None and run.status.value not in statuses:
        return False
    if domain is not None and run.domain != domain:
        return False
    if workflow_id is not None and run.workflow_id != workflow_id:
        return False
    if task_id is not None and run.task_id != task_id:
        return False
    phase = run.lifecycle_phase.value if run.lifecycle_phase is not None else None
    if lifecycle_phase is not None and phase != lifecycle_phase:
        return False
    if source is not None and run.input.get("source") != source:
        return False
    if sources is not None and run.input.get("source") not in sources:
        return False
    run_owner = str(run.input.get("authenticatedUserId") or "").strip()
    run_tenant = str(run.input.get("authenticatedTenantId") or "").strip()
    if run_owner and run_owner != owner_user_id:
        return False
    if run_owner and run_tenant and run_tenant != owner_tenant_id:
        return False
    return True


def run_priority(run: WorkflowRun) -> int:
    if run.status == WorkflowStatus.WAITING_REVIEW:
        return 2
    if run.status not in TERMINAL_RUN_STATUSES:
        return 1
    return 0


def reject_terminal_overwrite(existing: WorkflowRun, incoming: WorkflowRun) -> bool:
    if existing.status == WorkflowStatus.FAILED and incoming.status == WorkflowStatus.RETRYING:
        return False
    if existing.status in TERMINAL_RUN_STATUSES and incoming.status != existing.status:
        return True
    return existing.status in TERMINAL_RUN_STATUSES and incoming.updated_at < existing.updated_at
