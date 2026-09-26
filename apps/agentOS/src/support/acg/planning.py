"""Typed planning-side resource and context contracts for the ACG kernel."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.authority import LogicalAgentId


class PlanningSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class AgentBindingSpec(PlanningSpec):
    """Logical planner assignment; it is not a runtime resource identifier."""

    step_id: str = Field(alias="stepId", min_length=1)
    planned_agent_id: LogicalAgentId = Field(alias="plannedAgentId", min_length=1)
    role: str = ""
    required_capabilities: tuple[str, ...] = Field(
        default=(), alias="requiredCapabilities"
    )
    max_concurrency: int = Field(default=1, alias="maxConcurrency", ge=1)
    ephemeral: bool = False


class SkillRequirementSpec(PlanningSpec):
    step_id: str = Field(alias="stepId", min_length=1)
    skill_id: str = Field(alias="skillId", min_length=1)
    tool_name: str | None = Field(default=None, alias="toolName")
    version: str = "1.0.0"
    input_spec: dict[str, Any] = Field(default_factory=dict, alias="inputSpec")
    output_spec: dict[str, Any] = Field(default_factory=dict, alias="outputSpec")


class MemoryAccessSpec(PlanningSpec):
    step_id: str = Field(alias="stepId", min_length=1)
    memory_id: str = Field(alias="memoryId", min_length=1)
    access: Literal["read", "write"]
    memory_type: str = Field(default="working", alias="memoryType", min_length=1)
    storage_type: str = Field(default="inline", alias="storageType", min_length=1)
    retention_policy: str = Field(default="task", alias="retentionPolicy", min_length=1)
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")


class EvidenceSpec(PlanningSpec):
    evidence_id: str = Field(alias="evidenceId", min_length=1)
    producer_step_id: str | None = Field(default=None, alias="producerStepId")
    consumer_step_ids: tuple[str, ...] = Field(default=(), alias="consumerStepIds")
    evidence_type: str = Field(default="document", alias="evidenceType", min_length=1)
    source: str = ""
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")


class CommunicationSpec(PlanningSpec):
    producer_step_id: str = Field(alias="producerStepId", min_length=1)
    consumer_step_id: str = Field(alias="consumerStepId", min_length=1)
    mode: str = "STRICT_CONTRACT"
    allowed_fields: tuple[str, ...] = Field(default=(), alias="allowedFields")
    channel: str = Field(min_length=1)
    max_tokens: int | None = Field(default=None, alias="maxTokens", ge=0)
    schema_hash: str | None = Field(default=None, alias="schemaHash")
    backlog_limit: int = Field(default=1000, alias="backlogLimit", ge=1)
    partition: str | None = None
    max_rounds: int | None = Field(default=None, alias="maxRounds", ge=1)
    quorum: int | None = Field(default=None, ge=1)
    participant_step_ids: tuple[str, ...] = Field(
        default=(), alias="participantStepIds"
    )


class ACGResourcePlan(PlanningSpec):
    """Planner-owned resource/context semantics kept outside executable topology."""

    bindings: tuple[AgentBindingSpec, ...] = ()
    skills: tuple[SkillRequirementSpec, ...] = ()
    memory: tuple[MemoryAccessSpec, ...] = ()
    evidence: tuple[EvidenceSpec, ...] = ()
    communication: tuple[CommunicationSpec, ...] = ()


__all__ = [
    "ACGResourcePlan",
    "AgentBindingSpec",
    "CommunicationSpec",
    "EvidenceSpec",
    "MemoryAccessSpec",
    "PlanningSpec",
    "SkillRequirementSpec",
]
