"""HTN definitions are trusted configuration; expansion is only a semantic proposal.

No execution identities, bindings, commit operations or alternate TaskPlan contract.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.identity import SemanticTaskKey
from contracts.planning import PlannedTask, TaskPlanRelation


class HTNContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class HTNCondition(HTNContract):
    """Conjunction of closed equality predicates; missing facts never satisfy one."""
    source: Literal["basis_source_type", "constraint", "wake_reason", "step_status", "audit_outcome"]
    key: str | None = Field(default=None, max_length=200)
    equals: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def closed_predicate(self):
        needs_key = self.source in {"constraint", "step_status", "audit_outcome"}
        if (needs_key != (self.key is not None) or not self.equals.strip()
                or (self.key is not None and not self.key.strip())):
            raise ValueError("predicate requires a key exactly for constraint or step facts")
        return self


class HTNSubtask(HTNContract):
    # task.key is a method-local stable slot, not a model-assigned runtime identity.
    task: PlannedTask
    abstract_task: SemanticTaskKey | None = Field(default=None, alias="abstractTask")

    @model_validator(mode="after")
    def template_semantics(self):
        if self.task.parent_key is not None or self.task.workset is not None:
            raise ValueError("method slots cannot set parentKey or workset")
        if self.abstract_task is not None:
            if self.task.capability_requirements or self.task.produced_artifacts:
                raise ValueError("abstract slots cannot claim atomic capabilities or products")
        elif len(self.task.capability_requirements) != 1:
            raise ValueError("atomic slots require exactly one catalog capability")
        return self


class HTNMethod(HTNContract):
    method_id: SemanticTaskKey = Field(alias="methodId")
    abstract_task: SemanticTaskKey = Field(alias="abstractTask")
    version: int = Field(default=1, ge=1)
    priority: int = Field(default=0, ge=0, le=1000)
    applicability: tuple[HTNCondition, ...] = Field(default=(), max_length=32)
    subtasks: tuple[HTNSubtask, ...] = Field(min_length=1, max_length=32)
    # depends_on: source is prerequisite, target is consumer. Only local slots.
    ordering: tuple[TaskPlanRelation, ...] = Field(default=(), max_length=128)
    source_refs: tuple[str, ...] = Field(alias="sourceRefs", min_length=1, max_length=16)

    @model_validator(mode="after")
    def local_definition(self):
        keys = [slot.task.key for slot in self.subtasks]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate method-local slot")
        if any(not ref.strip() or len(ref) > 500 for ref in self.source_refs):
            raise ValueError("method sources must be nonblank and bounded")
        for edge in self.ordering:
            if edge.relation_type.value != "depends_on" or not {edge.source_key, edge.target_key} <= set(keys):
                raise ValueError("method ordering must reference local dependency slots")
        return self


class HTNMethodCandidate(HTNContract):
    method_id: str = Field(alias="methodId")
    abstract_task: str = Field(alias="abstractTask")
    version: int
    applicable: bool
    reason: Literal["APPLICABLE", "CONDITION_NOT_MET", "CAPABILITY_UNAVAILABLE"]
    source_refs: tuple[str, ...] = Field(alias="sourceRefs")
    applicability: tuple[HTNCondition, ...] = ()
    subtasks: tuple[HTNSubtask, ...] = ()
    ordering: tuple[TaskPlanRelation, ...] = ()


class HTNMethodCatalogProjection(HTNContract):
    target_key: str = Field(alias="targetKey")
    catalog_revision: str = Field(alias="catalogRevision")
    candidates: tuple[HTNMethodCandidate, ...]


class HTNMethodSelection(HTNContract):
    task_key: str = Field(alias="taskKey")
    abstract_task: str = Field(alias="abstractTask")
    method_id: str = Field(alias="methodId")
    method_version: int = Field(alias="methodVersion")


class HTNExpansionProposal(HTNContract):
    """Reuses PlannedTask and relations, never a patch or executable graph."""
    target_key: str = Field(alias="targetKey")
    catalog_revision: str = Field(alias="catalogRevision")
    basis_fingerprint: str = Field(alias="basisFingerprint")
    observation_id: str = Field(alias="observationId")
    base_plan_version: int = Field(alias="basePlanVersion")
    nodes: tuple[PlannedTask, ...]
    relations: tuple[TaskPlanRelation, ...]
    boundary_relations: tuple[TaskPlanRelation, ...] = Field(default=(), alias="boundaryRelations")
    atomic_keys: tuple[str, ...] = Field(alias="atomicKeys")
    selections: tuple[HTNMethodSelection, ...]
