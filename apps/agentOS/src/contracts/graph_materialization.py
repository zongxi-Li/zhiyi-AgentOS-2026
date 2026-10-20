"""Durable inactive compilation facts, never graph activation or execution permits."""
from typing import Literal
from pydantic import Field, model_validator
from contracts import stable_checksum
from contracts.compiled_acg import CompiledACGPackage
from contracts.graph_revision import GraphContract, Digest, Ref
from contracts.planning_commit import FrozenPlanningSources, PlanningCommitRejectionCode
from contracts.planning import TaskPlan, TaskImplementationBinding
from support.acg.schema import ACGBlueprint


class InitialGraphContent(GraphContract):
    """Durable output of frozen initial lowering, not an activated graph."""
    version: Literal["initial-graph-content-v1"] = "initial-graph-content-v1"
    plan: TaskPlan
    bindings: tuple[TaskImplementationBinding, ...]
    blueprint: ACGBlueprint


class GraphMaterializationRecord(GraphContract):
    version: Literal["graph-materialization-v1"] = "graph-materialization-v1"
    materialization_id: Ref = Field(alias="materializationId")
    idempotency_key: Ref = Field(alias="idempotencyKey")
    source_commit_id: Ref = Field(alias="sourceCommitId")
    commitment_fingerprint: Digest = Field(alias="commitmentFingerprint")
    mission_id: Ref = Field(alias="missionId")
    source_run_id: Ref = Field(alias="sourceRunId")
    graph_id: Ref = Field(alias="graphId")
    source_kind: Literal["graph_revision", "initial_plan"] = Field(default="graph_revision", alias="sourceKind")
    initial_content: InitialGraphContent | None = Field(default=None, alias="initialContent")
    source_graph_version: int | None = Field(strict=True, ge=1, alias="sourceGraphVersion")
    candidate_graph_version: int = Field(strict=True, ge=1, alias="candidateGraphVersion")
    sources: FrozenPlanningSources
    validation_policy: Literal["materialization-dag-v1"] = Field(default="materialization-dag-v1", alias="validationPolicy")
    proof_fingerprint: Digest = Field(alias="proofFingerprint")
    package: CompiledACGPackage
    package_checksum: Digest = Field(alias="packageChecksum")
    status: Literal["MATERIALIZED_INACTIVE"] = "MATERIALIZED_INACTIVE"

    @model_validator(mode="after")
    def coherent(self):
        if self.source_kind == "initial_plan":
            content = self.initial_content
            if (self.source_graph_version is not None or self.candidate_graph_version != 1
                    or self.sources.source_kind != "initial" or self.sources.graph_version is not None
                    or content is None or content.plan.mission_id != self.mission_id
                    or content.blueprint.mission_id != self.mission_id
                    or content.blueprint.graph_id != self.graph_id or content.blueprint.version != 1
                    or stable_checksum(content.blueprint.model_dump(mode="json", by_alias=True)) != self.package.blueprint_hash):
                raise ValueError("invalid initial materialization identity")
        elif (self.initial_content is not None or self.source_graph_version is None
              or self.candidate_graph_version != self.source_graph_version + 1):
            raise ValueError("revision materialization must advance its source by one")
        # Match the existing compiler's input mapping, whose nested contracts
        # are normalized by stable_checksum with their defaults excluded.
        package_body = {field.alias or name: getattr(self.package, name)
                        for name, field in type(self.package).model_fields.items()
                        if name not in {"package_id", "checksum"}}
        if (self.package_checksum != self.package.checksum or stable_checksum(package_body) != self.package_checksum
                or self.package.run_id != self.source_run_id or self.package.blueprint_id != self.graph_id
                or self.package.blueprint_version != self.candidate_graph_version
                or self.sources.mission_id != self.mission_id
                or self.sources.graph_version != self.source_graph_version
                or self.package.package_id != f"acgpkg:{self.graph_id}:{self.candidate_graph_version}:{self.package_checksum[:16]}"):
            raise ValueError("inactive materialization identity or package checksum mismatch")
        return self


class GraphMaterializationReceipt(GraphContract):
    status: Literal["MATERIALIZED_INACTIVE", "IDEMPOTENT_REPLAY", "REJECTED"]
    materialization_id: Ref | None = Field(default=None, alias="materializationId")
    package_checksum: Digest | None = Field(default=None, alias="packageChecksum")
    code: PlanningCommitRejectionCode | None = None
    reason: str | None = Field(default=None, max_length=500)
