"""Durable graph activation facts and the formal version head; never an execution permit."""
from typing import Literal
from pydantic import Field, model_validator
from contracts.graph_revision import Digest, GraphContract, Ref
from contracts.planning_commit import PlanningCommitRejectionCode


class GraphActivationRecord(GraphContract):
    """One controlled activation of an inactive materialization on its source Run."""

    version: Literal["graph-activation-v1"] = "graph-activation-v1"
    activation_id: Ref = Field(alias="activationId")
    idempotency_key: Ref = Field(alias="idempotencyKey")
    materialization_id: Ref = Field(alias="materializationId")
    source_commit_id: Ref = Field(alias="sourceCommitId")
    mission_id: Ref = Field(alias="missionId")
    run_id: Ref = Field(alias="runId")
    graph_id: Ref = Field(alias="graphId")
    source_kind: Literal["graph_revision", "initial_plan"] = Field(default="graph_revision", alias="sourceKind")
    source_graph_version: int | None = Field(strict=True, ge=1, alias="sourceGraphVersion")
    candidate_graph_version: int = Field(strict=True, ge=1, alias="candidateGraphVersion")
    package_checksum: Digest = Field(alias="packageChecksum")
    commitment_fingerprint: Digest = Field(alias="commitmentFingerprint")
    proof_fingerprint: Digest = Field(alias="proofFingerprint")
    activation_policy: Literal["activation-dag-v1"] = Field(default="activation-dag-v1", alias="activationPolicy")
    status: Literal["ACTIVATION_PREPARED", "ACTIVATED_PAUSED"]

    @model_validator(mode="after")
    def coherent(self):
        if (self.source_kind == "initial_plan" and (self.source_graph_version is not None or self.candidate_graph_version != 1)
                or self.source_kind == "graph_revision" and (self.source_graph_version is None
                    or self.candidate_graph_version != self.source_graph_version + 1)):
            raise ValueError("activation must advance the graph version by exactly one")
        return self


class GraphActivationHead(GraphContract):
    """The single formal graph version authority for one Run.

    Presence of a row pins the Run's persisted blueprint identity: ordinary
    ``save_run`` snapshots may no longer persist any other graphId/version.
    """

    run_id: Ref = Field(alias="runId")
    mission_id: Ref = Field(alias="missionId")
    graph_id: Ref = Field(alias="graphId")
    active_graph_version: int = Field(strict=True, ge=1, alias="activeGraphVersion")
    activation_id: Ref = Field(alias="activationId")


class GraphActivationReceipt(GraphContract):
    status: Literal["ACTIVATION_PREPARED", "ACTIVATED_PAUSED", "IDEMPOTENT_REPLAY", "REJECTED"]
    activation_id: Ref | None = Field(default=None, alias="activationId")
    active_graph_version: int | None = Field(default=None, alias="activeGraphVersion")
    code: PlanningCommitRejectionCode | None = None
    reason: str | None = Field(default=None, max_length=500)


def activation_projection(record: GraphActivationRecord, *, superseded_checkpoint_id) -> dict:
    """The minimal hand-off contract projected into the Run for S03-02B.

    The projected status is always ``ACTIVATED_PAUSED``: it is written only by
    the committing activation transaction. ``executionPermit`` stays ``None``
    until a later, separately verified authority issues one; every scheduling
    entry point must keep refusing the Run while it is ``None``.
    """
    return {
        "activationId": record.activation_id,
        "status": "ACTIVATED_PAUSED",
        "materializationId": record.materialization_id,
        "sourceCommitId": record.source_commit_id,
        "graphId": record.graph_id,
        "sourceGraphVersion": record.source_graph_version,
        "activeGraphVersion": record.candidate_graph_version,
        "supersededCheckpointId": superseded_checkpoint_id,
        "executionPermit": None,
    }


__all__ = [
    "GraphActivationRecord",
    "GraphActivationHead",
    "GraphActivationReceipt",
    "activation_projection",
]
