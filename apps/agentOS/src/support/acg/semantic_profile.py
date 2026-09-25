"""Planner semantic profile contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from .schema import ComplexityLevel

class CapabilityCandidate(BaseModel):
    """按目录归一且携带可审计置信分数的语义能力候选。

    ``score`` 被限制在 0 至 1，``matched_terms`` 和 ``source`` 保存推断依据；模型冻结，
    防止解析后的候选在路由前发生漂移。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    capability_id: str = Field(alias="capabilityId")
    score: float = Field(ge=0, le=1)
    matched_terms: List[str] = Field(default_factory=list, alias="matchedTerms")
    source: Literal["catalog_alias", "llm", "fallback", "dependency", "workflow_template"]
    rationale: str = ""


class ComplexityAssessment(BaseModel):
    """Deterministic six-axis complexity assessment used as a planning budget."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    level: ComplexityLevel
    score: int = Field(ge=0, le=18)
    dimensions: Dict[str, int] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    method: str = "deterministic-six-axis.v1"


class TaskSemanticProfile(BaseModel):
    """结构化任务语义画像。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    primary_goal: str = Field(default="", alias="primaryGoal")
    key_constraints: List[str] = Field(default_factory=list, alias="keyConstraints")
    required_capabilities: List[str] = Field(default_factory=list, alias="requiredCapabilities")
    capability_candidates: List[CapabilityCandidate] = Field(
        default_factory=list, alias="capabilityCandidates"
    )
    expected_artifacts: List[str] = Field(default_factory=list, alias="expectedArtifacts")
    verification_requirements: List[str] = Field(
        default_factory=list,
        alias="verificationRequirements",
    )
    estimated_complexity: ComplexityLevel = Field(
        default=ComplexityLevel.SIMPLE, alias="estimatedComplexity"
    )
    complexity_assessment: ComplexityAssessment | None = Field(
        default=None,
        alias="complexityAssessment",
    )
    domain_hint: str = Field(default="general", alias="domainHint")
    task_type_hint: str = Field(default="general", alias="taskTypeHint")
    implicit_requirements: List[str] = Field(default_factory=list, alias="implicitRequirements")
    risk_level: str = Field(default="normal", alias="riskLevel")
    resource_budget: Dict[str, Any] = Field(default_factory=dict, alias="resourceBudget")
    entropy_budget: int = Field(default=0, alias="entropyBudget")
    raw_intent: str = Field(default="", alias="rawIntent")

    def to_summary(self) -> str:
        """生成紧凑可读的画像摘要；能力按原列表顺序连接，不包含完整合同内容。"""
        caps = ", ".join(self.required_capabilities) or "(none)"
        return f"[{self.domain_hint}/{self.task_type_hint}] {self.primary_goal} | caps={caps}"



__all__ = ["CapabilityCandidate", "ComplexityAssessment", "TaskSemanticProfile"]
