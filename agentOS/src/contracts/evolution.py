"""图与 Skills 自进化闭环使用的可追溯数据合同。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


__all__ = [
    "EvolutionAction", "GraphEvolutionProposal", "SkillCandidate",
    "SkillEvolutionProposal", "SkillLifecycleState", "Trajectory",
    "TrajectoryEvaluation", "TrajectoryStep",
]
