"""Legacy constructor and Run adapter; new callers use policy.py with an injected store.

This compatibility boundary may compose defaults and adapt Run records. Neither
responsibility is part of the application policy service.
"""
from components.evolution.application.policy import EvolutionService as PolicyService
from components.evolution.ports.store import EvolutionStore


class EvolutionService(PolicyService):
    def __init__(self, *, store: EvolutionStore | None = None, proposal_threshold: int = 3):
        if store is None:
            from components.evolution.bootstrap.policy import build_memory_evolution_service
            store = build_memory_evolution_service(proposal_threshold=proposal_threshold).store
        super().__init__(store=store, proposal_threshold=proposal_threshold)

    def project_run(self, run, *, provenance_events):
        from components.evolution.integration.trajectory import project_run
        return self.store.save_trajectory(project_run(run, provenance_events=provenance_events))

    def propose_from_run(self, run, *, provenance_events):
        from components.evolution.integration.runs import propose_from_run
        return propose_from_run(self, run, provenance_events=provenance_events)


__all__ = ["EvolutionService"]
