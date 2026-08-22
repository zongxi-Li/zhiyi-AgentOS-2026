"""WorkflowStore adapters共享的纯筛选、排序与终态覆盖策略。"""

from __future__ import annotations

from contracts.workflow import (
    RuntimeMissionRecord,
    RuntimeRunRecord,
    StepStatus,
    WorkflowStatus,
)


TERMINAL_RUN_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.SUPERSEDED,
    }
)


def acg_review_subject(payload: object) -> tuple[str, str]:
    """Return the single persisted ACG review subject from canonical or v1 payloads."""

    if not isinstance(payload, dict):
        raise ValueError("ACG review payload must be an object")
    subject_type = payload.get("subjectType")
    subject_id = payload.get("subjectId")
    step_id = payload.get("stepId")
    control_id = payload.get("controlId")
    if subject_type is None and subject_id is None:
        if isinstance(step_id, str) and step_id:
            subject_type, subject_id = "step", step_id
        elif isinstance(control_id, str) and control_id:
            subject_type, subject_id = "control", control_id
    if subject_type not in {"step", "control"}:
        raise ValueError("ACG review payload has no valid subjectType")
    if not isinstance(subject_id, str) or not subject_id:
        raise ValueError("ACG review payload has no subjectId")
    legacy_id = step_id if subject_type == "step" else control_id
    if legacy_id is not None and legacy_id != subject_id:
        raise ValueError("ACG review payload subject identifiers conflict")
    if subject_type == "step" and control_id is not None:
        raise ValueError("ACG step review payload also declares a controlId")
    if subject_type == "control" and step_id is not None:
        raise ValueError("ACG control review payload also declares a stepId")
    return subject_type, subject_id


def validate_run_state(run: RuntimeRunRecord) -> None:
    """Reject snapshots whose Run lifecycle has no recoverable execution fact."""

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
        return
    if run.status == WorkflowStatus.FAILED:
        if statuses & {StepStatus.RUNNING, StepStatus.RETRYING}:
            raise ValueError(f"failed workflow run has active steps: {run.run_id}")
        return
    if run.status != WorkflowStatus.WAITING_REVIEW:
        return
    if (run.runtime_engine or "").strip().lower() != "acg":
        if StepStatus.WAITING_REVIEW not in statuses:
            raise ValueError(
                f"waiting_review workflow run has no waiting_review step: {run.run_id}"
            )
        return

    checkpoint_id = run.execution_state.get("checkpointId")
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        raise ValueError(f"waiting_review ACG run has no checkpoint: {run.run_id}")
    subject_type, subject_id = acg_review_subject(
        run.execution_state.get("reviewPayload")
    )
    if run.current_step_id != subject_id:
        raise ValueError(f"waiting_review ACG run subject is not current: {run.run_id}")
    if subject_type == "step":
        step = next((item for item in run.steps if item.step_id == subject_id), None)
        if step is None or step.status is not StepStatus.WAITING_REVIEW:
            raise ValueError(
                f"waiting_review ACG run has no waiting_review subject step: {run.run_id}"
            )
        return
    blueprint = run.acg_blueprint if isinstance(run.acg_blueprint, dict) else {}
    nodes = blueprint.get("nodes") if isinstance(blueprint.get("nodes"), list) else []
    subject = next(
        (item for item in nodes if isinstance(item, dict) and item.get("nodeId") == subject_id),
        None,
    )
    if not isinstance(subject, dict) or subject.get("nodeType") != "control":
        raise ValueError(
            f"waiting_review ACG run has no declared control subject: {run.run_id}"
        )


def matches_mission(
    task: RuntimeMissionRecord,
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
    run: RuntimeRunRecord,
    *,
    status: str | None,
    statuses: set[str] | None,
    domain: str | None,
    workflow_id: str | None,
    mission_id: str | None,
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
    if mission_id is not None and run.mission_id != mission_id:
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


def run_priority(run: RuntimeRunRecord) -> int:
    if run.status == WorkflowStatus.WAITING_REVIEW:
        return 2
    if run.status not in TERMINAL_RUN_STATUSES:
        return 1
    return 0


def reject_terminal_overwrite(existing: RuntimeRunRecord, incoming: RuntimeRunRecord) -> bool:
    if existing.status == WorkflowStatus.FAILED and incoming.status == WorkflowStatus.RETRYING:
        return False
    if existing.status in TERMINAL_RUN_STATUSES and incoming.status != existing.status:
        return True
    return existing.status in TERMINAL_RUN_STATUSES and incoming.updated_at < existing.updated_at
