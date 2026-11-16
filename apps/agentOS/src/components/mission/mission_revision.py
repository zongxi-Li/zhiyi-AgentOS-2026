"""Version decisions acknowledge differences, never prove semantic equivalence."""
from datetime import datetime
from typing import Literal
from pydantic import Field, StrictStr, field_validator
from contracts.mission_semantic import SemanticModel, run_intent_basis
from contracts.workflow import utc_now


class MissionRevisionDecision(SemanticModel):
    operation_id: StrictStr = Field(alias="operationId", min_length=1, max_length=200)
    source_revision: int = Field(alias="sourceRevision", ge=0, strict=True)
    target_revision: int = Field(alias="targetRevision", ge=1, strict=True)
    decision: Literal["CONTINUE", "REQUEST_REPLAN"]

    @field_validator("operation_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("operationId must not be blank")
        return value


class MissionRevisionReceipt(MissionRevisionDecision):
    mission_id: str = Field(alias="missionId")
    run_id: str = Field(alias="runId")
    actor_id: str = Field(alias="actorId")
    tenant_id: str = Field(alias="tenantId")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class MissionRevisionConflict(ValueError):
    pass


def revision_observation(run, snapshot, receipts):
    basis = run_intent_basis(run)
    source = basis.source_revision if basis and basis.source_type == "SEMANTIC" else 0
    status = ("LEGACY_UNBOUND" if source == 0 else
              "CURRENT" if source == snapshot.mission_revision else "REVISION_CHANGED")
    latest = receipts[-1] if receipts else None
    decision_status = ("UNDECIDED" if latest is None else "DECISION_STALE" if
        latest.target_revision != snapshot.mission_revision else
        "CONTINUE_SELECTED" if latest.decision == "CONTINUE" else "REPLAN_REQUESTED")
    return {"missionId": run.mission_id, "runId": run.run_id, "status": status,
            "sourceRevision": source, "targetRevision": snapshot.mission_revision,
            "decisionStatus": decision_status,
            "runStatus": run.status.value, "impact": "NOT_ANALYZED",
            "decisions": [r.model_dump(by_alias=True, mode="json") for r in receipts]}


def revision_successor_key(receipt):
    import hashlib
    fingerprint = hashlib.sha256(receipt.model_dump_json(by_alias=True).encode("utf-8")).hexdigest()
    return "mission-revision:" + fingerprint, fingerprint


def prepare_revision_decision(run, snapshot, request, principal, previous):
    receipt = MissionRevisionReceipt(**request.model_dump(), mission_id=run.mission_id,
        run_id=run.run_id, actor_id=principal.actor_id, tenant_id=principal.tenant_id)
    if previous:
        if previous.model_dump(exclude={"created_at"}) != receipt.model_dump(exclude={"created_at"}):
            raise MissionRevisionConflict("OPERATION_CONFLICT")
        return previous
    if run.record_state.value != "active":
        raise MissionRevisionConflict("RUN_NOT_ACTIVE")
    if run.status.value in {"completed", "failed", "cancelled", "superseded"}:
        raise MissionRevisionConflict("RUN_TERMINAL")
    basis = run_intent_basis(run)
    source = basis.source_revision if basis and basis.source_type == "SEMANTIC" else 0
    if request.source_revision != source or request.target_revision != snapshot.mission_revision:
        raise MissionRevisionConflict("REVISION_CONFLICT")
    if source == snapshot.mission_revision:
        raise MissionRevisionConflict("REVISION_ALREADY_CURRENT")
    return receipt


def validate_revision_successor(run, source, snapshot, choices):
    request = run.execution_state.get("missionRevisionDecision")
    if request is None:
        return
    if not choices or choices[-1].model_dump(by_alias=True, mode="json") != request:
        raise MissionRevisionConflict("DECISION_SUPERSEDED")
    if request["decision"] != "REQUEST_REPLAN":
        raise MissionRevisionConflict("DECISION_NOT_REPLAN")
    basis = run_intent_basis(run)
    if (not basis or basis.source_revision != request["targetRevision"] or
            snapshot.mission_revision != request["targetRevision"]):
        raise MissionRevisionConflict("REVISION_CONFLICT")
    if (source is None or source.run_id != request["runId"] or source.status.value != "cancelled" or
            source.record_state.value != "active"):
        raise MissionRevisionConflict("SOURCE_NOT_CANCELLED")
