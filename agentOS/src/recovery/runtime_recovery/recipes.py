"""提供带版本、领域无关且确定性的恢复配方。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from recovery.runtime_recovery.events import RuntimeEventType
from recovery.runtime_recovery.models import SubgraphInsertionMode


class RecoveryNodeTemplate(BaseModel):
    """描述恢复子图中单个节点的能力、输入输出与执行约束模板。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    logical_name: str = Field(alias="logicalName")
    name: str
    capability: str
    input_spec: dict[str, Any] = Field(default_factory=dict, alias="inputSpec")
    output_spec: dict[str, Any] = Field(default_factory=dict, alias="outputSpec")
    retry_limit: int = Field(default=0, alias="retryLimit", ge=0)
    timeout: int = Field(default=0, ge=0)
    priority: int = 0


class RecoveryRecipe(BaseModel):
    """用于目标节点前插入子图的有界能力型恢复配方。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    recipe_id: str = Field(alias="recipeId")
    version: str
    trigger_event_types: list[RuntimeEventType] = Field(alias="triggerEventTypes")
    trigger_reason_codes: list[str] = Field(default_factory=list, alias="triggerReasonCodes")
    required_capabilities: list[str] = Field(alias="requiredCapabilities")
    insertion_mode: SubgraphInsertionMode = Field(
        default=SubgraphInsertionMode.INSERT_BEFORE_TARGET,
        alias="insertionMode",
    )
    max_applications_per_run: int = Field(default=1, alias="maxApplicationsPerRun", ge=1)
    node_templates: list[RecoveryNodeTemplate] = Field(alias="nodeTemplates", min_length=1)
    edge_templates: list[dict[str, str]] = Field(default_factory=list, alias="edgeTemplates")
    input_mappings: dict[str, Any] = Field(default_factory=dict, alias="inputMappings")
    output_mappings: dict[str, Any] = Field(default_factory=dict, alias="outputMappings")

    def matches(self, event_type: RuntimeEventType, reason_code: str) -> bool:
        """判断事件类型和原因码是否命中配方触发器，支持 ``*`` 原因码。"""
        reason_codes = {code.upper() for code in self.trigger_reason_codes}
        return event_type in self.trigger_event_types and (
            "*" in reason_codes or reason_code.upper() in reason_codes
        )


class RecoveryRecipeRegistry:
    """注入 ``WorkflowRuntime`` 的内存配方注册表，不包含领域路由逻辑。"""

    def __init__(self, recipes: list[RecoveryRecipe] | None = None) -> None:
        self._recipes: dict[str, RecoveryRecipe] = {}
        for recipe in recipes or []:
            self.register(recipe)

    def register(self, recipe: RecoveryRecipe) -> None:
        """深拷贝登记唯一配方版本；重复键抛出 ``ValueError`` 防止静默覆盖。"""
        key = self._key(recipe.recipe_id, recipe.version)
        if key in self._recipes:
            raise ValueError(f"recovery recipe already registered: {key}")
        self._recipes[key] = recipe.model_copy(deep=True)

    def get(self, recipe_id: str, version: str | None = None) -> RecoveryRecipe:
        """返回指定或最高版本配方副本；没有匹配项时抛出 ``KeyError``。"""
        matches = [
            recipe for recipe in self._recipes.values()
            if recipe.recipe_id == recipe_id and (version is None or recipe.version == version)
        ]
        if not matches:
            raise KeyError(f"recovery recipe not found: {recipe_id}@{version or 'latest'}")
        return sorted(matches, key=lambda item: item.version)[-1].model_copy(deep=True)

    def match(self, event_type: RuntimeEventType, reason_code: str) -> RecoveryRecipe | None:
        """返回稳定排序后的首个匹配配方副本；无匹配时返回 ``None``。"""
        matches = [
            recipe for recipe in self._recipes.values()
            if recipe.matches(event_type, reason_code)
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: (item.recipe_id, item.version))[0].model_copy(deep=True)

    @classmethod
    def with_defaults(cls) -> "RecoveryRecipeRegistry":
        """构造内置证据与合同修复配方注册表，供默认运行时使用。"""
        return cls(
            [
                RecoveryRecipe(
                    recipeId="evidence_retrieval_and_validation.v1",
                    version="1",
                    triggerEventTypes=[RuntimeEventType.EVIDENCE_MISSING],
                    triggerReasonCodes=["EVIDENCE_MISSING"],
                    requiredCapabilities=["evidence_retrieval", "evidence_validation"],
                    nodeTemplates=[
                        RecoveryNodeTemplate(
                            logicalName="evidence_retrieval",
                            name="Evidence retrieval",
                            capability="evidence_retrieval",
                        ),
                        RecoveryNodeTemplate(
                            logicalName="evidence_validation",
                            name="Evidence validation",
                            capability="evidence_validation",
                        ),
                    ],
                ),
                RecoveryRecipe(
                    recipeId="contract_repair.v1",
                    version="1",
                    triggerEventTypes=[
                        RuntimeEventType.INPUT_CONTRACT_VIOLATION,
                        RuntimeEventType.OUTPUT_CONTRACT_VIOLATION,
                    ],
                    triggerReasonCodes=["*"],
                    requiredCapabilities=["contract_adapter"],
                    nodeTemplates=[
                        RecoveryNodeTemplate(
                            logicalName="contract_adapter",
                            name="Contract adapter",
                            capability="contract_adapter",
                        )
                    ],
                ),
            ]
        )

    @staticmethod
    def _key(recipe_id: str, version: str) -> str:
        return f"{recipe_id}@{version}"


__all__ = [
    "RecoveryNodeTemplate",
    "RecoveryRecipe",
    "RecoveryRecipeRegistry",
]
