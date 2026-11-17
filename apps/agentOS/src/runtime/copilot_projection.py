"""Public planning explanations and execution receipts for the task conversation."""
from contracts.planning import TaskPlan
from contracts.workflow import WorkflowStatus
from support.stores._policy import acg_review_subject


def planning_progress(run):
    """Project in-flight planner repair as read-only execution progress."""
    state = run.execution_state
    rejection = state.get("planningCommitRejection")
    loop = state.get("planningLoop") or {}
    current = loop.get("current") or {}
    status = getattr(run.status, "value", run.status)
    if state.get("reviewPayload") or status not in {"retrying", "running", "planning"}:
        return None
    pending = state.get("workspaceReviewContinuation")
    activation = state.get("graphActivation") or {}
    source_version = pending.get("sourceGraphVersion") if isinstance(pending, dict) else None
    if (isinstance(pending, dict) and not pending.get("blocked")
            and pending.get("observationId") and pending["observationId"] == current.get("observationId")
            and type(source_version) is int and source_version >= 1
            and state.get("graphVersion") == source_version + 1
            and activation.get("sourceGraphVersion") == source_version
            and activation.get("activeGraphVersion") == state.get("graphVersion")):
        return {
            "kind": "repairing", "status": status,
            "message": "正在将审查发现的缺口补入执行图，完成交接后继续读取",
            "observationId": str(pending["observationId"]),
            "errorCode": "WORKSPACE_REVIEW_REVISION_PENDING",
        }
    if not isinstance(rejection, dict) or not rejection.get("observationId"):
        return None
    observing_repair = (current.get("status") in {"observed", "decided"}
        and (current.get("observation") or {}).get("planningCommitRejection") == rejection)
    if loop.get("restartPending") is not True and not observing_repair:
        return None
    return {
        "kind": "repairing", "status": status,
        "message": "正在根据审查反馈自动修正计划",
        "observationId": str(rejection["observationId"]),
        "errorCode": str(rejection.get("code") or "PLANNING_COMMIT_REJECTED"),
    }


def _revision_failure_reason(reason):
    """Explain a recorded rejection without suggesting it is an approval wait."""
    if "started or settled work cannot be changed" in reason:
        return "修订方案试图更改已开始或已有最终结果的步骤，正式校验已拒绝该方案。"
    if "outcome" in reason.lower() and "unknown" in reason.lower():
        return "部分步骤的执行结果尚未确认，需要先核实执行结果，再决定后续处理方式。"
    return "计划修订未通过正式校验，任务仍处于暂停状态。请查看技术详情中的拒绝原因。"


def review_summary(run, current=None):
    """Project the current review's cause; never approve or mutate a barrier."""
    payload = run.execution_state.get("reviewPayload") or {}
    if run.status != WorkflowStatus.WAITING_REVIEW or not payload:
        return None
    subject_type, subject_id = acg_review_subject(payload)
    planner = subject_type == "planner"
    rejected = bool(planner and current and current.status == "rejected")
    review = {
        "subjectId": subject_id, "subjectType": subject_type,
        "reason": payload.get("reason", ""), "reasonCode": payload.get("reasonCode", ""),
        "kind": "planner_rejected" if rejected else "planner_wait" if planner else "step_review",
        "canApprove": not rejected, "decisionRejected": rejected,
        "expectedRunUpdatedAt": run.updated_at.isoformat(),
    }
    if rejected and isinstance(getattr(current, "rejection", None), str):
        review["reason"] = current.rejection
    pending = run.execution_state.get("workspaceReviewContinuation")
    rejection = run.execution_state.get("planningCommitRejection")
    observation_id = payload.get("observationId")
    if (planner and isinstance(pending, dict) and observation_id
            and pending.get("observationId") == observation_id):
        blocked = pending.get("blocked") is True
        review.update(kind="workspace_revision_blocked" if blocked else "workspace_revision_pending",
            reasonCode="WORKSPACE_REVIEW_REVISION_BLOCKED" if blocked else "WORKSPACE_REVIEW_REVISION_PENDING",
            canApprove=False, decisionRejected=blocked,
            displayReason=_revision_failure_reason(str(pending.get("reason") or "")) if blocked else
                "系统正在处理审查计划的自动修订，完成正式校验后会继续执行。")
        if blocked:
            review["reason"] = str(pending.get("reason") or review["reason"])
            for key in ("errorCode", "errorType"):
                if isinstance(pending.get(key), str):
                    review[key] = pending[key]
    elif planner and (
            isinstance(rejection, dict) and observation_id and rejection.get("observationId") == observation_id
            or payload.get("reasonCode") == "PLANNING_COMMIT_REJECTED"):
        matching = rejection if isinstance(rejection, dict) and rejection.get("observationId") == observation_id else {}
        reason = str(matching.get("reason") or getattr(current, "rejection", None) or review["reason"])
        review.update(kind="planner_rejected", reasonCode="PLANNING_COMMIT_REJECTED",
            reason=reason, displayReason=_revision_failure_reason(reason), canApprove=False, decisionRejected=True)
        if isinstance(matching.get("code"), str):
            review["errorCode"] = matching["code"]
    return review


def initial_plan_summary(runtime, run):
    """Project frozen, explicit plan fields; never expose provider reasoning buffers."""
    plan = run.execution_state.get("taskPlan")
    record = None
    authority = getattr(runtime, "planning_commit_authority", None)
    if authority is not None:
        record = authority.store.get_by_idempotency_key("initial-planning:" + run.run_id)
        if record is not None:
            if (record.mission_id != run.mission_id or record.proposal_type != "initial_plan"
                    or getattr(record.source_provenance, "source_run_id", None) != run.run_id):
                return None
            plan = record.proposal_payload
    if not plan:
        return None
    try:
        plan = TaskPlan.model_validate(plan)
    except ValueError:
        return None
    if plan.mission_id != run.mission_id:
        return None
    basis = run.execution_state.get("missionIntentBasis") or {}
    constraints = []
    for node in plan.nodes:
        for constraint in node.constraints:
            text = constraint.get("value") or constraint.get("description")
            if isinstance(text, str) and text.strip() and text not in constraints:
                constraints.append(text)
    return {
        "planVersion": plan.plan_version,
        "commitId": record.commit_id if record else None,
        "commitmentRevision": record.commitment_revision if record else None,
        "objective": basis.get("objective") or run.input.get("taskGoal") or "",
        "constraints": constraints,
        "expectedArtifacts": list(plan.expected_artifacts),
        "tasks": [{"key": node.key, "title": node.title, "objective": node.objective,
                   "rationale": node.decomposition_rationale,
                   "acceptanceCriteria": list(node.acceptance_criteria),
                   "sourceRefs": list(node.source_refs)} for node in plan.nodes],
    }
