"""图与 Skills 自进化闭环使用的可追溯数据合同。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Literal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvolutionAction(str, Enum):
    """标识技能库或图谱演化可提出的基本变更类型。"""

    ADD = "add"
    MERGE = "merge"
    SPLIT = "split"
    RETIRE = "retire"
    PATCH = "patch"


class SkillLifecycleState(str, Enum):
    """标识技能从候选、验证到退役的治理状态。"""

    CANDIDATE = "candidate"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class EvolutionProposalStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REJECTED_VALIDATION = "rejected_validation"


class PolicyMutation(BaseModel):
    """Closed mutation vocabulary; no executable code or unknown graph nodes."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    mutation_type: Literal[
        "budget_adjustment",
        "skill_preference_adjustment",
        "capability_route_adjustment",
        "registered_validator_insertion",
    ] = Field(alias="mutationType")
    target: str = Field(min_length=1)
    value: int | float | str | list[str]

    @field_validator("value", mode="before")
    @classmethod
    def finite_non_boolean_value(cls, value):
        if isinstance(value, bool) or (isinstance(value, float) and not isfinite(value)):
            raise ValueError("mutation value must be finite and not boolean")
        return value


class EvolutionProposal(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    proposal_id: str = Field(alias="proposalId", min_length=1)
    base_version: int = Field(alias="baseVersion", ge=0)
    trajectory_ids: list[str] = Field(alias="trajectoryIds", min_length=1)
    mutations: list[PolicyMutation] = Field(min_length=1)
    evaluation_checksum: str = Field(alias="evaluationChecksum", min_length=1)
    status: EvolutionProposalStatus = EvolutionProposalStatus.DRAFT
    reviewed_by: str | None = Field(default=None, alias="reviewedBy")
    reviewed_at: datetime | None = Field(default=None, alias="reviewedAt")


class EvolutionPolicyVersion(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    version: int = Field(ge=0)
    base_version: int | None = Field(default=None, alias="baseVersion", ge=0)
    proposal_ids: list[str] = Field(default_factory=list, alias="proposalIds")
    policy: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAt")
    approved_by: str | None = Field(default=None, alias="approvedBy")
    status: Literal["active", "superseded"] = "active"


class EvolutionPublicationReceipt(BaseModel):
    """Durable result of one atomic approval; never rewritten by rollback."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    proposal_id: str = Field(alias="proposalId", min_length=1)
    proposal_checksum: str = Field(alias="proposalChecksum", pattern=r"^[0-9a-f]{64}$")
    policy_version: int = Field(alias="policyVersion", ge=1)
    approved_by: str = Field(alias="approvedBy", min_length=1)
    published_at: datetime = Field(alias="publishedAt")


class TrajectoryStep(BaseModel):
    """记录一次任务轨迹中的单步意图、行为和可审计反馈。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    step_id: str = Field(alias="stepId", min_length=1)
    action_type: str = Field(alias="actionType", min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    feedback: dict[str, Any] = Field(default_factory=dict)


class Trajectory(BaseModel):
    """保存任务、步骤序列、结果和来源技能的完整执行轨迹。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    trajectory_id: str = Field(alias="trajectoryId", min_length=1)
    task: dict[str, Any] = Field(default_factory=dict)
    steps: list[TrajectoryStep] = Field(default_factory=list)
    outcome: dict[str, Any] = Field(default_factory=dict)
    source_skill_ids: list[str] = Field(default_factory=list, alias="sourceSkillIds")
    graph_version: int | None = Field(default=None, alias="graphVersion", ge=1)


class TrajectoryEvaluation(BaseModel):
    """保存成功、效率、新颖度和总质量等多维评估结果。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    trajectory_id: str = Field(alias="trajectoryId", min_length=1)
    success_score: float = Field(alias="successScore", ge=0.0, le=1.0)
    efficiency_score: float = Field(alias="efficiencyScore", ge=0.0, le=1.0)
    novelty_score: float = Field(alias="noveltyScore", ge=0.0, le=1.0)
    quality_score: float = Field(default=0.0, alias="qualityScore", ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)


class SkillCandidate(BaseModel):
    """描述由归纳或对比提炼得到、尚未入库的候选技能。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    candidate_id: str = Field(alias="candidateId", min_length=1)
    applicability: str = Field(min_length=1)
    procedure: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    source_trajectory_ids: list[str] = Field(default_factory=list, alias="sourceTrajectoryIds")
    extraction_mode: str = Field(alias="extractionMode", min_length=1)


class SkillEvolutionProposal(BaseModel):
    """描述技能库的增、并、分、退提案及其可追溯依据。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    proposal_id: str = Field(alias="proposalId", min_length=1)
    action: EvolutionAction
    candidate: SkillCandidate | None = None
    target_skill_ids: list[str] = Field(default_factory=list, alias="targetSkillIds")
    rationale: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class GraphEvolutionProposal(BaseModel):
    """描述图结构变更提案，与既有恢复补丁保持独立的演化语义。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    proposal_id: str = Field(alias="proposalId", min_length=1)
    graph_id: str = Field(alias="graphId", min_length=1)
    base_graph_version: int = Field(alias="baseGraphVersion", ge=1)
    action: EvolutionAction = EvolutionAction.PATCH
    mutations: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = ""
    evidence_trajectory_ids: list[str] = Field(default_factory=list, alias="evidenceTrajectoryIds")


class GraphEvolutionEvaluation(BaseModel):
    """Paired offline results for exactly one candidate and evaluator version."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True, allow_inf_nan=False)

    proposal_id: str = Field(alias="proposalId", min_length=1)
    proposal_checksum: str = Field(alias="proposalChecksum", pattern=r"^[0-9a-f]{64}$")
    sample_ids: tuple[str, ...] = Field(alias="sampleIds", min_length=1)
    evaluator_version: str = Field(alias="evaluatorVersion", min_length=1)
    baseline_quality: float = Field(alias="baselineQuality", ge=0, le=1)
    candidate_quality: float = Field(alias="candidateQuality", ge=0, le=1)
    baseline_cost: float = Field(alias="baselineCost", ge=0)
    candidate_cost: float = Field(alias="candidateCost", ge=0)

    @field_validator("sample_ids")
    @classmethod
    def unique_samples(cls, values):
        if len(set(values)) != len(values) or any(not value.strip() for value in values):
            raise ValueError("paired evaluation needs distinct non-empty sample identities")
        return values


class GraphEvolutionPublicationReceipt(BaseModel):
    """Reference from the external graph version authority, not a Run execution permit."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    proposal_id: str = Field(alias="proposalId", min_length=1)
    proposal_checksum: str = Field(alias="proposalChecksum", pattern=r"^[0-9a-f]{64}$")
    graph_id: str = Field(alias="graphId", min_length=1)
    graph_version: int = Field(alias="graphVersion", ge=1)
    approved_by: str = Field(alias="approvedBy", min_length=1)
    publication_ref: str = Field(alias="publicationRef", min_length=1)


__all__ = [
    "EvolutionAction", "EvolutionPolicyVersion", "EvolutionPublicationReceipt", "EvolutionProposal", "EvolutionProposalStatus", "GraphEvolutionProposal", "PolicyMutation", "SkillCandidate",
    "GraphEvolutionEvaluation", "GraphEvolutionPublicationReceipt",
    "SkillEvolutionProposal", "SkillLifecycleState", "Trajectory",
    "TrajectoryEvaluation", "TrajectoryStep",
]
