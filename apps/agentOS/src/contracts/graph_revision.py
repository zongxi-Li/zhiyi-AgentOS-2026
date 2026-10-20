"""Server-owned, immutable graph commitment evidence; never an execution permit."""
import hashlib
import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from contracts.identity import MissionId
from contracts.planning import TaskPlan, TaskImplementationBinding
from contracts.recovery import GraphPatch
from support.acg.schema import RuntimeBlueprintSpec

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Ref = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


def digest_model(model):
    return hashlib.sha256(json.dumps(model.model_dump(mode="json", by_alias=True),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class GraphContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class PlanningSourceProvenance(GraphContract):
    version: Literal["runtime-static-v1", "runtime-static-v2"]
    source_run_id: Ref = Field(alias="sourceRunId")
    graph_id: Ref = Field(alias="graphId")
    basis_fingerprint: Digest = Field(alias="basisFingerprint")
    scope_fingerprint: Digest = Field(alias="scopeFingerprint")
    static_fingerprint: Digest = Field(alias="staticFingerprint")
    compiler_version: Ref = Field(alias="compilerVersion")
    validation_policy: Literal["planning-acceptance-v1"] = Field(default="planning-acceptance-v1", alias="validationPolicy")


class SafeCutProof(GraphContract):
    version: Literal["safe-cut-dag-v1"] = "safe-cut-dag-v1"
    control_policy: Literal["reject-control-regions-v1"] = Field(default="reject-control-regions-v1", alias="controlPolicy")
    protected_task_keys: tuple[str, ...] = Field(alias="protectedTaskKeys")
    protected_node_ids: tuple[str, ...] = Field(alias="protectedNodeIds")
    touched_node_ids: tuple[str, ...] = Field(alias="touchedNodeIds")
    source_graph_fingerprint: Digest = Field(alias="sourceGraphFingerprint")
    candidate_graph_fingerprint: Digest = Field(alias="candidateGraphFingerprint")
    effective_dependency_fingerprint: Digest = Field(alias="effectiveDependencyFingerprint")
    execution_evidence_fingerprint: Digest = Field(alias="executionEvidenceFingerprint")
    checkpoint_fingerprint: Digest = Field(alias="checkpointFingerprint")
    result: Literal["PROVEN"] = "PROVEN"


class GraphRevisionProposal(GraphContract):
    version: Literal["graph-revision-v1"] = "graph-revision-v1"
    source_commit_id: Ref = Field(alias="sourceCommitId")
    mission_id: MissionId = Field(alias="missionId")
    mission_revision: int = Field(strict=True, ge=1, alias="missionRevision")
    source_proposal_fingerprint: Digest = Field(alias="sourceProposalFingerprint")
    source_provenance: PlanningSourceProvenance = Field(alias="sourceProvenance")
    base_plan_version: int = Field(strict=True, ge=1, alias="basePlanVersion")
    lowering_version: Literal["taskplan-lowering-v1"] = Field(default="taskplan-lowering-v1", alias="loweringVersion")
    next_plan: TaskPlan = Field(alias="nextPlan")
    next_bindings: tuple[TaskImplementationBinding, ...] = Field(alias="nextBindings")
    candidate_graph: RuntimeBlueprintSpec = Field(alias="candidateGraph")
    graph_patch: GraphPatch = Field(alias="graphPatch")
    safe_cut: SafeCutProof = Field(alias="safeCut")

    @model_validator(mode="after")
    def coherent(self):
        if (self.next_plan.mission_id != self.mission_id or self.candidate_graph.mission_id != self.mission_id
                or self.next_plan.plan_version != self.base_plan_version + 1
                or self.candidate_graph.graph_id != self.source_provenance.graph_id
                or self.graph_patch.graph_id != self.candidate_graph.graph_id
                or self.graph_patch.graph_version != self.candidate_graph.version
                or digest_model(self.candidate_graph) != self.safe_cut.candidate_graph_fingerprint):
            raise ValueError("graph candidate identity or proof is inconsistent")
        return self
