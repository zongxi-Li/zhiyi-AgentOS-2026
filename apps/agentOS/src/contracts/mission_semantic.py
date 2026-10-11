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


class MissionSemanticContent(SemanticModel):
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


class MissionSemanticEditRequest(MissionSemanticContent):
    operation_id: StrictStr = Field(alias="operationId", min_length=1, max_length=200)
    expected_mission_revision: int = Field(alias="expectedMissionRevision", ge=0, strict=True)

    @field_validator("operation_id")
    @classmethod
    def operation_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("operationId must not be blank")
        return value


class MissionSemanticRequest(MissionSemanticEditRequest):
    mission_id: StrictStr = Field(alias="missionId", min_length=1)


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


class FrozenSemanticConstraint(SemanticModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    constraint_id: StrictStr = Field(alias="constraintId", min_length=1)
    text: StrictStr = Field(min_length=1)
    source_refs: tuple[StrictStr, ...] = Field(default=(), alias="sourceRefs")


class MissionSemanticView(SemanticModel):
    """Current formal semantics only; never a legacy objective projection."""
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    mission_id: StrictStr = Field(alias="missionId", min_length=1)
    semantic_status: Literal["UNINITIALIZED", "INITIALIZED"] = Field(alias="semanticStatus")
    mission_revision: int = Field(alias="missionRevision", ge=0, strict=True)
    commit_id: StrictStr | None = Field(default=None, alias="commitId")
    objective: StrictStr | None = None
    constraints: tuple[FrozenSemanticConstraint, ...] = ()
    source_references: tuple[StrictStr, ...] = Field(default=(), alias="sourceReferences")
    source_status: Literal["NOT_APPLICABLE", "UNVERIFIED"] = Field(alias="sourceStatus")

    @model_validator(mode="after")
    def coherent_state(self):
        if self.semantic_status == "INITIALIZED":
            if self.mission_revision < 1 or not self.commit_id or not self.objective or not self.objective.strip():
                raise ValueError("initialized semantics require revision, commit and objective")
            if (self.source_references or any(c.source_refs for c in self.constraints)) and self.source_status != "UNVERIFIED":
                raise ValueError("semantic references are not verified evidence")
        elif (self.mission_revision != 0 or self.commit_id is not None or self.objective is not None
              or self.constraints or self.source_references or self.source_status != "NOT_APPLICABLE"):
            raise ValueError("uninitialized semantics cannot carry formal content")
        return self


class MissionIntentBasis(SemanticModel):
    """Immutable as-of Run input. It is not current Mission state or authorization."""
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    basis_schema_version: Literal[1] = Field(default=1, alias="basisSchemaVersion")
    mission_id: StrictStr = Field(alias="missionId", min_length=1)
    source_type: Literal["SEMANTIC", "LEGACY_INPUT", "LEGACY_TITLE"] = Field(alias="sourceType")
    source_revision: int = Field(alias="sourceRevision", ge=0, strict=True)
    commit_id: StrictStr | None = Field(default=None, alias="commitId")
    objective: StrictStr = Field(min_length=1)
    constraints: tuple[FrozenSemanticConstraint, ...] = ()
    source_references: tuple[StrictStr, ...] = Field(default=(), alias="sourceReferences")
    source_status: Literal["NOT_APPLICABLE", "UNVERIFIED"] = Field(alias="sourceStatus")
    fingerprint_version: Literal[1] = Field(default=1, alias="fingerprintVersion")
    fingerprint: StrictStr = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_basis(self):
        if not self.objective.strip():
            raise ValueError("basis objective must not be blank")
        if self.source_type == "SEMANTIC":
            if self.source_revision < 1 or not self.commit_id:
                raise ValueError("semantic basis requires a committed revision")
            if (self.source_references or any(c.source_refs for c in self.constraints)) and self.source_status != "UNVERIFIED":
                raise ValueError("semantic references are not verified evidence")
        elif self.source_revision != 0 or self.commit_id is not None:
            raise ValueError("legacy basis cannot claim a semantic revision")
        if len({c.constraint_id for c in self.constraints}) != len(self.constraints):
            raise ValueError("duplicate basis constraintId")
        if any(not ref.strip() for ref in self.source_references) or any(
            not c.text.strip() or not c.constraint_id.strip() or any(not ref.strip() for ref in c.source_refs)
            for c in self.constraints
        ):
            raise ValueError("blank basis constraint or reference")
        if self.fingerprint != intent_basis_fingerprint(self.model_dump(by_alias=True, mode="json")):
            raise ValueError("Mission intent basis fingerprint mismatch")
        return self

    def reference(self) -> dict:
        return {
            "basisSchemaVersion": self.basis_schema_version, "missionId": self.mission_id,
            "sourceType": self.source_type, "baseMissionRevision": self.source_revision,
            "commitId": self.commit_id, "fingerprintVersion": self.fingerprint_version,
            "fingerprint": self.fingerprint,
        }


def intent_basis_fingerprint(payload: dict) -> str:
    """v1: UTF-8 canonical JSON, sorted keys and sets; no Unicode/text rewriting."""
    import hashlib
    import json

    content = {key: value for key, value in payload.items() if key != "fingerprint"}
    content["constraints"] = [
        {**item, "sourceRefs": sorted(set(item.get("sourceRefs", ())))}
        for item in sorted(content.get("constraints", ()), key=lambda item: item["constraintId"])
    ]
    content["sourceReferences"] = sorted(set(content.get("sourceReferences", ())))
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_intent_basis(run) -> MissionIntentBasis | None:
    """Validate the persisted basis on every boundary, including restart."""
    if "missionIntentBasis" not in run.execution_state:
        return None
    basis = MissionIntentBasis.model_validate(run.execution_state["missionIntentBasis"])
    if basis.mission_id != run.mission_id:
        raise ValueError("Mission intent basis belongs to another Mission")
    return basis
