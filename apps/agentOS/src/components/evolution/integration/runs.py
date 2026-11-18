"""Compatibility policy example for a completed Run; not an optimization algorithm."""
from contracts.evolution import PolicyMutation
from components.evolution.integration.trajectory import project_run
from components.evolution.policy import EvolutionService


def propose_from_run(service: EvolutionService, run, *, provenance_events):
    trajectory = project_run(run, provenance_events=provenance_events)
    evaluation = service.evaluate(trajectory)
    proposal = service.propose([trajectory], PolicyMutation(
        mutationType="budget_adjustment", target="memory_token_budget", value=768))
    if proposal is None:
        raise ValueError("real-run trajectory threshold was not met")
    return trajectory, evaluation, proposal
