"""Public planning explanations and execution receipts for the task conversation."""
from contracts.planning import TaskPlan


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
