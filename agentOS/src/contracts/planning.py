"""Pure planning contracts and explicit execution binding contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.identity import MissionId
from contracts.content import WorksetSpec


_FORBIDDEN_IDENTITY_KEYS = {
    "acgNodeId", "acg_node_id", "agentId", "agent_id", "agentName", "agent_name",
    "attemptId", "attempt_id", "modelId", "model_id", "resourceId", "resource_id",
    "runId", "run_id", "stepExecutionId", "step_execution_id",
}
_ALLOWED_METADATA_KEYS = {
    "plannerStrategy", "strategy", "capability", "source", "rationale", "risk",
    "plannerAlgorithmVersion", "planningDiversity", "planningSeed",
    "capabilityCatalogRevision", "taskType", "domain",
    "degraded", "degradationReason", "promptVersion", "complexityBand",
    "planningBudget",
}


def _reject_execution_identity(value: Any) -> None:
    """Reject execution identities recursively, including tuple-shaped payloads."""
    if isinstance(value, dict):
        forbidden = _FORBIDDEN_IDENTITY_KEYS.intersection(value)
        if forbidden:
            raise ValueError(
                "TaskPlan cannot contain execution identities: "
                + ", ".join(sorted(forbidden))
            )
        for nested in value.values():
            _reject_execution_identity(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_execution_identity(nested)


class SemanticTaskRelationType(str, Enum):
    PARENT = "parent"
    DEPENDS_ON = "depends_on"


class TaskPlanRelation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    source_key: str = Field(alias="sourceKey", min_length=1)
    target_key: str = Field(alias="targetKey", min_length=1)
    relation_type: SemanticTaskRelationType = Field(alias="relationType")

    @model_validator(mode="after")
    def validate_not_self(self) -> "TaskPlanRelation":
        if self.source_key == self.target_key:
            raise ValueError("TaskPlanRelation cannot point to itself")
        return self


class PlannedTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    parent_key: str | None = Field(default=None, alias="parentKey")
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    capability_requirements: tuple[str, ...] = Field(
        default_factory=tuple,
        alias="capabilityRequirements",
    )
    acceptance_criteria: tuple[str, ...] = Field(
        default_factory=tuple,
        alias="acceptanceCriteria",
    )
    source_refs: tuple[str, ...] = Field(default_factory=tuple, alias="sourceRefs")
    decomposition_rationale: str = Field(default="", alias="decompositionRationale")
    logical_role: str = Field(default="task", alias="logicalRole")
    workset: WorksetSpec | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_semantic_only(self) -> "PlannedTask":
        if self.parent_key == self.key:
            raise ValueError("PlannedTask cannot be its own parent")
        _reject_execution_identity(self.model_dump(by_alias=True))
        unknown = set(self.metadata) - _ALLOWED_METADATA_KEYS
        if unknown:
            raise ValueError("PlannedTask metadata contains non-planning keys: " + ", ".join(sorted(unknown)))
        return self


class TaskPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    mission_id: MissionId = Field(alias="missionId")
    plan_version: int = Field(default=1, alias="planVersion", ge=1)
    nodes: tuple[PlannedTask, ...] = Field(min_length=1)
    relations: tuple[TaskPlanRelation, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self) -> "TaskPlan":
        keys = [node.key for node in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("TaskPlan contains duplicate semantic keys")
        known = set(keys)
        for node in self.nodes:
            if node.parent_key is not None and node.parent_key not in known:
                raise ValueError(f"TaskPlan node has unknown parent: {node.parent_key}")
        for relation in self.relations:
            if relation.source_key not in known or relation.target_key not in known:
                raise ValueError("TaskPlan relation references an unknown semantic key")
        unresolved = {node.key: node.parent_key for node in self.nodes}
        resolved: set[str] = set()
        while unresolved:
            ready = [
                key for key, parent in unresolved.items()
                if parent is None or parent in resolved
            ]
            if not ready:
                raise ValueError("TaskPlan contains a parent cycle")
            resolved.update(ready)
            for key in ready:
                unresolved.pop(key)
        dependencies: dict[str, set[str]] = {key: set() for key in known}
        for relation in self.relations:
            if relation.relation_type == SemanticTaskRelationType.DEPENDS_ON:
                dependencies[relation.target_key].add(relation.source_key)
        resolved_dependencies: set[str] = set()
        remaining = dict(dependencies)
        while remaining:
            ready = [key for key, deps in remaining.items() if deps <= resolved_dependencies]
            if not ready:
                raise ValueError("TaskPlan contains a dependency cycle")
            resolved_dependencies.update(ready)
            for key in ready:
                remaining.pop(key)
        _reject_execution_identity(self.metadata)
        unknown = set(self.metadata) - _ALLOWED_METADATA_KEYS
        if unknown:
            raise ValueError("TaskPlan metadata contains non-planning keys: " + ", ".join(sorted(unknown)))
        return self


class TaskImplementationBinding(BaseModel):
    """Builder-owned mapping from a semantic plan key to an executable ACG node."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    plan_node_key: str = Field(alias="planNodeKey", min_length=1)
    acg_node_id: str = Field(alias="acgNodeId", min_length=1)


class TaskBindingPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    bindings: tuple[TaskImplementationBinding, ...] = Field(min_length=1)


class TaskPlanPatch(BaseModel):
    """Semantic-only incremental plan change. Execution bindings are separate."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    mission_id: MissionId = Field(alias="missionId")
    base_plan_version: int = Field(alias="basePlanVersion", ge=1)
    plan_version: int = Field(alias="planVersion", ge=2)
    add_nodes: tuple[PlannedTask, ...] = Field(default_factory=tuple, alias="addNodes")
    retire_keys: tuple[str, ...] = Field(default_factory=tuple, alias="retireKeys")
    replace_keys: tuple[str, ...] = Field(default_factory=tuple, alias="replaceKeys")
    relations: tuple[TaskPlanRelation, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_increment(self) -> "TaskPlanPatch":
        if self.plan_version != self.base_plan_version + 1:
            raise ValueError("TaskPlanPatch planVersion must increment basePlanVersion by one")
        keys = [node.key for node in self.add_nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("TaskPlanPatch contains duplicate semantic keys")
        if set(self.retire_keys).intersection(keys):
            raise ValueError("TaskPlanPatch cannot add and retire the same semantic key")
        if set(self.replace_keys).intersection(self.retire_keys):
            raise ValueError("TaskPlanPatch cannot replace and retire the same semantic key")
        _reject_execution_identity(self.metadata)
        return self


class PlanExpansionRequest(BaseModel):
    """Safe-checkpoint request for an additive semantic plan expansion.

    Capacity recovery may add smaller semantic units, but it cannot retire, replace or
    rewrite already completed work through this contract.  Builder-owned Blueprint and
    identity bindings remain separate downstream artifacts.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    mission_id: MissionId = Field(alias="missionId")
    base_plan_version: int = Field(alias="basePlanVersion", ge=1)
    checkpoint_ref: str = Field(alias="checkpointRef", min_length=1)
    reason: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(default_factory=tuple, alias="sourceRefs")
    add_nodes: tuple[PlannedTask, ...] = Field(alias="addNodes", min_length=1)
    relations: tuple[TaskPlanRelation, ...] = Field(default_factory=tuple)

    def to_patch(self) -> TaskPlanPatch:
        return TaskPlanPatch(
            missionId=self.mission_id,
            basePlanVersion=self.base_plan_version,
            planVersion=self.base_plan_version + 1,
            addNodes=self.add_nodes,
            relations=self.relations,
            metadata={"source": "plan_expansion", "rationale": self.reason},
        )


__all__ = [
    "TaskBindingPatch",
    "TaskImplementationBinding",
    "PlanExpansionRequest",
    "SemanticTaskRelationType",
    "TaskPlan",
    "PlannedTask",
    "TaskPlanPatch",
    "TaskPlanRelation",
    "WorksetSpec",
]
