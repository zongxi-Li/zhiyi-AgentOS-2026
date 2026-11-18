"""Evidence -> restricted candidate -> paired evaluation -> authorized publication."""
from math import isfinite

from contracts import stable_checksum
from contracts.evolution import (
    GraphEvolutionEvaluation, GraphEvolutionProposal, GraphEvolutionPublicationReceipt,
    Trajectory, TrajectoryEvaluation,
)
from components.evolution.domain.graph import require_distinct_runs, require_graph_evaluation, require_graph_evidence
from components.evolution.domain.policy import require_reviewer, unique_trajectories
from components.evolution.ports.graph import (
    GraphCandidateGenerator, GraphOfflineEvaluator, GraphProposalValidator, GraphVersionPublisher,
)
from components.evolution.ports.store import EvolutionStore


class GraphEvolutionService:
    def __init__(self, *, store: EvolutionStore | None = None,
                 generator: GraphCandidateGenerator | None = None,
                 validator: GraphProposalValidator | None = None,
                 evaluator: GraphOfflineEvaluator | None = None,
                 publisher: GraphVersionPublisher | None = None,
                 proposal_threshold: int = 3, max_cost_ratio: float = 1.0) -> None:
        if isinstance(proposal_threshold, bool) or not isinstance(proposal_threshold, int) or proposal_threshold < 1:
            raise ValueError("proposal_threshold must be a positive integer")
        if isinstance(max_cost_ratio, bool) or not isfinite(max_cost_ratio) or max_cost_ratio <= 0:
            raise ValueError("max_cost_ratio must be finite and positive")
        self.store, self.generator, self.validator = store, generator, validator
        self.evaluator, self.publisher = evaluator, publisher
        self.proposal_threshold, self.max_cost_ratio = proposal_threshold, max_cost_ratio

    @staticmethod
    def _configured(value, capability):
        if value is None:
            raise NotImplementedError(f"graph evolution {capability} is not configured")
        return value

    def propose_mutation(self, trajectory: Trajectory, evaluation: TrajectoryEvaluation) -> GraphEvolutionProposal:
        """Legacy entry; the configured distinct-evidence threshold still applies."""
        return self.propose([trajectory], [evaluation])

    def propose(self, trajectories: list[Trajectory],
                evaluations: list[TrajectoryEvaluation]) -> GraphEvolutionProposal:
        generator = self._configured(self.generator, "candidate generator")
        store = self._configured(self.store, "evidence store")
        self._configured(self.validator, "proposal validator")
        ordered = unique_trajectories([t.model_copy(deep=True) for t in trajectories])
        require_distinct_runs(ordered, threshold=self.proposal_threshold)
        by_id = {}
        for evaluation in evaluations:
            evaluation = evaluation.model_copy(deep=True)
            if evaluation.trajectory_id in by_id and by_id[evaluation.trajectory_id] != evaluation:
                raise ValueError("conflicting trajectory evaluation")
            by_id[evaluation.trajectory_id] = evaluation
        if set(by_id) != {t.trajectory_id for t in ordered}:
            raise ValueError("trajectory evaluation identities do not match evidence")
        for trajectory in ordered:
            store.save_trajectory(trajectory)
            store.save_evaluation(by_id[trajectory.trajectory_id])
        proposal = generator.generate([t.model_copy(deep=True) for t in ordered],
            [by_id[t.trajectory_id].model_copy(deep=True) for t in ordered])
        if proposal.evidence_trajectory_ids != [t.trajectory_id for t in ordered]:
            raise ValueError("candidate generator changed evidence identities")
        self.validate_proposal(proposal)
        return proposal.model_copy(deep=True)

    def validate_proposal(self, proposal: GraphEvolutionProposal) -> None:
        proposal = proposal.model_copy(deep=True)
        store = self._configured(self.store, "evidence store")
        validator = self._configured(self.validator, "proposal validator")
        try:
            trajectories = [store.get_trajectory(key) for key in proposal.evidence_trajectory_ids]
            evaluations = [store.get_evaluation(key) for key in proposal.evidence_trajectory_ids]
        except KeyError as exc:
            raise ValueError("graph evidence is not persisted") from exc
        require_graph_evidence(proposal, trajectories, evaluations, threshold=self.proposal_threshold)
        validator.validate(proposal.model_copy(deep=True), trajectories=trajectories, evaluations=evaluations)

    def evaluate_proposal(self, proposal: GraphEvolutionProposal) -> GraphEvolutionEvaluation:
        proposal = proposal.model_copy(deep=True)
        evaluator = self._configured(self.evaluator, "offline evaluator")
        self.validate_proposal(proposal)
        evaluation = evaluator.evaluate(proposal.model_copy(deep=True))
        source_run_ids = {
            run_id for key in proposal.evidence_trajectory_ids
            if isinstance(run_id := self.store.get_trajectory(key).task.get("runId"), str)
        }
        return require_graph_evaluation(proposal, evaluation, max_cost_ratio=self.max_cost_ratio,
                                         source_run_ids=source_run_ids)

    def apply_approved_proposal(self, proposal: GraphEvolutionProposal, *, approved_by: str,
                                evaluation: GraphEvolutionEvaluation | None = None) -> GraphEvolutionPublicationReceipt:
        proposal = proposal.model_copy(deep=True)
        evaluation = evaluation.model_copy(deep=True) if evaluation is not None else None
        reviewer = require_reviewer(approved_by)
        publisher = self._configured(self.publisher, "formal graph version publisher")
        # Caller-supplied scores never substitute for the trusted evaluator.
        trusted = self.evaluate_proposal(proposal)
        if evaluation is not None and evaluation != trusted:
            raise ValueError("supplied evaluation differs from the trusted offline evaluation")
        receipt = publisher.publish(proposal.model_copy(deep=True),
            evaluation=trusted.model_copy(deep=True), approved_by=reviewer)
        receipt = GraphEvolutionPublicationReceipt.model_validate(receipt.model_dump())
        if (receipt.proposal_id != proposal.proposal_id or receipt.proposal_checksum != stable_checksum(proposal)
                or receipt.graph_id != proposal.graph_id or receipt.graph_version != proposal.base_graph_version + 1
                or receipt.approved_by != reviewer):
            raise ValueError("graph publication receipt identity is inconsistent")
        return receipt
