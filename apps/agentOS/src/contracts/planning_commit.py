"""S02-01 accepted planning facts, without execution or graph activation authority.

Requests are assembled by trusted application code, not exposed as model output.
Pydantic validation is a shape check; only the injected authority can attest sources.
"""
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.identity import MissionId, SemanticTaskKey


Fingerprint = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Reference = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
ProposalType = Literal[
    "candidate_tasks", "plan_revision", "method", "htn_expansion", "horizon",
    "initial_plan", "plan_expansion",
]


class PlanningCommitContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def nonblank_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("planning commitment text must not be blank")
        return value


class FrozenPlanningSources(PlanningCommitContract):
    """Runtime-provided evidence; never model-selected authority values."""
    mission_id: MissionId = Field(alias="missionId")
    mission_revision: int = Field(strict=True, ge=1, alias="missionRevision")
    observation_id: Reference = Field(alias="observationId")
    observation_fingerprint: Fingerprint = Field(alias="observationFingerprint")
    plan_version: int = Field(strict=True, ge=1, alias="planVersion")
    graph_version: int = Field(strict=True, ge=1, alias="graphVersion")
    strategy_fingerprint: Fingerprint = Field(alias="strategyFingerprint")


class PlanningCommitRequest(PlanningCommitContract):
    proposal_id: Reference = Field(alias="proposalId")
    proposal_type: ProposalType = Field(alias="proposalType")
    proposal_fingerprint: Fingerprint = Field(alias="proposalFingerprint")
    sources: FrozenPlanningSources
    requested_scope: tuple[SemanticTaskKey, ...] = Field(
        min_length=1, max_length=256, alias="requestedScope")
    idempotency_key: Reference = Field(alias="idempotencyKey")

    @field_validator("requested_scope")
    @classmethod
    def canonical_scope(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("requestedScope contains duplicate task keys")
        return tuple(sorted(value))


class PlanningCommitReceipt(PlanningCommitContract):
    commit_id: Reference | None = Field(default=None, alias="commitId")
    commitment_revision: int | None = Field(default=None, strict=True, ge=1,
                                            alias="commitmentRevision")
    status: Literal["ACCEPTED", "REJECTED", "IDEMPOTENT_REPLAY"]

    @model_validator(mode="after")
    def accepted_identity(self):
        if self.status == "REJECTED":
            if self.commit_id is not None or self.commitment_revision is not None:
                raise ValueError("rejection cannot identify an accepted commitment")
        elif self.commit_id is None or self.commitment_revision is None:
            raise ValueError("accepted and replay receipts require commitment identity")
        return self


class PlanningCommitRejectionCode(str, Enum):
    STALE_MISSION = "STALE_MISSION"
    STALE_PLAN = "STALE_PLAN"
    STALE_GRAPH = "STALE_GRAPH"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    STALE_STRATEGY = "STALE_STRATEGY"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    DEPENDENCY_NOT_CLOSED = "DEPENDENCY_NOT_CLOSED"
    AUTHORITY_DENIED = "AUTHORITY_DENIED"
    CONTROL_BARRIER_BLOCKED = "CONTROL_BARRIER_BLOCKED"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"


class PlanningCommitRejection(PlanningCommitReceipt):
    status: Literal["REJECTED"] = "REJECTED"
    code: PlanningCommitRejectionCode
    reason: Annotated[str, Field(strict=True, min_length=1, max_length=500)]


class PlanningCommitRecord(PlanningCommitContract):
    """Immutable acceptance record, not a TaskPlan, graph, Run or dispatch token."""
    commit_id: Reference = Field(alias="commitId")
    mission_id: MissionId = Field(alias="missionId")
    parent_commit_id: Reference | None = Field(default=None, alias="parentCommitId")
    commitment_revision: int = Field(strict=True, ge=1, alias="commitmentRevision")
    proposal_id: Reference = Field(alias="proposalId")
    proposal_type: ProposalType = Field(alias="proposalType")
    proposal_fingerprint: Fingerprint = Field(alias="proposalFingerprint")
    source_revision: int = Field(strict=True, ge=1, alias="sourceRevision")
    status: Literal["ACCEPTED"] = "ACCEPTED"
    sources: FrozenPlanningSources
    requested_scope: tuple[SemanticTaskKey, ...] = Field(
        min_length=1, max_length=256, alias="requestedScope")
    request_fingerprint: Fingerprint = Field(alias="requestFingerprint")

    @model_validator(mode="after")
    def consistent_sources(self):
        if (self.mission_id != self.sources.mission_id
                or self.source_revision != self.sources.mission_revision):
            raise ValueError("commitment source identity must be consistent")
        if len(set(self.requested_scope)) != len(self.requested_scope):
            raise ValueError("commitment scope must be unique")
        return self
