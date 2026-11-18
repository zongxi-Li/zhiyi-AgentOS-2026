"""Restricted offline graph mutations and quality/cost release gates."""
from contracts import stable_checksum
from contracts.evolution import (
    EvolutionAction, GraphEvolutionEvaluation, GraphEvolutionProposal,
    PolicyMutation, Trajectory, TrajectoryEvaluation,
)


def require_distinct_runs(trajectories: list[Trajectory], *, threshold: int) -> None:
    # Legacy offline DTOs may use trajectoryId as their only source identity.
    # Real Run projections always carry runId; multiple snapshots count once.
    sources = [t.task.get("runId", t.trajectory_id) for t in trajectories]
    if (any(not isinstance(key, str) or not key.strip() for key in sources)
            or len(set(sources)) < threshold or len(set(sources)) != len(sources)):
        raise ValueError("graph proposal requires distinct Run evidence")


def require_graph_evidence(proposal: GraphEvolutionProposal, trajectories: list[Trajectory],
                           evaluations: list[TrajectoryEvaluation], *, threshold: int) -> None:
    ids = proposal.evidence_trajectory_ids
    require_distinct_runs(trajectories, threshold=threshold)
    if (len(ids) < threshold or len(ids) != len(set(ids))
            or [t.trajectory_id for t in trajectories] != ids):
        raise ValueError("graph proposal requires distinct persisted evidence")
    if [e.trajectory_id for e in evaluations] != ids:
        raise ValueError("graph evaluation evidence identity is invalid")
    if (not proposal.graph_id.strip() or proposal.base_graph_version < 1
            or any(t.task.get("graphId") != proposal.graph_id or t.graph_version != proposal.base_graph_version
                   for t in trajectories)):
        raise ValueError("graph proposal identity or evidence version is invalid")
    if proposal.action is not EvolutionAction.PATCH or not proposal.mutations:
        raise ValueError("only non-empty restricted graph patches are supported")
    targets = set()
    for raw in proposal.mutations:
        mutation = PolicyMutation.model_validate(raw)
        if (mutation.mutation_type != "registered_validator_insertion"
                or not isinstance(mutation.value, str) or not mutation.value.strip()
                or not mutation.target.strip() or mutation.target in targets):
            raise ValueError("only one registered validator insertion per target is supported")
        if any(mutation.target not in {s.step_id for s in t.steps} for t in trajectories):
            raise ValueError("graph target is not bound to trajectory steps")
        targets.add(mutation.target)


def require_graph_evaluation(proposal: GraphEvolutionProposal, evaluation: GraphEvolutionEvaluation,
                             *, max_cost_ratio: float, source_run_ids: set[str]) -> GraphEvolutionEvaluation:
    evaluation = GraphEvolutionEvaluation.model_validate(evaluation.model_dump())
    if evaluation.proposal_id != proposal.proposal_id or evaluation.proposal_checksum != stable_checksum(proposal):
        raise ValueError("offline evaluation belongs to another proposal")
    if set(evaluation.sample_ids) & (set(proposal.evidence_trajectory_ids) | source_run_ids):
        raise ValueError("offline evaluation must use held-out samples")
    if evaluation.candidate_quality < evaluation.baseline_quality:
        raise ValueError("offline candidate quality regressed")
    if evaluation.candidate_cost > evaluation.baseline_cost * max_cost_ratio:
        raise ValueError("offline candidate cost exceeds release policy")
    return evaluation
