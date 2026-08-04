"""认知规划引擎子系统。

把高维模糊的自然语言意图，转化为可执行的 ACG 蓝图。
采用“静态优选，动态补位”：优先复用验证过的模板，无命中时由认知路由 +
ACG 构建器动态生成认知协作网络。
"""

from __future__ import annotations

from core.planning.acg_builder import ACGBuilder
from core.planning.capabilities import CapabilityCatalog, PlanningCapabilityDescriptor
from core.planning.cognitive_router import (
    CapabilityBinding,
    CognitiveRouter,
    CollaborationNetwork,
)
from core.planning.engine import ACGPlanningError, PlanningEngine, PlanResult
from core.planning.intent_parser import IntentLLM, IntentParser
from core.planning.profile import CapabilityCandidate, TaskSemanticProfile
from core.planning.template_matcher import TemplateMatch, TemplateMatcher
from core.planning.variants import (
    PLANNER_ALGORITHM_VERSION,
    PlanningDiversity,
    PlanningVariant,
    PlanningVariantGenerator,
    normalize_planning_diversity,
    normalize_planning_seed,
)

__all__ = [
    "PlanningEngine",
    "ACGPlanningError",
    "PlanResult",
    "IntentParser",
    "IntentLLM",
    "TaskSemanticProfile",
    "CapabilityCandidate",
    "TemplateMatcher",
    "TemplateMatch",
    "CognitiveRouter",
    "CollaborationNetwork",
    "CapabilityBinding",
    "ACGBuilder",
    "CapabilityCatalog",
    "PlanningCapabilityDescriptor",
    "PLANNER_ALGORITHM_VERSION",
    "PlanningDiversity",
    "PlanningVariant",
    "PlanningVariantGenerator",
    "normalize_planning_diversity",
    "normalize_planning_seed",
]
