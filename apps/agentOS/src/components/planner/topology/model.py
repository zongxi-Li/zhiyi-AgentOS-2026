from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from contracts.planning import TaskPlanRelation, VerificationLoopPolicy


class EdgeOrigin(StrEnum):
    MODEL = "model"
    CAPABILITY_CATALOG = "capability_catalog"
    TERMINAL_CONNECTOR = "terminal_connector"
    USER_DECLARED = "user_declared"
    TEMPLATE_DECLARED = "template_declared"
    FALLBACK_GENERATED = "fallback_generated"
    PLAN_PATCH = "plan_patch"


class EdgeMutationPolicy(StrEnum):
    FIXED = "fixed"
    REPAIRABLE = "repairable"
    REBINDABLE = "rebindable"
    REGENERABLE = "regenerable"


@dataclass(frozen=True)
class TopologyEdge:
    source_key: str
    target_key: str
    relation_type: str
    origin: EdgeOrigin
    mutation_policy: EdgeMutationPolicy
    reason: str | None = None
    requirement_id: str | None = None
    original_relation_index: int | None = None

    def to_relation(self) -> TaskPlanRelation:
        return TaskPlanRelation(
            sourceKey=self.source_key, targetKey=self.target_key,
            relationType=self.relation_type,
        )


@dataclass(frozen=True)
class CapabilityRequirement:
    requirement_id: str
    producer_capability: str
    consumer_capability: str
    consumer_task_key: str
    candidate_producer_keys: tuple[str, ...]


@dataclass(frozen=True, order=True)
class CapabilityBindingScore:
    explicit_dependency_rank: int
    preceding_rank: int
    ordinal_distance: int
    producer_task_key: str


@dataclass(frozen=True)
class CapabilityBindingCandidate:
    requirement_id: str
    producer_task_key: str
    consumer_task_key: str
    score: CapabilityBindingScore


@dataclass(frozen=True)
class CapabilityBindingRejection:
    requirement_id: str
    producer_task_key: str
    consumer_task_key: str
    reason: str
    path: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityBindingAudit:
    ordered_candidates: tuple[tuple[str, tuple[CapabilityBindingCandidate, ...]], ...]
    selected_bindings: tuple[TopologyEdge, ...]
    rejected_candidates: tuple[CapabilityBindingRejection, ...]
    search_states_explored: int
    backtrack_count: int


@dataclass(frozen=True)
class CandidateTopology:
    task_keys: tuple[str, ...]
    edges: tuple[TopologyEdge, ...]
    capability_requirements: tuple[CapabilityRequirement, ...]
    control_policies: tuple[VerificationLoopPolicy, ...]
    selected_bindings: tuple[TopologyEdge, ...] = ()


@dataclass(frozen=True)
class TopologyCompilationAudit:
    original_model_relations: tuple[TaskPlanRelation, ...]
    normalized_model_edges: tuple[TopologyEdge, ...]
    capability_requirements: tuple[CapabilityRequirement, ...]
    selected_concrete_bindings: tuple[TopologyEdge, ...]
    terminal_edges: tuple[TopologyEdge, ...]
    binding_audit: CapabilityBindingAudit
    normalized_loop_relations: tuple[TaskPlanRelation, ...] = ()


@dataclass(frozen=True)
class TopologyCompileResult:
    candidate: CandidateTopology
    task_plan_relations: tuple[TaskPlanRelation, ...]
    control_policies: tuple[VerificationLoopPolicy, ...]
    audit: TopologyCompilationAudit
