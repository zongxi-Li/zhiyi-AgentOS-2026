"""Minimal Mission semantics. References are recorded, never implicitly verified."""

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, StrictStr, field_validator, model_validator

from contracts.workflow import CoreModel, utc_now


class SemanticModel(CoreModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SemanticConstraint(SemanticModel):
    constraint_id: StrictStr = Field(alias="constraintId", min_length=1)
    text: StrictStr = Field(min_length=1)
    source_refs: list[StrictStr] = Field(default_factory=list, alias="sourceRefs")

    @field_validator("constraint_id", "text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("constraint fields must not be blank")
        return value


class MissionSemanticRequest(SemanticModel):
    mission_id: StrictStr = Field(alias="missionId", min_length=1)
    operation_id: StrictStr = Field(alias="operationId", min_length=1)
    expected_mission_revision: int = Field(alias="expectedMissionRevision", ge=0, strict=True)
    objective: StrictStr = Field(min_length=1)
    constraints: list[SemanticConstraint]
    source_refs: list[StrictStr] = Field(default_factory=list, alias="sourceRefs")

    @field_validator("objective")
    @classmethod
    def objective_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("objective must not be blank")
        return value

    @model_validator(mode="after")
    def unique_constraints(self):
        ids = [item.constraint_id for item in self.constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate constraintId")
        refs = self.source_refs + [ref for item in self.constraints for ref in item.source_refs]
        if any(not ref.strip() for ref in refs):
            raise ValueError("source reference must not be blank")
        return self


class SemanticPrincipal(SemanticModel):
    """Supplied by the trusted authentication boundary, not by request JSON."""
    actor_id: StrictStr = Field(alias="actorId", min_length=1)
    tenant_id: StrictStr = Field(alias="tenantId", min_length=1)


class MissionSemanticOperation(MissionSemanticRequest):
    actor_id: StrictStr = Field(alias="actorId", min_length=1)
    tenant_id: StrictStr = Field(alias="tenantId", min_length=1)


class MissionSemanticAggregate(SemanticModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    mission_id: str = Field(alias="missionId")
    mission_revision: int = Field(alias="missionRevision", ge=1)
    objective: str
    constraints: list[SemanticConstraint]
    source_refs: list[str] = Field(alias="sourceRefs")
    last_commit_id: str = Field(alias="lastCommitId")
    updated_at: datetime = Field(alias="updatedAt")


class SemanticCommit(SemanticModel):
    commit_id: str = Field(alias="commitId")
    mission_id: str = Field(alias="missionId")
    operation_id: str = Field(alias="operationId")
    previous_revision: int = Field(alias="previousRevision", ge=0)
    mission_revision: int = Field(alias="missionRevision", ge=1)
    actor_id: str = Field(alias="actorId")
    tenant_id: str = Field(alias="tenantId")
    request_fingerprint: str = Field(alias="requestFingerprint")
    state: MissionSemanticAggregate
    created_at: datetime = Field(alias="createdAt")


class SemanticOperationResult(SemanticModel):
    status: Literal["COMMITTED", "NO_OP", "REVISION_CONFLICT", "OPERATION_CONFLICT"]
    mission_id: str = Field(alias="missionId")
    operation_id: str = Field(alias="operationId")
    mission_revision: int = Field(alias="missionRevision", ge=0)
    expected_mission_revision: int = Field(alias="expectedMissionRevision", ge=0)
    commit_id: str | None = Field(default=None, alias="commitId")


class SemanticOperationReceipt(SemanticModel):
    fingerprint_version: Literal[1] = Field(default=1, alias="fingerprintVersion")
    request_fingerprint: str = Field(alias="requestFingerprint")
    actor_id: str = Field(alias="actorId")
    tenant_id: str = Field(alias="tenantId")
    result: SemanticOperationResult
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class EffectiveMissionSnapshot(SemanticModel):
    mission_id: str = Field(alias="missionId")
    status: Literal["MISSION_NOT_FOUND", "UNINITIALIZED", "INITIALIZED"]
    mission_revision: int = Field(alias="missionRevision", ge=0)
    state: MissionSemanticAggregate | None = None
    source_status: Literal["NOT_APPLICABLE", "UNVERIFIED"] = Field(alias="sourceStatus")
