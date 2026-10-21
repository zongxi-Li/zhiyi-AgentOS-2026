"""Durable execution permission for one activated graph handoff."""

from typing import Literal

from pydantic import Field, model_validator

from contracts.graph_revision import Digest, GraphContract, Ref


class ExecutionPermitRecord(GraphContract):
    """Workflow-owned permit binding one activation to a promoted checkpoint.

    PREPARING is a reconciliation journal only. Only ISSUED is executable, and
    the Run projection must match this entire identity before the scheduler can
    enter the graph.
    """

    version: Literal["execution-permit-v1"] = "execution-permit-v1"
    permit_id: Ref = Field(alias="permitId")
    idempotency_key: Ref = Field(alias="idempotencyKey")
    handoff_id: Ref = Field(alias="handoffId")
    activation_id: Ref = Field(alias="activationId")
    mission_id: Ref = Field(alias="missionId")
    run_id: Ref = Field(alias="runId")
    graph_id: Ref = Field(alias="graphId")
    source_kind: Literal["graph_revision", "initial_plan"] = Field(default="graph_revision", alias="sourceKind", exclude_if=lambda v: v == "graph_revision")
    graph_version: int = Field(strict=True, ge=1, alias="graphVersion")
    package_checksum: Digest = Field(alias="packageChecksum")
    staged_checkpoint_id: Ref = Field(alias="stagedCheckpointId")
    staged_checkpoint_fingerprint: Digest = Field(alias="stagedCheckpointFingerprint")
    source_checkpoint_id: Ref | None = Field(alias="sourceCheckpointId")
    source_checkpoint_version: int | None = Field(strict=True, ge=1, alias="sourceCheckpointVersion")
    promoted_checkpoint_id: Ref = Field(alias="promotedCheckpointId")
    promoted_checkpoint_version: int = Field(strict=True, ge=1, alias="promotedCheckpointVersion")
    source_run_fingerprint: Digest = Field(alias="sourceRunFingerprint")
    handoff_fingerprint: Digest = Field(alias="handoffFingerprint")
    source_identity_fingerprint: Digest = Field(alias="sourceIdentityFingerprint")
    candidate_identity_fingerprint: Digest = Field(alias="candidateIdentityFingerprint")
    principal_fingerprint: Digest = Field(alias="principalFingerprint")
    attempt_generation: Ref = Field(alias="attemptGeneration")
    status: Literal["PREPARING", "ISSUED", "REVOKED"]

    @model_validator(mode="after")
    def consistent(self):
        if self.source_kind == "initial_plan":
            if self.graph_version != 1 or self.source_checkpoint_id is not None or self.source_checkpoint_version is not None or self.promoted_checkpoint_version != 1:
                raise ValueError("initial permit requires the first checkpoint without a historical source")
        elif (self.graph_version < 2 or self.source_checkpoint_id is None or self.source_checkpoint_version is None
                or self.promoted_checkpoint_version != self.source_checkpoint_version + 1):
            raise ValueError("permit checkpoint promotion must advance exactly one version")
        return self


class ExecutionPermitReceipt(GraphContract):
    status: Literal["PREPARING", "ISSUED", "IDEMPOTENT_REPLAY", "REJECTED"]
    permit_id: Ref | None = Field(default=None, alias="permitId")
    run_id: Ref | None = Field(default=None, alias="runId")
    graph_version: int | None = Field(default=None, alias="graphVersion")
    code: str | None = None
    reason: str | None = Field(default=None, max_length=500)


def execution_permit_projection(record: ExecutionPermitRecord) -> dict:
    """Small immutable identity copied into RuntimeRunRecord after issuance."""
    return {
        "permitId": record.permit_id,
        "attemptGeneration": record.attempt_generation,
        "handoffId": record.handoff_id,
        "activationId": record.activation_id,
        "runId": record.run_id,
        "graphId": record.graph_id,
        "graphVersion": record.graph_version,
        "packageChecksum": record.package_checksum,
        "checkpointId": record.promoted_checkpoint_id,
        "checkpointVersion": record.promoted_checkpoint_version,
        "status": "ISSUED",
    }


__all__ = ["ExecutionPermitRecord", "ExecutionPermitReceipt", "execution_permit_projection"]
