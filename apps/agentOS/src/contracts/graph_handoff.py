"""State preparation facts, never execution permission or a recovery head."""
from typing import Any, Literal
from pydantic import Field, model_validator
from contracts.graph_revision import GraphContract, Ref, Digest
from contracts.workflow import GraphRef


class GraphVersionIdentityLink(GraphContract):
    run_id: Ref = Field(alias="runId")
    source_kind: Literal["graph_revision", "initial_plan"] = Field(default="graph_revision", alias="sourceKind", exclude_if=lambda v: v == "graph_revision")
    source_blueprint_id: Ref | None = Field(alias="sourceBlueprintId")
    source_graph: GraphRef | None = Field(alias="sourceGraph")
    candidate_graph: GraphRef = Field(alias="candidateGraph")
    source_identity_fingerprint: Digest = Field(alias="sourceIdentityFingerprint")
    candidate_package_checksum: Digest = Field(alias="candidatePackageChecksum")
    # Existing Attempt identities remain attached to their original graph.
    prefix_attempt_ids: tuple[Ref, ...] = Field(alias="prefixAttemptIds")

    @model_validator(mode="after")
    def source_boundary(self):
        if self.source_kind == "initial_plan":
            if self.source_graph is not None or self.source_blueprint_id is not None or self.prefix_attempt_ids or self.candidate_graph.version != "1":
                raise ValueError("initial Identity has no historical graph or prefix")
        elif self.source_graph is None or self.source_blueprint_id is None:
            raise ValueError("revision requires the existing Identity source")
        return self


class StagedGraphCheckpoint(GraphContract):
    version: Literal["staged-graph-checkpoint-v1"] = "staged-graph-checkpoint-v1"
    checkpoint_id: Ref = Field(alias="checkpointId")
    handoff_id: Ref = Field(alias="handoffId")
    run_id: Ref = Field(alias="runId")
    activation_id: Ref = Field(alias="activationId")
    source_kind: Literal["graph_revision", "initial_plan"] = Field(default="graph_revision", alias="sourceKind", exclude_if=lambda v: v == "graph_revision")
    graph_version: int = Field(strict=True, ge=1, alias="graphVersion")
    package_checksum: Digest = Field(alias="packageChecksum")
    state: dict[str, Any]

    @model_validator(mode="after")
    def consistent(self):
        if (self.source_kind == "initial_plan" and self.graph_version != 1
                or self.source_kind == "graph_revision" and self.graph_version < 2):
            raise ValueError("staged checkpoint source type/version mismatch")
        if self.source_kind == "initial_plan" and any(
                value is not None and value != [] and value != {}
                for key, value in self.state.items() if key not in {"runId", "graphId", "graphVersion", "checkpointId"}):
            raise ValueError("initial staged checkpoint must have an empty execution prefix")
        if (self.state.get("runId") != self.run_id or self.state.get("graphVersion") != self.graph_version
                or self.state.get("checkpointId") != self.checkpoint_id or self.state.get("activeStepIds")
                or self.state.get("reviewPayload") is not None or self.state.get("currentStepId") is not None):
            raise ValueError("staged checkpoint identity or pause boundary mismatch")
        return self


class GraphHandoffRecord(GraphContract):
    version: Literal["graph-handoff-v1"] = "graph-handoff-v1"
    handoff_id: Ref = Field(alias="handoffId")
    idempotency_key: Ref = Field(alias="idempotencyKey")
    run_id: Ref = Field(alias="runId")
    activation_id: Ref = Field(alias="activationId")
    source_kind: Literal["graph_revision", "initial_plan"] = Field(default="graph_revision", alias="sourceKind", exclude_if=lambda v: v == "graph_revision")
    graph_version: int = Field(strict=True, ge=1, alias="graphVersion")
    source_checkpoint_id: Ref | None = Field(alias="sourceCheckpointId")
    source_checkpoint_version: int | None = Field(strict=True, ge=1, alias="sourceCheckpointVersion")
    source_checkpoint_fingerprint: Digest | None = Field(alias="sourceCheckpointFingerprint")
    prefix_fingerprint: Digest = Field(alias="prefixFingerprint")
    sources_fingerprint: Digest = Field(alias="sourcesFingerprint")
    identity_link: GraphVersionIdentityLink = Field(alias="identityLink")
    candidate: StagedGraphCheckpoint
    candidate_fingerprint: Digest = Field(alias="candidateFingerprint")
    status: Literal["STAGING", "STATE_PREPARED"]

    @model_validator(mode="after")
    def consistent(self):
        source = (self.source_checkpoint_id, self.source_checkpoint_version, self.source_checkpoint_fingerprint)
        if (self.candidate.source_kind != self.source_kind or self.identity_link.source_kind != self.source_kind
                or self.source_kind == "initial_plan" and (any(v is not None for v in source) or self.graph_version != 1)
                or self.source_kind == "graph_revision" and (any(v is None for v in source) or self.graph_version < 2)):
            raise ValueError("handoff source boundary mismatch")
        if (self.candidate.handoff_id != self.handoff_id or self.candidate.run_id != self.run_id
                or self.candidate.activation_id != self.activation_id
                or self.candidate.graph_version != self.graph_version or self.identity_link.run_id != self.run_id
                or self.identity_link.candidate_graph.graph_id != self.candidate.state.get("graphId")
                or self.identity_link.candidate_graph.version != str(self.graph_version)
                or self.identity_link.candidate_package_checksum != self.candidate.package_checksum):
            raise ValueError("handoff references disagree")
        return self


class GraphHandoffReceipt(GraphContract):
    status: Literal["STATE_PREPARED", "IDEMPOTENT_REPLAY", "REJECTED"]
    handoff_id: Ref | None = Field(default=None, alias="handoffId")
    code: str | None = None
    reason: str | None = Field(default=None, max_length=500)
