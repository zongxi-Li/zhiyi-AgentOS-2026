"""Identity Graph 中显式持久化的关系实体。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from contracts.identity import (
    AttemptId,
    MissionId,
    ArtifactId,
    ArtifactKey,
    BindingId,
    BlueprintId,
    RunId,
    SemanticTaskKey,
    TaskId,
    new_binding_id,
)
from contracts.authority import LogicalAgentId, RuntimeResourceId
from domain.models import DomainModel, utc_now

from .relations import BlueprintRelationType, IdentityRelation, TaskBindingType


class RunArtifactDisposition(str, Enum):
    """How a Run uses an immutable Artifact identity."""

    GENERATED = "GENERATED"
    REUSED = "REUSED"


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
    resource_id: RuntimeResourceId = Field(alias="resourceId", min_length=1)
    agent_id: LogicalAgentId = Field(alias="agentId", min_length=1)
    model_id: str = Field(alias="modelId", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class RunArtifactBinding(DomainModel):
    """Append-only relationship between a Run and an Artifact logical slot."""

    binding_id: BindingId = Field(default_factory=new_binding_id, alias="bindingId")
    run_id: RunId = Field(alias="runId")
    task_id: TaskId = Field(alias="taskId")
    semantic_task_key: SemanticTaskKey = Field(alias="semanticTaskKey")
    artifact_key: ArtifactKey = Field(alias="artifactKey")
    artifact_id: ArtifactId = Field(alias="artifactId")
    disposition: RunArtifactDisposition
    source_run_id: RunId | None = Field(default=None, alias="sourceRunId")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")

    @model_validator(mode="after")
    def validate_disposition_source(self) -> "RunArtifactBinding":
        if self.disposition is RunArtifactDisposition.GENERATED and self.source_run_id is not None:
            raise ValueError("GENERATED Artifact binding cannot have sourceRunId")
        if self.disposition is RunArtifactDisposition.REUSED:
            if self.source_run_id is None:
                raise ValueError("REUSED Artifact binding requires sourceRunId")
            if self.source_run_id == self.run_id:
                raise ValueError("REUSED Artifact binding must reference another Run")
        return self


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



class ResourceUsageRecord(DomainModel):
    """一次 attempt 对某资源的绑定投影，供资源目录回溯最近使用。"""

    binding_id: BindingId = Field(alias="bindingId")
    attempt_id: AttemptId = Field(alias="attemptId")
    run_id: RunId = Field(alias="runId")
    task_id: TaskId = Field(alias="taskId")
    mission_id: MissionId | None = Field(default=None, alias="missionId")
    task_title: str | None = Field(default=None, alias="taskTitle")
    semantic_task_key: SemanticTaskKey | None = Field(default=None, alias="semanticTaskKey")
    acg_node_id: str | None = Field(default=None, alias="acgNodeId")
    agent_id: LogicalAgentId = Field(alias="agentId")
    model_id: str = Field(alias="modelId")
    attempt_number: int = Field(alias="attemptNumber")
    attempt_status: str = Field(alias="attemptStatus")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    bound_at: datetime = Field(alias="boundAt")


__all__ = [
    "BlueprintNodeBinding",
    "ExecutionBinding",
    "ProvenanceLink",
    "RunArtifactBinding",
    "RunArtifactDisposition",
    "TaskBinding",
    "ResourceUsageRecord",
]
