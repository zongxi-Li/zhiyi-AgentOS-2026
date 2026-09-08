from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model import CapabilityBindingRejection, CapabilityRequirement, TopologyEdge


class TopologyConflictCode(StrEnum):
    DEPENDENCY_CYCLE = "dependency_cycle"
    CAPABILITY_BINDING_CONFLICT = "capability_binding_conflict"
    INVALID_CONTROL_POLICY = "invalid_control_policy"
    TERMINAL_CONNECTION_CONFLICT = "terminal_connection_conflict"
    UNKNOWN_TASK_REFERENCE = "unknown_task_reference"
    SELF_DEPENDENCY = "self_dependency"
    CAPABILITY_BINDING_SEARCH_EXHAUSTED = "capability_binding_search_exhausted"


@dataclass(frozen=True)
class TopologyConflict:
    code: TopologyConflictCode
    phase: str
    cycle_nodes: tuple[str, ...] = ()
    cycle_edges: tuple[TopologyEdge, ...] = ()
    capability_requirements: tuple[CapabilityRequirement, ...] = ()
    repairable_edges: tuple[TopologyEdge, ...] = ()
    rebindable_edges: tuple[TopologyEdge, ...] = ()
    regenerable_edges: tuple[TopologyEdge, ...] = ()
    fixed_edges: tuple[TopologyEdge, ...] = ()
    repair_attempts: int = 0
    binding_rejections: tuple[CapabilityBindingRejection, ...] = ()
    search_states_explored: int = 0


class TopologyCompileError(ValueError):
    def __init__(self, conflict: TopologyConflict, message: str) -> None:
        super().__init__(message)
        self.conflict = conflict
        self.audit: dict | None = None


def is_model_repair_eligible(conflict: TopologyConflict) -> bool:
    return (
        conflict.code in {
            TopologyConflictCode.DEPENDENCY_CYCLE,
            TopologyConflictCode.CAPABILITY_BINDING_CONFLICT,
        }
        and bool(conflict.repairable_edges)
    )
