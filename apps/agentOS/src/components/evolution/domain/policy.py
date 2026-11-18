"""Evidence, scoring and approval invariants shared by the use case and stores."""
from math import isfinite

from contracts import stable_checksum
from contracts.evolution import (
    EvolutionPolicyVersion, EvolutionProposal, EvolutionProposalStatus,
    EvolutionPublicationReceipt, PolicyMutation, Trajectory, TrajectoryEvaluation,
)


def unique_trajectories(trajectories: list[Trajectory]) -> list[Trajectory]:
    values: dict[str, Trajectory] = {}
    for item in trajectories:
        if item.trajectory_id in values and values[item.trajectory_id] != item:
            raise ValueError("conflicting trajectory evidence")
        values[item.trajectory_id] = item
    return [values[key] for key in sorted(values)]


def evaluate_trajectory(trajectory: Trajectory) -> TrajectoryEvaluation:
    completed = str(trajectory.outcome.get("status", "")).lower() in {"completed", "success"}
    success = 1.0 if completed or trajectory.outcome.get("success") is True else 0.0
    failed = sum(bool(step.feedback.get("error")) for step in trajectory.steps)
    quality = float(trajectory.outcome.get("quality", success))
    if not isfinite(quality) or quality < 0:
        raise ValueError("trajectory quality must be finite and non-negative")
    return TrajectoryEvaluation(
        trajectoryId=trajectory.trajectory_id, successScore=success,
        efficiencyScore=max(0.0, 1.0 - failed / max(len(trajectory.steps), 1)),
        noveltyScore=0.0, qualityScore=min(1.0, quality),
        evidence={"stepCount": len(trajectory.steps), "failedSteps": failed},
    )


def require_reviewer(approved_by: str) -> str:
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise ValueError("evolution proposal reviewer is required")
    return approved_by.strip()


def require_mutation(mutation: PolicyMutation) -> None:
    # Revalidate model_copy inputs as well as normally parsed DTOs.
    mutation = PolicyMutation.model_validate(mutation.model_dump())
    if not mutation.target.strip():
        raise ValueError("mutation target is required")
    if mutation.mutation_type == "budget_adjustment":
        if (not isinstance(mutation.value, (int, float)) or isinstance(mutation.value, bool)
                or not isfinite(mutation.value) or mutation.value <= 0):
            raise ValueError("budget adjustment must be a finite positive number")


def proposal_checksum(proposal: EvolutionProposal) -> str:
    return stable_checksum(proposal.model_dump(by_alias=True, mode="json",
        exclude={"status", "reviewed_by", "reviewed_at"}))


def require_proposal(proposal: EvolutionProposal, active_version: int,
                     evaluations: list[TrajectoryEvaluation]) -> None:
    if proposal.base_version != active_version:
        raise ValueError("proposal base version is stale")
    if not proposal.trajectory_ids or len(set(proposal.trajectory_ids)) != len(proposal.trajectory_ids):
        raise ValueError("proposal requires distinct trajectory evidence")
    if [item.trajectory_id for item in evaluations] != proposal.trajectory_ids:
        raise ValueError("proposal evaluation identity is invalid")
    if stable_checksum(evaluations) != proposal.evaluation_checksum:
        raise ValueError("proposal evaluation checksum is invalid")
    if not proposal.mutations:
        raise ValueError("proposal requires mutations")
    for mutation in proposal.mutations:
        require_mutation(mutation)


def next_policy(active: EvolutionPolicyVersion, proposal: EvolutionProposal) -> dict:
    policy = dict(active.policy)
    for mutation in proposal.mutations:
        policy[f"{mutation.mutation_type}:{mutation.target}"] = mutation.value
    return policy


def require_transition(existing: EvolutionProposal | None, value: EvolutionProposal) -> None:
    if existing is None or existing == value:
        return
    if existing.model_copy(update={"status": value.status, "reviewed_by": value.reviewed_by,
                                    "reviewed_at": value.reviewed_at}) != value:
        raise ValueError("proposal content cannot change after validation")
    if existing.status is not EvolutionProposalStatus.PENDING_REVIEW or value.status not in {
        EvolutionProposalStatus.APPROVED, EvolutionProposalStatus.REJECTED,
    }:
        raise ValueError("invalid evolution proposal status transition")


def publication_receipt(active: EvolutionPolicyVersion, pending: EvolutionProposal,
                        approved: EvolutionProposal, value: EvolutionPolicyVersion,
                        evaluations: list[TrajectoryEvaluation]) -> EvolutionPublicationReceipt:
    require_proposal(pending, active.version, evaluations)
    reviewer = require_reviewer(approved.reviewed_by)
    require_transition(pending, approved)
    if (pending.status is not EvolutionProposalStatus.PENDING_REVIEW
            or approved.status is not EvolutionProposalStatus.APPROVED or approved.reviewed_at is None
            or approved.reviewed_by != reviewer or value.approved_by != reviewer
            or value.base_version != active.version or value.version != active.version + 1
            or value.status != "active" or value.proposal_ids != [pending.proposal_id]
            or value.policy != next_policy(active, pending)):
        raise ValueError("inconsistent evolution publication")
    return EvolutionPublicationReceipt(proposalId=pending.proposal_id,
        proposalChecksum=proposal_checksum(pending), policyVersion=value.version,
        approvedBy=reviewer, publishedAt=approved.reviewed_at)


def require_replay(receipt: EvolutionPublicationReceipt, proposal: EvolutionProposal,
                   approved_by: str) -> None:
    if (receipt.proposal_id != proposal.proposal_id
            or receipt.proposal_checksum != proposal_checksum(proposal)
            or receipt.approved_by != require_reviewer(approved_by)):
        raise ValueError("publication content or reviewer conflicts with existing receipt")
