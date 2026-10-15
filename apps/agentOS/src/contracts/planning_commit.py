"""S02-01 accepted planning facts, without execution or graph activation authority.

Requests are assembled by trusted application code, not exposed as model output.
Pydantic validation is a shape check; only the injected authority can attest sources.
"""
from enum import Enum
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.identity import MissionId, SemanticTaskKey
from contracts.planning import TaskPlan, TaskPlanPatch
from contracts.graph_revision import GraphRevisionProposal, PlanningSourceProvenance


Fingerprint = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Reference = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
ProposalType = Literal[
    "candidate_tasks", "plan_revision", "method", "htn_expansion", "horizon",
    "initial_plan", "plan_expansion", "graph_revision",
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
    source_kind: Literal["runtime", "initial"] = Field(default="runtime", alias="sourceKind")
    observation_id: Reference | None = Field(alias="observationId")
    observation_fingerprint: Fingerprint | None = Field(alias="observationFingerprint")
    plan_version: int | None = Field(strict=True, ge=1, alias="planVersion")
    graph_version: int | None = Field(strict=True, ge=1, alias="graphVersion")
    strategy_fingerprint: Fingerprint = Field(alias="strategyFingerprint")

    @model_validator(mode="after")
    def coherent_phase(self):
        empty = (self.observation_id, self.observation_fingerprint, self.plan_version, self.graph_version)
        if self.source_kind == "initial":
            if any(v is not None for v in empty):
                raise ValueError("initial sources have no formal plan, graph or observation")
        elif any(v is None for v in empty):
            raise ValueError("runtime sources require complete formal planning references")
        return self


class PlanningCommitRequest(PlanningCommitContract):
    proposal_id: Reference = Field(alias="proposalId")
    proposal_type: ProposalType = Field(alias="proposalType")
    proposal_fingerprint: Fingerprint = Field(alias="proposalFingerprint")
    sources: FrozenPlanningSources
    requested_scope: tuple[SemanticTaskKey, ...] = Field(
        min_length=1, max_length=256, alias="requestedScope")
    idempotency_key: Reference = Field(alias="idempotencyKey")
    expected_commitment_revision: int | None = Field(default=None, strict=True, ge=0,
                                                    alias="expectedCommitmentRevision")

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
    STALE_COMMITMENT = "STALE_COMMITMENT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


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
    expected_commitment_revision: int | None = Field(default=None, strict=True, ge=0,
                                                    alias="expectedCommitmentRevision")
    proposal_payload: TaskPlan | TaskPlanPatch | GraphRevisionProposal | None = Field(default=None, alias="proposalPayload")
    source_provenance: PlanningSourceProvenance | None = Field(default=None, alias="sourceProvenance")
    materialization_status: Literal["COMMITTED_NOT_MATERIALIZED"] = Field(
        default="COMMITTED_NOT_MATERIALIZED", alias="materializationStatus")

    @model_validator(mode="after")
    def consistent_sources(self):
        if (self.mission_id != self.sources.mission_id
                or self.source_revision != self.sources.mission_revision):
            raise ValueError("commitment source identity must be consistent")
        if len(set(self.requested_scope)) != len(self.requested_scope):
            raise ValueError("commitment scope must be unique")
        if self.expected_commitment_revision is not None and self.expected_commitment_revision != self.commitment_revision - 1:
            raise ValueError("commitment base must match its predecessor revision")
        if self.proposal_payload is not None:
            payload = self.proposal_payload.model_dump(mode="json", by_alias=True)
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            if digest != self.proposal_fingerprint or self.proposal_payload.mission_id != self.mission_id:
                raise ValueError("commitment proposal content is inconsistent")
        return self
