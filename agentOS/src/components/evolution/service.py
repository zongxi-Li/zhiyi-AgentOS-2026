"""Controlled policy evolution derived from completed General trajectories."""

from __future__ import annotations

from contracts import stable_checksum
from contracts.evolution import (
    EvolutionPolicyVersion,
    EvolutionProposal,
    EvolutionProposalStatus,
    PolicyMutation,
    Trajectory,
    TrajectoryEvaluation,
)

from .store import EvolutionStore, InMemoryEvolutionStore


class EvolutionService:
    def __init__(self, *, store: EvolutionStore | None = None, proposal_threshold: int = 3) -> None:
        if proposal_threshold < 1:
            raise ValueError("proposal_threshold must be positive")
        self.store = store or InMemoryEvolutionStore()
        self.proposal_threshold = proposal_threshold

    def evaluate(self, trajectory: Trajectory) -> TrajectoryEvaluation:
        completed = str(trajectory.outcome.get("status", "")).lower() in {"completed", "success"}
        success = 1.0 if completed or trajectory.outcome.get("success") is True else 0.0
        step_count = max(len(trajectory.steps), 1)
        failed_steps = sum(bool(step.feedback.get("error")) for step in trajectory.steps)
        efficiency = max(0.0, 1.0 - failed_steps / step_count)
        quality = min(1.0, float(trajectory.outcome.get("quality", success)))
        return TrajectoryEvaluation(
            trajectoryId=trajectory.trajectory_id,
            successScore=success,
            efficiencyScore=efficiency,
            noveltyScore=0.0,
            qualityScore=quality,
            evidence={"stepCount": len(trajectory.steps), "failedSteps": failed_steps},
        )

    def propose(
        self,
        trajectories: list[Trajectory],
        mutation: PolicyMutation,
    ) -> EvolutionProposal | None:
        ordered = sorted(trajectories, key=lambda item: item.trajectory_id)
        if len(ordered) < self.proposal_threshold:
            return None
        evaluations = [self.evaluate(item) for item in ordered]
        checksum = stable_checksum(evaluations)
        active = self.store.active()
        proposal_id = f"evolution:{stable_checksum([active.version, [item.trajectory_id for item in ordered], mutation])[:16]}"
        return EvolutionProposal(
            proposalId=proposal_id,
            baseVersion=active.version,
            trajectoryIds=[item.trajectory_id for item in ordered],
            mutations=[mutation],
            evaluationChecksum=checksum,
            status=EvolutionProposalStatus.PENDING_REVIEW,
        )

    def approve(self, proposal: EvolutionProposal, *, approved_by: str) -> EvolutionPolicyVersion:
        if proposal.status is not EvolutionProposalStatus.PENDING_REVIEW:
            raise ValueError("only a validated pending proposal can be approved")
        active = self.store.active()
        if proposal.base_version != active.version:
            raise ValueError("proposal base version is stale")
        policy = dict(active.policy)
        for mutation in proposal.mutations:
            policy[f"{mutation.mutation_type}:{mutation.target}"] = mutation.value
        return self.store.create(
            EvolutionPolicyVersion(
                version=active.version + 1,
                baseVersion=active.version,
                proposalIds=[proposal.proposal_id],
                policy=policy,
                approvedBy=approved_by,
            ),
            expected_active=active.version,
        )

    def rollback(self, target_version: int, *, approved_by: str) -> EvolutionPolicyVersion:
        target = self.store.get(target_version)
        active = self.store.active()
        return self.store.create(
            EvolutionPolicyVersion(
                version=active.version + 1,
                baseVersion=active.version,
                proposalIds=[f"rollback:{target_version}"],
                policy=dict(target.policy),
                approvedBy=approved_by,
            ),
            expected_active=active.version,
        )


__all__ = ["EvolutionService"]
