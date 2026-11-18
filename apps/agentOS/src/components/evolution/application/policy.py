"""Controlled policy evolution without Runtime or concrete storage dependencies."""
from datetime import datetime, timezone

from contracts import stable_checksum
from contracts.evolution import (
    EvolutionPolicyVersion, EvolutionProposal, EvolutionProposalStatus, PolicyMutation,
    Trajectory, TrajectoryEvaluation,
)
from components.evolution.domain.policy import (
    evaluate_trajectory, next_policy, require_mutation, require_proposal,
    require_replay, require_reviewer, unique_trajectories,
)
from components.evolution.ports.store import EvolutionStore


class EvolutionService:
    def __init__(self, *, store: EvolutionStore, proposal_threshold: int = 3) -> None:
        if isinstance(proposal_threshold, bool) or not isinstance(proposal_threshold, int) or proposal_threshold < 1:
            raise ValueError("proposal_threshold must be a positive integer")
        self.store = store
        self.proposal_threshold = proposal_threshold

    def evaluate(self, trajectory: Trajectory) -> TrajectoryEvaluation:
        trajectory = trajectory.model_copy(deep=True)
        self.store.save_trajectory(trajectory)
        return self.store.save_evaluation(evaluate_trajectory(trajectory))

    def propose(self, trajectories: list[Trajectory], mutation: PolicyMutation) -> EvolutionProposal | None:
        require_mutation(mutation)
        ordered = unique_trajectories([t.model_copy(deep=True) for t in trajectories])
        if len(ordered) < self.proposal_threshold:
            return None
        evaluations = [self.evaluate(item) for item in ordered]
        active = self.store.active()
        ids = [item.trajectory_id for item in ordered]
        proposal = EvolutionProposal(
            proposalId=f"evolution:{stable_checksum([active.version, ids, mutation])[:16]}",
            baseVersion=active.version, trajectoryIds=ids, mutations=[mutation],
            evaluationChecksum=stable_checksum(evaluations),
            status=EvolutionProposalStatus.PENDING_REVIEW,
        )
        self.validate_proposal(proposal)
        return self.store.save_proposal(proposal)

    def validate_proposal(self, proposal: EvolutionProposal) -> None:
        require_proposal(proposal, self.store.active().version,
                         [self.store.get_evaluation(item) for item in proposal.trajectory_ids])

    def approve(self, proposal: EvolutionProposal, *, approved_by: str) -> EvolutionPolicyVersion:
        proposal = proposal.model_copy(deep=True)
        reviewer = require_reviewer(approved_by)
        try:
            receipt = self.store.get_receipt(proposal.proposal_id)
        except KeyError:
            receipt = None
        if receipt is not None:
            require_replay(receipt, proposal, reviewer)
            return self.store.get(receipt.policy_version)
        if proposal.status is not EvolutionProposalStatus.PENDING_REVIEW:
            raise ValueError("only a validated pending proposal can be approved")
        # The store revalidates evidence, content and CAS inside the commit lock.
        # Separate preflight reads here would race a concurrent identical retry.
        reviewed_at = datetime.now(timezone.utc)
        version = EvolutionPolicyVersion(
            version=proposal.base_version + 1, baseVersion=proposal.base_version,
            proposalIds=[proposal.proposal_id],
            policy=next_policy(self.store.get(proposal.base_version), proposal),
            approvedBy=reviewer, createdAt=reviewed_at,
        )
        approved = proposal.model_copy(update={"status": EvolutionProposalStatus.APPROVED,
            "reviewed_by": reviewer, "reviewed_at": reviewed_at})
        receipt = self.store.commit_approval(version, approved, expected_active=proposal.base_version)
        return self.store.get(receipt.policy_version)

    def rollback(self, target_version: int, *, approved_by: str) -> EvolutionPolicyVersion:
        reviewer = require_reviewer(approved_by)
        target, active = self.store.get(target_version), self.store.active()
        return self.store.create(EvolutionPolicyVersion(
            version=active.version + 1, baseVersion=active.version,
            proposalIds=[f"rollback:{target_version}"], policy=dict(target.policy),
            approvedBy=reviewer,
        ), expected_active=active.version)
