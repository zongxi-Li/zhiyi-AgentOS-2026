"""Domain-neutral planning capability contracts and catalog."""

from __future__ import annotations

from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field
from contracts.request_budget import ModelRequestBudget, SupplementalReadBudget
from contracts.resource import ModelDemand

PlanningRiskLevel = Literal["normal", "elevated", "high", "critical"]
_RISK_LEVEL_ORDER: tuple[PlanningRiskLevel, ...] = (
    "normal",
    "elevated",
    "high",
    "critical",
)


class CapabilityPromptProfile(BaseModel):
    """Versioned, domain-neutral instructions used to select and execute a capability."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    profile_id: str = Field(default="generic", alias="profileId")
    prompt_profile_version: str = Field(default="capability-profile.v1", alias="promptProfileVersion")
    purpose: str = ""
    when_to_use: list[str] = Field(default_factory=list, alias="whenToUse")
    when_not_to_use: list[str] = Field(default_factory=list, alias="whenNotToUse")
    decomposition_hints: list[str] = Field(default_factory=list, alias="decompositionHints")
    execution_principles: list[str] = Field(default_factory=list, alias="executionPrinciples")
    quality_criteria: list[str] = Field(default_factory=list, alias="qualityCriteria")
    verification_questions: list[str] = Field(default_factory=list, alias="verificationQuestions")
    required_tools: list[str] = Field(default_factory=list, alias="requiredTools")
    evidence_policy: str = Field(default="Use only supplied or tool-returned evidence.", alias="evidencePolicy")


class ContextConsumptionPolicy(BaseModel):
    """Registered consumer policy, frozen when a new execution package is built."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    version: Literal["consumer-fields.v1"] = "consumer-fields.v1"
    match_input_contract: bool = Field(default=True, alias="matchInputContract")
    prefetch_fields: dict[str, list[str]] = Field(default_factory=dict, alias="prefetchFields")
    memory_token_budget: int = Field(default=2048, alias="memoryTokenBudget", ge=0)
    request_budget: ModelRequestBudget | None = Field(default=None, alias="requestBudget")
    supplemental_read_budget: SupplementalReadBudget | None = Field(default=None, alias="supplementalReadBudget")


class PlanningCapabilityDescriptor(BaseModel):
    """解析、路由和 ACG 构造共享的稳定能力描述。

    标识、别名、依赖和领域提示决定可发现性；输入/输出合同与产物、证据、内存、审核及风险
    标志决定图构造边界。插件来源字段将贡献锁定到版本化安装包。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    capability_id: str = Field(alias="capabilityId")
    display_name: str = Field(alias="displayName")
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    prompt_profile: CapabilityPromptProfile = Field(
        default_factory=CapabilityPromptProfile,
        alias="promptProfile",
    )
    planning_stage: str = Field(default="analysis", alias="planningStage")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    optional_dependencies: list[str] = Field(default_factory=list, alias="optionalDependencies")
    input_contract: dict = Field(default_factory=dict, alias="inputContract")
    output_contract: dict = Field(default_factory=dict, alias="outputContract")
    context_policy: ContextConsumptionPolicy | None = Field(default=None, alias="contextPolicy")
    model_demand: ModelDemand | None = Field(default=None, alias="modelDemand")
    produces_artifact: bool = Field(default=False, alias="producesArtifact")
    requires_evidence: bool = Field(default=False, alias="requiresEvidence")
    writes_memory: bool = Field(default=False, alias="writesMemory")
    requires_review: bool = Field(default=False, alias="requiresReview")
    risk_level_hint: PlanningRiskLevel = Field(default="normal", alias="riskLevelHint")
    domain_hints: list[str] = Field(default_factory=list, alias="domainHints")
    priority: int = 100
    source: Literal["native", "plugin"] = "native"
    plugin_id: str | None = Field(default=None, alias="pluginId")
    plugin_version: str | None = Field(default=None, alias="pluginVersion")
    contribution_id: str | None = Field(default=None, alias="contributionId")




def highest_planning_risk_level(values: Iterable[str]) -> PlanningRiskLevel:
    """返回输入中已识别声明式规划风险的最高级别；未知值忽略，空集合回退 ``normal``。"""

    ranks = {value: index for index, value in enumerate(_RISK_LEVEL_ORDER)}
    normalized = [str(value or "").strip().lower() for value in values]
    return max(
        (value for value in normalized if value in ranks),
        key=ranks.__getitem__,
        default="normal",
    )


__all__ = [
    "CapabilityPromptProfile", "PlanningCapabilityDescriptor",
    "PlanningRiskLevel", "highest_planning_risk_level",
]
