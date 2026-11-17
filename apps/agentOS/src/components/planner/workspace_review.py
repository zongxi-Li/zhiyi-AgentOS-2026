"""Receipt-derived, additive semantic work for the remaining workspace scope.

This module proposes TaskPlanPatch values only. The existing Planning Commit,
graph revision, safe-cut and execution handoff authorities still decide whether
the proposal may become executable. A page is a work unit, not a retry limit.
"""
from __future__ import annotations

import json

from contracts import stable_checksum
from contracts.artifacts import is_final_synthesis_role
from contracts.execution_evidence import workspace_coverage_fingerprint, workspace_relative_path
from contracts.planning import PlannedTask, TaskPlan, TaskPlanPatch, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningDecision, RuntimePlanningObservation


WORKSPACE_REVIEW_SOURCE = "workspace_review"
WORKSPACE_ACQUISITION_TASK = "workspace_acquisition"
WORKSPACE_REVIEW_TASK = "workspace_review"


def _decision(observation, action, reason, patch=None):
    return RuntimePlanningDecision(observationId=observation.fingerprint(), action=action,
        reason=reason, taskPlanPatch=patch)


def _batch_scope(node):
    for constraint in node.constraints:
        value = constraint.get("workspaceReview")
        if isinstance(value, dict):
            return value
    return {}


def _targets(progress, batch_size):
    seen, result = set(), []
    # Discover the outstanding tree before assuming the visible file page is
    # the complete repository. Subsequent observations expose the next page.
    for field, operation in (("missingListings", "list"), ("missingReads", "read")):
        for item in progress:
            for raw in item.get(field, ()):
                path = workspace_relative_path(raw)
                key = (operation, path)
                if key not in seen:
                    seen.add(key)
                    result.append({"operation": operation, "path": path})
                if len(result) >= batch_size:
                    return result
    return result


def workspace_review_decision(*, observation: RuntimePlanningObservation, task_plan: TaskPlan,
                              batch_size: int = 16) -> RuntimePlanningDecision | None:
    """Schedule one remaining evidence page and its review, reusing the prefix.

    ``None`` leaves unrelated planning to the existing Planner. Confirmed
    coverage always comes from the host observation, never Agent output claims.
    Neither the number of generated pages nor the number of revisions is capped.
    """
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("workspace work page must contain at least one operation")
    progress = observation.workspace_observations
    if not progress or all(item.get("complete") is True for item in progress):
        return None
    if observation.mission_id != task_plan.mission_id or observation.plan_version != task_plan.plan_version:
        raise ValueError("workspace review must use the current Mission TaskPlan")
    if (observation.failed_step_ids or observation.failure_type in {"policy", "storage"}
            or observation.wake_reason in {"failure", "user_input"}
            or any(blocker.startswith(("review_unresolved:", "artifact_unsealed:", "artifact_content_integrity:"))
                   for blocker in observation.completion_blockers)):
        return None

    remaining_ids = set(observation.remaining_step_ids)
    pending = {item.task_key for item in observation.steps if item.step_id in remaining_ids}
    committed = {item.task_key for item in observation.steps if item.output_ref is not None}
    fingerprint = workspace_coverage_fingerprint(progress)
    batches = [node for node in task_plan.nodes if node.metadata.get("source") == WORKSPACE_REVIEW_SOURCE]
    readers = [node for node in batches if node.metadata.get("taskType") == WORKSPACE_ACQUISITION_TASK]
    if any(node.key in pending for node in batches):
        return _decision(observation, "continue", "Execute the already-declared workspace acquisition/review "
            "page before proposing another page; reuse all committed receipt-verified coverage.")
    if readers:
        latest = readers[-1]
        if (latest.key in committed and _batch_scope(latest).get("coverageFingerprint") == fingerprint):
            return _decision(observation, "wait", "WORKSPACE_REVIEW_NO_PROGRESS: the submitted acquisition "
                "did not add receipt-verified coverage. Preserve the remaining scope and resolve the tool, "
                "authorization or unreadable-source blocker before repeating the same work.")
    if any(node.key in pending and node.capability_requirements
           and node.capability_requirements[0] == "information_extraction" for node in task_plan.nodes):
        return _decision(observation, "continue", "The current plan already has pending workspace acquisition; "
            "observe its committed results before proposing supplemental reads.")
    if any(node.key in pending and node.capability_requirements
           and node.capability_requirements[0] == "task_understanding" for node in task_plan.nodes):
        return _decision(observation, "continue", "Finish the declared task-understanding prefix before "
            "adding receipt-scoped workspace acquisition.")
    if any(node.key in committed and is_final_synthesis_role(node.logical_role) for node in task_plan.nodes):
        return _decision(observation, "wait", "WORKSPACE_REVIEW_FINAL_ALREADY_COMMITTED: the frozen source "
            "scope is still incomplete after delivery. A new accepted delivery plan is required; "
            "committed results cannot be silently relabeled or declared complete.")
    targets = _targets(progress, batch_size)
    if not targets:
        return _decision(observation, "wait", "WORKSPACE_SCOPE_UNRESOLVED: the remaining workspace scope "
            "contains unsupported or unresolved entries. Obtain explicit scope resolution; symlinks, "
            "binary data and failed/partial reads cannot be silently counted as inspected source text.")

    identity = stable_checksum({"mission": task_plan.mission_id, "planVersion": task_plan.plan_version,
        "coverageFingerprint": fingerprint, "targets": targets})[:24]
    reader_key, reviewer_key = "workspace_read:" + identity, "workspace_review:" + identity
    if {reader_key, reviewer_key} & {node.key for node in task_plan.nodes}:
        return _decision(observation, "wait", "WORKSPACE_REVIEW_IDENTITY_CONFLICT: this coverage page "
            "already exists without a schedulable current observation; preserve its evidence for review.")
    scope = {"coverageFingerprint": fingerprint, "targets": targets}
    reader = PlannedTask(key=reader_key, title="补读剩余仓库范围", logicalRole="workspace_acquisition",
        objective="Acquire only this page of receipt-unverified workspace paths using the authorized "
            "fs.list/fs.read tools: " + json.dumps(targets, ensure_ascii=False, separators=(",", ":"))
            + ". The workspace root is '.'. Reuse the runtime's verified prefix; do not restart a full "
            "repository scan. Read means source contents, not only names. Return confirmed scoped findings "
            "after useful progress so ACG can review and schedule the remaining pages. While reading, inspect "
            "actual source for correctness, security and integration issues relevant to the mission. Cite "
            "relative files and precise line/symbol evidence for actionable findings; distinguish suspected "
            "risks from confirmed defects. No findings in this page is not a repository-wide clean bill.",
        capabilityRequirements=("information_extraction",),
        acceptanceCriteria=("Every claimed observation is supported by a successful complete tool receipt.",
            "Report failed, unreadable, partial or still-pending paths explicitly; do not claim global completion."),
        constraints=[{"workspaceReview": scope}],
        metadata={"source": WORKSPACE_REVIEW_SOURCE, "taskType": WORKSPACE_ACQUISITION_TASK})
    reviewer = PlannedTask(key=reviewer_key, title="审查本批证据与剩余范围", logicalRole="workspace_review",
        objective="Review the new acquisition page together with the committed upstream repository findings. "
            "Check that findings cite actual inspected contents and identify substantive code issues. "
            "State any unresolved acquisition or analysis gaps explicitly. Verify this page's supported "
            "claims; a passed batch review is not proof that the entire repository has been read. "
            "Use authorized context or workspace tools for targeted verification when supplied findings "
            "do not contain enough source evidence. Receipt metadata proves an observation occurred, not "
            "that an arbitrary code claim is correct. A supported review may pass even when it reports code "
            "defects or other source pages remain; partial/failed means this page's checks remain unresolved. "
            "Runtime receipt coverage determines the remaining global scope and subsequent acquisition pages.",
        capabilityRequirements=("verification",),
        acceptanceCriteria=("Validate the acquired page against its receipt-backed observations.",
            "Preserve explicit unresolved global scope for the next ACG observation."),
        constraints=[{"workspaceReview": scope}],
        metadata={"source": WORKSPACE_REVIEW_SOURCE, "taskType": WORKSPACE_REVIEW_TASK})
    edges = [relation for relation in task_plan.relations if relation.relation_type.value == "depends_on"]
    frontier = committed - {relation.source_key for relation in edges if relation.target_key in committed}
    roots = pending - {relation.target_key for relation in edges if relation.source_key in pending}
    links = [(key, reader_key) for key in sorted(frontier)] + [(reader_key, reviewer_key)]
    links.extend((reviewer_key, key) for key in sorted(roots))
    # Adding predecessors only to untouched work keeps immutable node commits
    # and their existing incoming obligations outside the patch.
    patch = TaskPlanPatch(missionId=task_plan.mission_id, basePlanVersion=task_plan.plan_version,
        planVersion=task_plan.plan_version + 1, addNodes=(reader, reviewer),
        relations=tuple(TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")
                        for source, target in links),
        metadata={"source": WORKSPACE_REVIEW_SOURCE,
            "rationale": "Acquire and review the next receipt-unverified workspace page; preserve the frozen scope."})
    return _decision(observation, "revise", "Receipt-verified workspace coverage has remaining source scope. "
        "Add one acquisition page and its dependent review before the unexecuted suffix.", patch)


__all__ = ["workspace_review_decision"]
