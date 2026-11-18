"""Offline algorithms and graph version authority are explicit dependencies."""
from typing import Protocol

from contracts.evolution import (
    GraphEvolutionEvaluation, GraphEvolutionProposal, GraphEvolutionPublicationReceipt,
    Trajectory, TrajectoryEvaluation,
)


class GraphCandidateGenerator(Protocol):
    def generate(self, trajectories: list[Trajectory],
                 evaluations: list[TrajectoryEvaluation]) -> GraphEvolutionProposal: ...


class GraphProposalValidator(Protocol):
    def validate(self, proposal: GraphEvolutionProposal, *, trajectories: list[Trajectory],
                 evaluations: list[TrajectoryEvaluation]) -> None:
        """Prove registration, topology, capabilities and budget against a trusted graph snapshot."""
        ...


class GraphOfflineEvaluator(Protocol):
    def evaluate(self, proposal: GraphEvolutionProposal) -> GraphEvolutionEvaluation:
        """Run paired held-out cases; return reproducible baseline/candidate aggregates."""
        ...


class GraphVersionPublisher(Protocol):
    def publish(self, proposal: GraphEvolutionProposal, *, evaluation: GraphEvolutionEvaluation,
                approved_by: str) -> GraphEvolutionPublicationReceipt:
        """Authorize reviewer, check graph CAS, atomically persist/replay publication.

        Use the formal TaskPlan/compiler/version authority, never patch a live
        RuntimeGraph. The proposal checksum is an idempotency identity, not permission.
        """
        ...
