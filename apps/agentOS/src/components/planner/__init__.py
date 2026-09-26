"""规划部件的公共入口。

The lowering kernel is intentionally available without importing the planning
engine, provider adapters, or cognitive router.  The remaining public symbols
are loaded lazily for callers that explicitly request them.
"""

from importlib import import_module

from .acg_lowerer import ACGLoweringInput, ACGLoweringStep, ACGLowerer

_LAZY_EXPORTS = {
    "ACGPlanningError": (".service", "ACGPlanningError"),
    "PlannerService": (".service", "PlannerService"),
    "SemanticPlanner": (".semantic_planner", "SemanticPlanner"),
    "SemanticPlanningError": (".semantic_planner", "SemanticPlanningError"),
    "TaskDecomposer": (".task_decomposer", "TaskDecomposer"),
    "TaskDecompositionError": (".task_decomposer", "TaskDecompositionError"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value

__all__ = [
    "ACGLoweringInput",
    "ACGLoweringStep",
    "ACGLowerer",
    "ACGPlanningError",
    "PlannerService",
    "SemanticPlanner",
    "SemanticPlanningError",
    "TaskDecomposer",
    "TaskDecompositionError",
]
