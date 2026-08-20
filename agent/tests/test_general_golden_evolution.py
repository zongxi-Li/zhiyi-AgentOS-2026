"""Evolution projection and policy versioning from a completed Core General run."""

from __future__ import annotations

from adapters.model.native import GENERAL_EVIDENCE_WORKFLOW_ID
from app.execution.wiring import build_default_runtime, close_runtime
from contracts.workflow import ReviewDecision, ReviewDecisionType, WorkflowStatus


def _environment(tmp_path) -> dict[str, str]:
    return {
        "AGENTOS_WORKFLOW_DB_PATH": str(tmp_path / "workflows.sqlite3"),
        "AGENTOS_LANGGRAPH_CHECKPOINT_DB": str(tmp_path / "checkpoints.sqlite3"),
        "AGENTOS_EXECUTION_VALUE_DB": str(tmp_path / "values.sqlite3"),
        "AGENTOS_EXECUTION_MEMORY_DB": str(tmp_path / "memory.sqlite3"),
        "AGENTOS_PROVENANCE_DB": str(tmp_path / "provenance.sqlite3"),
        "AGENTOS_AUDIT_DB": str(tmp_path / "decisions.sqlite3"),
        "AGENTOS_RESOURCE_DB": str(tmp_path / "resources.sqlite3"),
        "AGENTOS_EVOLUTION_DB": str(tmp_path / "evolution.sqlite3"),
    }


async def _complete_general_run(runtime):
    task = runtime.create_task(
        title="Compare two deployment designs and cite the release evidence",
        domain="general",
        intent="evidence_decision",
        workflow_id=GENERAL_EVIDENCE_WORKFLOW_ID,
        input={
            "userIntent": (
                "Extract requirements, retrieve release evidence, compare both designs, "
                "verify the recommendation, and write a cited decision report."
            ),
            "constraints": ["cite every material conclusion"],
            "thinkingMode": "disabled",
        },
    )
    paused = await runtime.start(
        task.task_id,
        workflow_id=GENERAL_EVIDENCE_WORKFLOW_ID,
        review_mode="human_in_loop",
    )
    assert paused.status is WorkflowStatus.WAITING_REVIEW
    completed = await runtime.apply_review(ReviewDecision(
        runId=paused.run_id,
        stepId=paused.current_step_id,
        decision=ReviewDecisionType.APPROVED,
        operationId=f"approve:{paused.run_id}",
        reviewer="evolution-reviewer",
        comment="evidence decision approved",
    ))
    assert completed.status is WorkflowStatus.COMPLETED
    return completed


async def test_trajectory_is_deterministic_and_uses_real_run_sources(tmp_path) -> None:
    runtime = build_default_runtime(environment=_environment(tmp_path))
    try:
        completed = await _complete_general_run(runtime)
        first = runtime.propose_evolution_from_run(completed.run_id)
        second = runtime.propose_evolution_from_run(completed.run_id)

        assert first == second
        trajectory, evaluation, proposal = first
        assert trajectory.task["runId"] == completed.run_id
        assert trajectory.outcome["checkpointId"] == completed.execution_state["checkpointId"]
        assert trajectory.outcome["phaseCapsuleRefs"]
        assert trajectory.outcome["traceRefs"] == [event.event_id for event in completed.trace]
        assert len(trajectory.steps) == len(completed.steps)
        assert any(step.input["candidateCount"] > 0 for step in trajectory.steps)
        assert any(step.input["memoryEventRef"] for step in trajectory.steps)
        assert any(step.output["provenanceRefs"] for step in trajectory.steps)
        assert evaluation.trajectory_id == trajectory.trajectory_id
        assert evaluation.success_score == 1
        assert proposal.trajectory_ids == [trajectory.trajectory_id]
        assert proposal.status.value == "pending_review"
    finally:
        close_runtime(runtime)


async def test_approved_real_run_proposal_only_changes_future_general_runs(tmp_path) -> None:
    environment = _environment(tmp_path)
    runtime = build_default_runtime(environment=environment)
    try:
        completed = await _complete_general_run(runtime)
        old_run_id = completed.run_id
        old_step_inputs = {
            step.step_id: dict(step.input)
            for step in completed.steps
        }
        _, _, proposal = runtime.propose_evolution_from_run(old_run_id)
        version = runtime.approve_evolution_proposal(
            proposal.proposal_id,
            approved_by="policy-reviewer",
        )
        assert version.version == 1
        assert version.policy["budget_adjustment:memory_token_budget"] == 768

        next_task = runtime.create_task(
            title="Evaluate the follow-up architecture decision",
            domain="general",
            intent="evidence_decision",
            workflow_id=GENERAL_EVIDENCE_WORKFLOW_ID,
            input={"userIntent": "Produce a verified evidence decision."},
        )
        _, next_run = runtime.prepare_run(
            next_task.task_id,
            workflow_id=GENERAL_EVIDENCE_WORKFLOW_ID,
        )
        persisted_old = runtime.get_status(old_run_id)

        assert persisted_old.execution_state["evolutionPolicyVersion"] == 0
        assert {step.step_id: step.input for step in persisted_old.steps} == old_step_inputs
        assert next_run.execution_state["evolutionPolicyVersion"] == 1
        assert next_run.execution_state["appliedEvolutionPolicy"] == {
            "memoryTokenBudget": 768
        }
        memory_policies = [
            step.input["memoryPolicy"]
            for step in next_run.steps
            if "memoryPolicy" in step.input
        ]
        assert memory_policies
        assert all(policy["tokenBudget"] == 768 for policy in memory_policies)
    finally:
        close_runtime(runtime)
