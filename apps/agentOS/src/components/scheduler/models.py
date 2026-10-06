"""Typed scheduler decisions without DAG state."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from contracts.resource import ExecutionBinding, ResourceLease


class FilterReason(str, Enum):
    DISABLED = "DISABLED"
    UNHEALTHY = "UNHEALTHY"
    NODE_UNHEALTHY = "NODE_UNHEALTHY"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    RUNTIME_KIND_MISMATCH = "RUNTIME_KIND_MISMATCH"
    PLACEMENT_MISMATCH = "PLACEMENT_MISMATCH"
    TRUST_INSUFFICIENT = "TRUST_INSUFFICIENT"
    NOT_ALLOWED = "NOT_ALLOWED"
    EXCLUDED = "EXCLUDED"
    DOMAIN_MISMATCH = "DOMAIN_MISMATCH"
    DATA_ZONE_MISMATCH = "DATA_ZONE_MISMATCH"
    OWNER_SCOPE_MISMATCH = "OWNER_SCOPE_MISMATCH"
    LABEL_MISMATCH = "LABEL_MISMATCH"
    NO_CAPACITY = "NO_CAPACITY"
    COST_EXCEEDED = "COST_EXCEEDED"
    LATENCY_EXCEEDED = "LATENCY_EXCEEDED"
    REMOTE_EXECUTION_DISABLED = "REMOTE_EXECUTION_DISABLED"
    MODEL_ENDPOINT_UNAVAILABLE = "MODEL_ENDPOINT_UNAVAILABLE"


#: 调度结果中代表永久性配置缺口的原因；执行循环应立即失败而不是排队等待。
FATAL_SCHEDULING_REASONS = frozenset({
    "NO_ELIGIBLE_RESOURCE",
    "NO_MODEL_ENDPOINT",
})


class CandidateDecision(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    resource_id: str = Field(alias="resourceId")
    accepted: bool
    reasons: list[FilterReason] = Field(default_factory=list)
    score: float | None = None


class ReadyNodeSchedulingResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    status: str
    binding: ExecutionBinding | None = None
    lease: ResourceLease | None = None
    candidates: list[CandidateDecision] = Field(default_factory=list)
    reason: str | None = None


class SchedulerUnavailable(RuntimeError):
    """Coordination state cannot safely allocate a lease."""


class SchedulerNoEligibleResource(RuntimeError):
    """The frozen binding policy has no executable resource in this Runtime."""


class SchedulerAllocationTimeout(TimeoutError):
    """A READY node could not obtain capacity within its bounded queue window."""


__all__ = [
    "FATAL_SCHEDULING_REASONS",
    "CandidateDecision",
    "FilterReason",
    "ReadyNodeSchedulingResult",
    "SchedulerAllocationTimeout",
    "SchedulerNoEligibleResource",
    "SchedulerUnavailable",
]
