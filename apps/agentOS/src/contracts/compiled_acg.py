"""Immutable contracts produced by the ACG compiler and consumed by runtime."""

from __future__ import annotations

from collections.abc import Mapping
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
    edge_type: Literal["dependency"] = Field(alias="edgeType")


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
    access: Literal["produce", "consume"]
    evidence_type: StrictStr = Field(alias="evidenceType", min_length=1)
    source: StrictStr
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")


class EvidenceManifest(FrozenContract):
    rules: tuple[EvidenceRule, ...] = ()

    def for_step(self, step_id: str, access: str | None = None) -> tuple[EvidenceRule, ...]:
        return tuple(
            rule for rule in self.rules
            if rule.step_id == step_id and (access is None or rule.access == access)
        )


class CommunicationRuleSpec(FrozenContract):
    producer_step_id: StrictStr = Field(alias="producerStepId", min_length=1)
    consumer_step_id: StrictStr = Field(alias="consumerStepId", min_length=1)
    mode: CommunicationMode = CommunicationMode.STRICT_CONTRACT
    allowed_fields: tuple[StrictStr, ...] = Field(default=(), alias="allowedFields")
    channel: StrictStr = Field(min_length=1)
    max_tokens: int | None = Field(default=None, alias="maxTokens", ge=0)
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
    package_version: Literal[4] = Field(default=4, alias="packageVersion")
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
    checksum: StrictStr = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_canonical_structure(self) -> "CompiledACGPackage":
        node_id_list = [node.node_id for node in self.nodes]
        if len(node_id_list) != len(set(node_id_list)):
            raise ValueError("compiled package contains duplicate nodeId")
        node_ids = set(node_id_list)
        step_ids = {node.node_id for node in self.nodes if node.kind is CompiledNodeKind.STEP}
        control_nodes = {
            node.node_id: node for node in self.nodes if node.kind is CompiledNodeKind.CONTROL
        }

        edge_id_list = [edge.edge_id for edge in self.edges]
        if len(edge_id_list) != len(set(edge_id_list)):
            raise ValueError("compiled package contains duplicate edgeId")
        for edge in self.edges:
            if edge.source_id not in node_ids or edge.target_id not in node_ids:
                raise ValueError(
                    "compiled edge references unknown executable node: "
                    f"{edge.source_id} -> {edge.target_id}"
                )

        binding_id_list = [rule.step_id for rule in self.binding_manifest.rules]
        if len(binding_id_list) != len(set(binding_id_list)):
            raise ValueError("binding manifest contains duplicate stepId")
        binding_ids = set(binding_id_list)
        if binding_ids != step_ids:
            missing = sorted(step_ids - binding_ids)
            extra = sorted(binding_ids - step_ids)
            raise ValueError(f"binding manifest coverage mismatch: missing={missing}, extra={extra}")

        for label, rules in (
            ("skill", self.skill_manifest.rules),
            ("memory", self.memory_manifest.rules),
            ("evidence", self.evidence_manifest.rules),
        ):
            unknown = sorted({rule.step_id for rule in rules} - step_ids)
            if unknown:
                raise ValueError(f"{label} manifest references unknown Step: {unknown}")

        for rule in self.communication_manifest.rules:
            referenced_steps = {
                rule.producer_step_id,
                rule.consumer_step_id,
                *rule.participant_step_ids,
            }
            unknown = sorted(referenced_steps - step_ids)
            if unknown:
                raise ValueError(f"communication manifest references unknown Step: {unknown}")
        unknown_budget_steps = sorted(set(self.communication_manifest.step_budgets) - step_ids)
        if unknown_budget_steps:
            raise ValueError(
                f"communication step budgets reference unknown Step: {unknown_budget_steps}"
            )

        for label, references in (
            ("control entry", self.control_manifest.entry_node_ids),
            ("control exit", self.control_manifest.exit_node_ids),
        ):
            unknown = sorted(set(references) - node_ids)
            if unknown:
                raise ValueError(f"{label} references unknown executable node: {unknown}")

        control_id_list = [rule.control_id for rule in self.control_manifest.rules]
        if len(control_id_list) != len(set(control_id_list)):
            raise ValueError("control manifest contains duplicate controlId")
        if set(control_id_list) != set(control_nodes):
            missing = sorted(set(control_nodes) - set(control_id_list))
            extra = sorted(set(control_id_list) - set(control_nodes))
            raise ValueError(f"control manifest coverage mismatch: missing={missing}, extra={extra}")
        for rule in self.control_manifest.rules:
            control_node = control_nodes[rule.control_id]
            if control_node.control_type != rule.control_type:
                raise ValueError(f"control type mismatch for {rule.control_id}")
            self._validate_condition(rule.condition, step_ids, node_ids, rule.control_id)
            if rule.loop is not None:
                self._require_refs(
                    (rule.loop.body_entry_id, rule.loop.body_exit_id),
                    step_ids,
                    f"LOOP {rule.control_id} body",
                )
                self._validate_condition(
                    rule.loop.condition, step_ids, node_ids, f"LOOP {rule.control_id}"
                )
            if rule.parallel is not None:
                self._require_refs(
                    rule.parallel.branch_entry_ids,
                    step_ids,
                    f"PARALLEL {rule.control_id} branches",
                )
                self._require_refs(
                    (rule.parallel.join_node_id,),
                    set(control_nodes),
                    f"PARALLEL {rule.control_id} join",
                )
            if rule.consensus is not None:
                self._require_refs(
                    rule.consensus.participant_step_ids,
                    step_ids,
                    f"CONSENSUS {rule.control_id} participants",
                )
        return self

    @staticmethod
    def _require_refs(references, allowed: set[str], label: str) -> None:
        unknown = sorted(set(references) - allowed)
        if unknown:
            raise ValueError(f"{label} references unknown node: {unknown}")

    @classmethod
    def _validate_condition(
        cls,
        condition: ConditionalControlSpec | None,
        step_ids: set[str],
        node_ids: set[str],
        label: str,
    ) -> None:
        if condition is None:
            return
        cls._require_refs((condition.source_step_id,), step_ids, f"{label} condition source")
        targets = tuple(condition.targets_by_case.values()) + (
            (condition.default_target,) if condition.default_target is not None else ()
        )
        cls._require_refs(targets, node_ids, f"{label} condition targets")


class UnsupportedCompiledACGPackageVersion(ValueError):
    """Raised when persisted runtime state is not the canonical package version."""


def load_compiled_acg_package(
    value: CompiledACGPackage | Mapping[str, Any],
) -> CompiledACGPackage:
    """Load the canonical V4 runtime contract and reject every other version."""
    if isinstance(value, CompiledACGPackage):
        return value
    payload = dict(value)
    version = payload.get("packageVersion", payload.get("package_version"))
    if version != 4:
        raise UnsupportedCompiledACGPackageVersion(
            f"unsupported CompiledACGPackage version: {version}; canonical version is 4"
        )
    return CompiledACGPackage.model_validate(payload)


__all__ = [
    "BindingManifest", "BindingRule", "CommunicationManifestSpec", "CommunicationMode",
    "CommunicationRuleSpec", "CompiledACGPackage", "CompiledEdge", "CompiledNodeKind",
    "CompiledNodeSpec", "ConditionalControlSpec", "ConsensusControlSpec", "ControlManifest",
    "ControlRule", "EvidenceManifest", "EvidenceRule", "LoopControlSpec", "MemoryManifest",
    "MemoryRule", "ParallelControlSpec", "SkillManifest", "SkillRule",
    "UnsupportedCompiledACGPackageVersion", "load_compiled_acg_package",
]
