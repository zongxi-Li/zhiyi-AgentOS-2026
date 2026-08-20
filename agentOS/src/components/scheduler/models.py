"""Typed scheduler decisions without DAG state."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from contracts.resource import ExecutionBinding, ResourceLease


class FilterReason(str, Enum):
    DISABLED = "DISABLED"
    UNHEALTHY = "UNHEALTHY"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    DOMAIN_MISMATCH = "DOMAIN_MISMATCH"
    RESOURCE_TYPE_MISMATCH = "RESOURCE_TYPE_MISMATCH"
    NOT_ALLOWED = "NOT_ALLOWED"
    EXCLUDED = "EXCLUDED"
    DATA_ZONE_MISMATCH = "DATA_ZONE_MISMATCH"
    OWNER_SCOPE_MISMATCH = "OWNER_SCOPE_MISMATCH"
    NO_CAPACITY = "NO_CAPACITY"
    COST_EXCEEDED = "COST_EXCEEDED"


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


__all__ = ["CandidateDecision", "FilterReason", "ReadyNodeSchedulingResult", "SchedulerUnavailable"]
