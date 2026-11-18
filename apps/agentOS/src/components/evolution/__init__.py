"""Stable evolution entries; importing the package does not load storage adapters."""
from importlib import import_module

_EXPORTS = {
    "EvolutionService": (".service", "EvolutionService"),
    "GraphEvolutionService": (".graph_service", "GraphEvolutionService"),
    "SkillEvolutionService": (".skill_service", "SkillEvolutionService"),
    "EvolutionStore": (".ports.store", "EvolutionStore"),
    "EvolutionVersionConflict": (".ports.store", "EvolutionVersionConflict"),
    "InMemoryEvolutionStore": (".infrastructure.memory", "InMemoryEvolutionStore"),
    "SQLiteEvolutionStore": (".infrastructure.sqlite", "SQLiteEvolutionStore"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(module, __name__), attribute)
