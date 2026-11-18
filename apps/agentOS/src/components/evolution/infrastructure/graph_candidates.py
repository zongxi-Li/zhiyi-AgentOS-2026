"""Evidence-based suggestions; never compiles or authorizes an execution graph."""
from collections import Counter

from contracts import stable_checksum
from contracts.evolution import GraphEvolutionProposal, Trajectory, TrajectoryEvaluation
from components.evolution.domain.graph import require_distinct_runs


class RegisteredValidatorCandidateGenerator:
    """Suggest one configured validator at a step that failed across distinct Runs."""

    def __init__(self, *, validators: dict[str, str], min_failures: int = 2) -> None:
        if isinstance(min_failures, bool) or not isinstance(min_failures, int) or min_failures < 1:
            raise ValueError("min_failures must be a positive integer")
        if not validators or any(not key.strip() or not value.strip() for key, value in validators.items()):
            raise ValueError("explicit non-empty validator mappings are required")
        self.validators = dict(validators)
        self.min_failures = min_failures

    def generate(self, trajectories: list[Trajectory],
                 evaluations: list[TrajectoryEvaluation]) -> GraphEvolutionProposal:
        if not trajectories or len({t.trajectory_id for t in trajectories}) != len(trajectories):
            raise ValueError("distinct trajectory evidence is required")
        ordered = sorted(trajectories, key=lambda t: t.trajectory_id)
        require_distinct_runs(ordered, threshold=self.min_failures)
        first = ordered[0]
        graph_id, version = first.task.get("graphId"), first.graph_version
        if (not isinstance(graph_id, str) or not graph_id.strip() or version is None
                or any(t.task.get("graphId") != graph_id or t.graph_version != version for t in ordered)):
            raise ValueError("failure evidence must describe the same graph version")
        counts = Counter()
        for trajectory in ordered:
            failed = {(s.step_id, s.action_type) for s in trajectory.steps
                      if s.feedback.get("error") and s.action_type in self.validators}
            counts.update(failed)
        candidates = sorted((key for key, count in counts.items() if count >= self.min_failures),
                            key=lambda key: (-counts[key], key))
        if not candidates:
            raise ValueError("no repeated failure supports a registered validator candidate")
        step_id, capability = candidates[0]
        mutations = [{"mutationType": "registered_validator_insertion", "target": step_id,
                      "value": self.validators[capability]}]
        ids = [t.trajectory_id for t in ordered]
        fingerprint = stable_checksum([graph_id, version, ids, mutations,
            sorted(evaluations, key=lambda e: e.trajectory_id)])
        return GraphEvolutionProposal(proposalId="graph-evolution:" + fingerprint[:24],
            graphId=graph_id, baseGraphVersion=version, mutations=mutations,
            evidenceTrajectoryIds=ids,
            rationale=f"Step {step_id} failed in {counts[(step_id, capability)]} distinct trajectories; evaluate a registered validator offline.")
