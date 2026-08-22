"""Identity Graph 中显式持久化的关系实体。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from contracts.identity import (
    AttemptId,
    BindingId,
    BlueprintId,
    TaskId,
    new_binding_id,
)
from domain.models import DomainModel, utc_now

from .relations import BlueprintRelationType, IdentityRelation, TaskBindingType


class TaskBinding(DomainModel):
    binding_id: BindingId = Field(default_factory=new_binding_id, alias="bindingId")
    task_id: TaskId = Field(alias="taskId")
    blueprint_id: BlueprintId = Field(alias="blueprintId")
    acg_node_id: str = Field(alias="acgNodeId", min_length=1)
    binding_type: TaskBindingType = Field(
        default=TaskBindingType.PRIMARY,
        alias="bindingType",
    )
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class BlueprintNodeBinding(DomainModel):
    binding_id: BindingId = Field(default_factory=new_binding_id, alias="bindingId")
    blueprint_id: BlueprintId = Field(alias="blueprintId")
    source_node_id: str = Field(alias="sourceNodeId", min_length=1)
    target_node_id: str = Field(alias="targetNodeId", min_length=1)
    relation_type: BlueprintRelationType = Field(alias="relationType")

    @model_validator(mode="after")
    def reject_self_relation(self) -> "BlueprintNodeBinding":
        if self.source_node_id == self.target_node_id:
            raise ValueError("Blueprint node relation cannot point to itself")
        return self


class ExecutionBinding(DomainModel):
    binding_id: BindingId = Field(default_factory=new_binding_id, alias="bindingId")
    attempt_id: AttemptId = Field(alias="attemptId")
    acg_node_id: str = Field(alias="acgNodeId", min_length=1)
    resource_id: str = Field(alias="resourceId", min_length=1)
    agent_id: str = Field(alias="agentId", min_length=1)
    model_id: str = Field(alias="modelId", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class ProvenanceLink(DomainModel):
    source_id: str = Field(alias="sourceId", min_length=1)
    target_id: str = Field(alias="targetId", min_length=1)
    relation_type: IdentityRelation = Field(alias="relationType")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")

    @model_validator(mode="after")
    def reject_self_relation(self) -> "ProvenanceLink":
        if self.source_id == self.target_id:
            raise ValueError("Provenance link cannot point to itself")
        return self


__all__ = [
    "BlueprintNodeBinding",
    "ExecutionBinding",
    "ProvenanceLink",
    "TaskBinding",
]
