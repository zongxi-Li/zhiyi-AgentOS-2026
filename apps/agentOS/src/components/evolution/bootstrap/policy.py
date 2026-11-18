"""Construct a process-local policy service for callers without persistence wiring."""
from components.evolution.application.policy import EvolutionService
from components.evolution.infrastructure.memory import InMemoryEvolutionStore


def build_memory_evolution_service(*, proposal_threshold: int = 3) -> EvolutionService:
    return EvolutionService(store=InMemoryEvolutionStore(), proposal_threshold=proposal_threshold)
