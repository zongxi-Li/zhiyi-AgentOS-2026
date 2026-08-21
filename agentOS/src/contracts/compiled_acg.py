"""Immutable contracts produced by the ACG compiler and consumed by runtime."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator


class FrozenContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class CompiledNodeKind(str, Enum):
    STEP = "step"
    CONTROL = "control"


class CommunicationMode(str, Enum):
    STRICT_CONTRACT = "STRICT_CONTRACT"
    EVENT = "EVENT"
    BLACKBOARD = "BLACKBOARD"
    DEBATE = "DEBATE"


class CompiledNodeSpec(FrozenContract):
    node_id: StrictStr = Field(alias="nodeId", min_length=1)
    kind: CompiledNodeKind = CompiledNodeKind.STEP
    communication_mode: CommunicationMode = Field(
        default=CommunicationMode.STRICT_CONTRACT,
        alias="communicationMode",
    )
    review_required: bool = Field(default=False, alias="reviewRequired")
    control_type: str | None = Field(default=None, alias="controlType")


class CompiledEdge(FrozenContract):
    edge_id: StrictStr = Field(alias="edgeId", min_length=1)
    source_id: StrictStr = Field(alias="sourceId", min_length=1)
    target_id: StrictStr = Field(alias="targetId", min_length=1)
    edge_type: StrictStr = Field(alias="edgeType", min_length=1)


class BindingRule(FrozenContract):
    step_id: StrictStr = Field(alias="stepId", min_length=1)
    agent_node_ids: tuple[StrictStr, ...] = Field(default=(), alias="agentNodeIds")
    required_capabilities: tuple[StrictStr, ...] = Field(
        default=(), alias="requiredCapabilities"
    )
    allowed_resource_ids: tuple[StrictStr, ...] = Field(
        default=(), alias="allowedResourceIds"
    )
    domain: StrictStr | None = None
    max_concurrency: int = Field(default=1, alias="maxConcurrency", ge=1)
    compatibility_source: bool = Field(default=False, alias="compatibilitySource")


class BindingManifest(FrozenContract):
    rules: tuple[BindingRule, ...] = ()

    def for_step(self, step_id: str) -> BindingRule:
        matches = tuple(rule for rule in self.rules if rule.step_id == step_id)
        if len(matches) != 1:
            raise KeyError(f"binding manifest has no unique rule for step {step_id}")
        return matches[0]


class SkillRule(FrozenContract):
    step_id: StrictStr = Field(alias="stepId", min_length=1)
    skill_node_id: StrictStr = Field(alias="skillNodeId", min_length=1)
    tool_name: StrictStr | None = Field(default=None, alias="toolName")
    version: StrictStr = "1.0.0"
    input_spec: dict[str, Any] = Field(default_factory=dict, alias="inputSpec")
    output_spec: dict[str, Any] = Field(default_factory=dict, alias="outputSpec")
    compatibility_source: bool = Field(default=False, alias="compatibilitySource")


class SkillManifest(FrozenContract):
    rules: tuple[SkillRule, ...] = ()

    def for_step(self, step_id: str) -> tuple[SkillRule, ...]:
        return tuple(rule for rule in self.rules if rule.step_id == step_id)


class MemoryRule(FrozenContract):
    step_id: StrictStr = Field(alias="stepId", min_length=1)
    memory_node_id: StrictStr = Field(alias="memoryNodeId", min_length=1)
    access: Literal["read", "write"]
    memory_type: StrictStr = Field(alias="memoryType", min_length=1)
    storage_type: StrictStr = Field(alias="storageType", min_length=1)
    retention_policy: StrictStr = Field(alias="retentionPolicy", min_length=1)
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    compatibility_source: bool = Field(default=False, alias="compatibilitySource")


class MemoryManifest(FrozenContract):
    rules: tuple[MemoryRule, ...] = ()

    def for_step(self, step_id: str, access: str | None = None) -> tuple[MemoryRule, ...]:
        return tuple(
            rule for rule in self.rules
            if rule.step_id == step_id and (access is None or rule.access == access)
        )


class EvidenceRule(FrozenContract):
    step_id: StrictStr = Field(alias="stepId", min_length=1)
    evidence_node_id: StrictStr = Field(alias="evidenceNodeId", min_length=1)
    evidence_type: StrictStr = Field(alias="evidenceType", min_length=1)
    source: StrictStr
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    compatibility_source: bool = Field(default=False, alias="compatibilitySource")


class EvidenceManifest(FrozenContract):
    rules: tuple[EvidenceRule, ...] = ()

    def for_step(self, step_id: str) -> tuple[EvidenceRule, ...]:
        return tuple(rule for rule in self.rules if rule.step_id == step_id)


class CommunicationRuleSpec(FrozenContract):
    producer_step_id: StrictStr = Field(alias="producerStepId", min_length=1)
    consumer_step_id: StrictStr = Field(alias="consumerStepId", min_length=1)
    mode: CommunicationMode = CommunicationMode.STRICT_CONTRACT
    allowed_fields: tuple[StrictStr, ...] = Field(default=(), alias="allowedFields")
    channel: StrictStr = Field(min_length=1)
    max_tokens: int = Field(alias="maxTokens", ge=0)
    schema_hash: StrictStr | None = Field(default=None, alias="schemaHash")
    backlog_limit: int = Field(default=1000, alias="backlogLimit", ge=1)
    partition: StrictStr | None = None
    max_rounds: int | None = Field(default=None, alias="maxRounds", ge=1)
    quorum: int | None = Field(default=None, ge=1)
    participant_step_ids: tuple[StrictStr, ...] = Field(
        default=(), alias="participantStepIds"
    )

    @model_validator(mode="after")
    def validate_advanced_mode(self) -> "CommunicationRuleSpec":
        if self.mode is CommunicationMode.DEBATE:
            if self.max_rounds is None or self.quorum is None:
                raise ValueError("DEBATE requires maxRounds and quorum")
            if not self.participant_step_ids:
                raise ValueError("DEBATE requires participantStepIds")
            if self.quorum > len(self.participant_step_ids):
                raise ValueError("DEBATE quorum exceeds participants")
        return self


class CommunicationManifestSpec(FrozenContract):
    run_id: StrictStr | None = Field(default=None, alias="runId")
    rules: tuple[CommunicationRuleSpec, ...] = ()
    run_budget: int | None = Field(default=None, alias="runBudget", ge=0)
    step_budgets: dict[str, int] = Field(default_factory=dict, alias="stepBudgets")
    channel_budgets: dict[str, int] = Field(default_factory=dict, alias="channelBudgets")


class ConditionalControlSpec(FrozenContract):
    source_step_id: StrictStr = Field(alias="sourceStepId", min_length=1)
    json_pointer: str = Field(alias="jsonPointer")
    operator: StrictStr = Field(min_length=1)
    targets_by_case: dict[str, StrictStr] = Field(alias="targetsByCase")
    default_target: StrictStr | None = Field(default=None, alias="defaultTarget")


class LoopControlSpec(FrozenContract):
    body_entry_id: StrictStr = Field(alias="bodyEntryId", min_length=1)
    body_exit_id: StrictStr = Field(alias="bodyExitId", min_length=1)
    condition: ConditionalControlSpec
    max_iterations: int = Field(alias="maxIterations", ge=1)
    on_limit: Literal["review", "fail"] = Field(default="review", alias="onLimit")


class ParallelControlSpec(FrozenContract):
    branch_entry_ids: tuple[StrictStr, ...] = Field(alias="branchEntryIds", min_length=2)
    join_node_id: StrictStr = Field(alias="joinNodeId", min_length=1)


class ConsensusControlSpec(FrozenContract):
    participant_step_ids: tuple[StrictStr, ...] = Field(alias="participantStepIds", min_length=1)
    quorum: int = Field(ge=1)
    strategy: Literal["unanimous", "majority", "auditor"] = "majority"
    timeout_seconds: int = Field(default=300, alias="timeoutSeconds", ge=1)
    on_unresolved: Literal["review", "fail"] = Field(default="review", alias="onUnresolved")


class ControlRule(FrozenContract):
    control_id: StrictStr = Field(alias="controlId", min_length=1)
    control_type: StrictStr = Field(alias="controlType", min_length=1)
    condition: ConditionalControlSpec | None = None
    loop: LoopControlSpec | None = None
    parallel: ParallelControlSpec | None = None
    consensus: ConsensusControlSpec | None = None


class ControlManifest(FrozenContract):
    entry_node_ids: tuple[StrictStr, ...] = Field(alias="entryNodeIds", min_length=1)
    exit_node_ids: tuple[StrictStr, ...] = Field(alias="exitNodeIds", min_length=1)
    rules: tuple[ControlRule, ...] = ()


class CompiledACGPackage(FrozenContract):
    package_version: Literal[2] = Field(default=2, alias="packageVersion")
    package_id: StrictStr = Field(alias="packageId", min_length=1)
    run_id: StrictStr | None = Field(default=None, alias="runId")
    blueprint_id: StrictStr = Field(alias="blueprintId", min_length=1)
    blueprint_version: int = Field(alias="blueprintVersion", ge=1)
    blueprint_hash: StrictStr = Field(alias="blueprintHash", min_length=64, max_length=64)
    nodes: tuple[CompiledNodeSpec, ...]
    edges: tuple[CompiledEdge, ...]
    control_manifest: ControlManifest = Field(alias="controlManifest")
    binding_manifest: BindingManifest = Field(alias="bindingManifest")
    skill_manifest: SkillManifest = Field(alias="skillManifest")
    memory_manifest: MemoryManifest = Field(alias="memoryManifest")
    evidence_manifest: EvidenceManifest = Field(alias="evidenceManifest")
    communication_manifest: CommunicationManifestSpec = Field(alias="communicationManifest")
    compatibility_warnings: tuple[StrictStr, ...] = Field(default=(), alias="compatibilityWarnings")
    checksum: StrictStr = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_manifest_coverage(self) -> "CompiledACGPackage":
        step_ids = {node.node_id for node in self.nodes if node.kind is CompiledNodeKind.STEP}
        binding_ids = {rule.step_id for rule in self.binding_manifest.rules}
        if binding_ids != step_ids:
            missing = sorted(step_ids - binding_ids)
            extra = sorted(binding_ids - step_ids)
            raise ValueError(f"binding manifest coverage mismatch: missing={missing}, extra={extra}")
        return self


__all__ = [
    "BindingManifest", "BindingRule", "CommunicationManifestSpec", "CommunicationMode",
    "CommunicationRuleSpec", "CompiledACGPackage", "CompiledEdge", "CompiledNodeKind",
    "CompiledNodeSpec", "ConditionalControlSpec", "ConsensusControlSpec", "ControlManifest",
    "ControlRule", "EvidenceManifest", "EvidenceRule", "LoopControlSpec", "MemoryManifest",
    "MemoryRule", "ParallelControlSpec", "SkillManifest", "SkillRule",
]
