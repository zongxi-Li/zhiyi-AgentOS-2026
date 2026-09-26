"""Domain-neutral planning capability contracts and catalog."""

from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class CapabilityCatalog:
    """经校验且顺序确定的可执行规划能力注册表。"""

    def __init__(self, descriptors: Iterable[PlanningCapabilityDescriptor] = ()) -> None:
        self._descriptors: OrderedDict[str, PlanningCapabilityDescriptor] = OrderedDict()
        self._aliases: dict[str, str] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: PlanningCapabilityDescriptor) -> None:
        """注册一个能力描述符并规范化标识与别名。

        保持插入顺序；重复能力或与其他能力冲突的别名会抛出 ``ValueError``，失败前不写入。
        """
        capability_id = self._normalize(descriptor.capability_id)
        if not capability_id:
            raise ValueError("capabilityId is required")
        if capability_id in self._descriptors:
            raise ValueError(f"duplicate capabilityId: {descriptor.capability_id}")

        normalized = descriptor.model_copy(
            update={
                "capability_id": capability_id,
                "depends_on": [self._normalize(item) for item in descriptor.depends_on],
                "optional_dependencies": [
                    self._normalize(item) for item in descriptor.optional_dependencies
                ],
                "domain_hints": [self._normalize(item) for item in descriptor.domain_hints],
            }
        )
        alias_values = [capability_id, *normalized.aliases]
        for value in alias_values:
            alias = self._normalize(value)
            existing = self._aliases.get(alias)
            if existing is not None and existing != capability_id:
                raise ValueError(f"duplicate capability alias: {value}")

        self._descriptors[capability_id] = normalized
        for value in alias_values:
            self._aliases[self._normalize(value)] = capability_id

    def get(self, capability_id: str) -> PlanningCapabilityDescriptor:
        """按规范化能力标识获取描述符；未注册时抛出 ``KeyError``。"""
        normalized = self._normalize(capability_id)
        try:
            return self._descriptors[normalized]
        except KeyError as exc:
            raise KeyError(f"planning capability not registered: {capability_id}") from exc

    def resolve(self, value: str) -> PlanningCapabilityDescriptor:
        """按能力标识或别名解析描述符；别名冲突已在注册阶段禁止。"""
        normalized = self._normalize(value)
        capability_id = self._aliases.get(normalized)
        if capability_id is None:
            raise KeyError(f"planning capability not registered: {value}")
        return self._descriptors[capability_id]

    def available(self, domain_hint: str | None = None) -> tuple[PlanningCapabilityDescriptor, ...]:
        """返回领域可见描述符的不可变序列，按 ``(priority, capability_id)`` 稳定排序。"""
        domain = self._normalize(domain_hint or "")
        descriptors = [
            descriptor
            for descriptor in self._descriptors.values()
            if not domain
            or not descriptor.domain_hints
            or domain in descriptor.domain_hints
            or "general" in descriptor.domain_hints
        ]
        return tuple(sorted(descriptors, key=lambda item: (item.priority, item.capability_id)))

    def scoped(self, capability_ids: Iterable[str]) -> "CapabilityCatalog":
        """构建隔离能力目录视图，不修改全局目录；返回项深拷贝并重新校验依赖。"""

        allowed = {self._normalize(item) for item in capability_ids}
        scoped = CapabilityCatalog(
            descriptor.model_copy(deep=True)
            for capability_id, descriptor in self._descriptors.items()
            if capability_id in allowed
        )
        scoped.validate()
        return scoped

    def validate(self) -> None:
        """验证依赖均已注册且不存在环；深度优先遍历，复杂度 ``O(V+E)``。"""
        for descriptor in self._descriptors.values():
            for dependency in [*descriptor.depends_on, *descriptor.optional_dependencies]:
                if dependency not in self._descriptors:
                    raise ValueError(
                        f"capability {descriptor.capability_id} has dangling dependency: {dependency}"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(capability_id: str) -> None:
            if capability_id in visiting:
                raise ValueError(f"capability dependency cycle detected at: {capability_id}")
            if capability_id in visited:
                return
            visiting.add(capability_id)
            descriptor = self._descriptors[capability_id]
            for dependency in [*descriptor.depends_on, *descriptor.optional_dependencies]:
                visit(dependency)
            visiting.remove(capability_id)
            visited.add(capability_id)

        for capability_id in self._descriptors:
            visit(capability_id)

    def expand_dependencies(self, capability_ids: Iterable[str]) -> list[str]:
        """展开必需依赖并返回依赖先于依赖者的去重顺序，复杂度 ``O(V+E)``。"""
        selected: list[str] = []
        visited: set[str] = set()

        def include(value: str) -> None:
            descriptor = self.resolve(value)
            if descriptor.capability_id in visited:
                return
            for dependency in descriptor.depends_on:
                include(dependency)
            visited.add(descriptor.capability_id)
            selected.append(descriptor.capability_id)

        for capability_id in capability_ids:
            include(capability_id)
        return selected

    @staticmethod
    def _normalize(value: str) -> str:
        return (value or "").strip().lower()


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
    "CapabilityCatalog", "CapabilityPromptProfile", "PlanningCapabilityDescriptor",
    "PlanningRiskLevel", "highest_planning_risk_level",
]
