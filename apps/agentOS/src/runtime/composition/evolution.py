"""Composition of the optional process-local evolution policy dependency."""
from components.evolution.bootstrap.policy import build_memory_evolution_service


def build_default_evolution_service():
    return build_memory_evolution_service()
