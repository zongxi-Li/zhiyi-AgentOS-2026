"""Versioned compilation evidence for an accepted initial plan, never a graph."""
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from contracts.graph_revision import Digest, GraphContract, Ref
from contracts.identity import MissionId
from contracts.mission_semantic import MissionIntentBasis
from contracts.planning import TaskPlan
from contracts.workflow import RunExecutionScope, WorkflowDefinition
from support.acg.capabilities import CapabilityCatalog, PlanningCapabilityDescriptor
from support.acg.semantic_profile import TaskSemanticProfile


class InitialCompilationPolicy(GraphContract):
    version: Literal["initial-compilation-policy-v1"] = "initial-compilation-policy-v1"
    versions: dict[str, Ref]
    implementations: dict[str, Digest]

    @model_validator(mode="after")
    def complete(self):
        if set(self.versions) != {"topology", "bindingSolver", "lowerer", "graphCompiler", "routing", "acceptance"}:
            raise ValueError("incomplete initial compilation policy")
        if set(self.implementations) != {"topology", "bindingSolver", "lowerer", "graphCompiler", "routing", "loweringInput"}:
            raise ValueError("incomplete initial compiler implementation identities")
        return self


class InitialPlanningSourceProvenance(GraphContract):
    version: Literal["initial-static-v1"] = "initial-static-v1"
    source_run_id: Ref = Field(alias="sourceRunId")
    mission_id: MissionId = Field(alias="missionId")
    mission_revision: int = Field(strict=True, ge=1, alias="missionRevision")
    basis: MissionIntentBasis
    scope: RunExecutionScope
    workflow: WorkflowDefinition
    semantic_profile: TaskSemanticProfile | None = Field(alias="semanticProfile")
    run_domain: str = Field(alias="runDomain")
    # Exact JSON projections of the existing AgentProfile/Identity contracts.
    # Capture revalidates them through their owning models; no runtime instances.
    agent_profiles: tuple[dict[str, JsonValue], ...] = Field(max_length=256, alias="agentProfiles")
    catalog: tuple[PlanningCapabilityDescriptor, ...] = Field(min_length=1, max_length=512)
    validation_catalog: tuple[PlanningCapabilityDescriptor, ...] = Field(min_length=1, max_length=512, alias="validationCatalog")
    identity_snapshot: TaskPlan | None = Field(alias="identitySnapshot")
    identity_fingerprint: Digest = Field(alias="identityFingerprint")
    material_refs: tuple[JsonValue, ...] = Field(max_length=256, alias="materialRefs")
    lowering_options: dict[str, JsonValue] = Field(alias="loweringOptions")
    input_fingerprint: Digest = Field(alias="inputFingerprint")
    runtime_fingerprint: Digest = Field(alias="runtimeFingerprint")
    policy: InitialCompilationPolicy
    static_fingerprint: Digest = Field(alias="staticFingerprint")

    def content_fingerprint(self):
        import hashlib
        import json
        body = self.model_dump(mode="json", by_alias=True, exclude={"static_fingerprint"})
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    @model_validator(mode="after")
    def coherent(self):
        import hashlib
        import json
        if (self.basis.mission_id != self.mission_id or self.basis.source_revision != self.mission_revision
                or self.basis.source_type != "SEMANTIC" or self.workflow.workflow_id not in self.scope.workflow_ids):
            raise ValueError("initial source Mission, basis or workflow mismatch")
        ids = [p.get("agentId") or p.get("agentName") for p in self.agent_profiles]
        if (len(ids) != len(set(ids)) or set(ids) != set(self.scope.agent_ids)
                or any(not {"agentId", "agentName", "domain", "capabilities"} <= set(p) for p in self.agent_profiles)):
            raise ValueError("initial source profiles do not cover frozen scope")
        for descriptors in (self.catalog, self.validation_catalog):
            CapabilityCatalog(descriptors).validate()
        if {d.capability_id for d in self.catalog} != set(self.scope.capability_ids):
            raise ValueError("initial catalog does not cover frozen scope")
        if self.identity_snapshot is not None and self.identity_snapshot.mission_id != self.mission_id:
            raise ValueError("initial Identity snapshot belongs to another Mission")
        identity_body = self.identity_snapshot.model_dump(mode="json", by_alias=True) if self.identity_snapshot else None
        identity_digest = hashlib.sha256(json.dumps(identity_body, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        if identity_digest != self.identity_fingerprint or self.static_fingerprint != self.content_fingerprint():
            raise ValueError("initial source content checksum mismatch")
        return self


def initial_strategy_fingerprint(runtime_fingerprint: str, provenance: InitialPlanningSourceProvenance) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps({"projection": "initial-acceptance-v1",
        "runtimeFingerprint": runtime_fingerprint, "sourceFingerprint": provenance.static_fingerprint},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
