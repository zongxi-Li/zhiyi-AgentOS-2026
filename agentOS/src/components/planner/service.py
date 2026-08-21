"""认知规划引擎。

“静态优选，动态补位”混合策略的总编排：

  意图解析 → 模板匹配
     ├─ 命中(≥阈值) → 复用模板，线性升格为 ACG（静态，零规划开销）
     └─ 未命中     → 认知路由 → ACG 构建器（动态生成 ACG）

产物统一为 ACGBlueprint，交付执行器。规划决策（走静态还是动态、命中哪个
模板、能力如何绑定）记录在 PlanResult，供审计与前端展示。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
import secrets
from typing import Any, Dict, Optional, Sequence

from contracts.planning import (
    TaskNodeImplementationBinding,
    TaskPlan,
    TaskPlanNode,
    TaskPlanRelation,
    TaskPlanPatch,
    TaskNodeRelationType,
)
from service.agents import AgentRegistry
from support.acg.models import ACGBlueprint, CapabilityCandidate, promote_workflow_to_acg
from .acg_builder import ACGBuilder
from support.acg.models import CapabilityCatalog
from .cognitive_router import CognitiveRouter
from support.acg.models import build_default_capability_catalog
from .intent_analyzer import IntentLLM, IntentParser
from support.acg.models import TaskSemanticProfile
from .template_matcher import TemplateMatcher
from .algorithms import (
    PLANNER_ALGORITHM_VERSION,
    PlanningDiversity,
    PlanningVariantGenerator,
    normalize_planning_diversity,
)
from components.task_manager.store import WorkflowRegistry


class ACGPlanningError(ValueError):
    """当前能力可见性或熵预算下无法产出可执行 ACG 时抛出的规划错误。"""


@dataclass
class PlanResult:
    """一次规划的不可持久化结果。

    蓝图与画像是主产物，模板/变体、随机种子、能力目录版本和选择理由记录决策可复现
    上下文；``candidate_count`` 至少表示最终参与选择的候选数。
    """
    blueprint: ACGBlueprint
    profile: TaskSemanticProfile
    task_plan: TaskPlan
    task_node_bindings: tuple[TaskNodeImplementationBinding, ...]
    strategy: str  # "static_template" | "dynamic_generation"
    template_id: Optional[str] = None
    template_score: float = 0.0
    thinking_mode: Optional[str] = None
    planning_diversity: PlanningDiversity = "stable"
    planning_seed: Optional[int] = None
    planner_algorithm_version: str = PLANNER_ALGORITHM_VERSION
    capability_catalog_revision: Optional[str] = None
    candidate_count: int = 1
    selected_variant_id: Optional[str] = None
    selected_capabilities: list[str] = field(default_factory=list)
    selected_bindings: list[Dict[str, str]] = field(default_factory=list)
    selection_reasons: list[str] = field(default_factory=list)
    stochastic_fallback: bool = False
    notes: list[str] = field(default_factory=list)

    def to_decision(self) -> Dict[str, Any]:
        """将规划结果转换为审计/前端消费的别名键字典，不修改蓝图或画像。"""
        return {
            "strategy": self.strategy,
            "templateId": self.template_id,
            "templateScore": self.template_score,
            "thinkingMode": self.thinking_mode,
            "planningDiversity": self.planning_diversity,
            "planningSeed": self.planning_seed,
            "plannerAlgorithmVersion": self.planner_algorithm_version,
            "capabilityCatalogRevision": self.capability_catalog_revision,
            "candidateCount": self.candidate_count,
            "selectedVariantId": self.selected_variant_id,
            "selectedCapabilities": self.selected_capabilities,
            "selectedBindings": self.selected_bindings,
            "selectionReasons": self.selection_reasons,
            "stochasticFallback": self.stochastic_fallback,
            "profile": self.profile.model_dump(by_alias=True),
            "graphId": self.blueprint.graph_id,
            "taskPlanVersion": self.task_plan.plan_version,
            "taskNodeCount": len(self.task_plan.nodes),
            "nodeCount": self.blueprint.node_count,
            "edgeCount": self.blueprint.edge_count,
            "notes": self.notes,
        }


class PlanningEngine:
    """认知规划引擎。"""

    def __init__(
        self,
        *,
        workflow_registry: WorkflowRegistry,
        agent_registry: AgentRegistry,
        capability_catalog: CapabilityCatalog | None = None,
        intent_llm: Optional[IntentLLM] = None,
        template_threshold: float = 0.85,
    ):
        self.capability_catalog = capability_catalog or build_default_capability_catalog()
        self.intent_parser = IntentParser(intent_llm, self.capability_catalog)
        self.template_matcher = TemplateMatcher(workflow_registry, threshold=template_threshold)
        self.cognitive_router = CognitiveRouter(agent_registry, self.capability_catalog)
        self.acg_builder = ACGBuilder(self.capability_catalog)
        self.variant_generator = PlanningVariantGenerator(
            capability_catalog=self.capability_catalog,
            cognitive_router=self.cognitive_router,
        )

    def plan(
        self,
        *,
        task_id: str,
        intent: str,
        domain: str = "general",
        task_type: str = "general",
        force_dynamic: bool = False,
        thinking_mode: str | None = None,
        deterministic_intent: bool = False,
        planning_diversity: str = "stable",
        planning_seed: int | None = None,
        capability_catalog_revision: str | None = None,
        required_capabilities: Sequence[str] | None = None,
    ) -> PlanResult:
        """为任务选择模板或动态生成 ACG。

        稳定多样性优先匹配模板；否则绑定能力、生成变体并在可执行候选中选取。种子控制
        随机选择的复现性，目录或绑定不满足约束时抛出 ``ACGPlanningError``；不持久化结果。
        """
        diversity = normalize_planning_diversity(planning_diversity)
        resolved_seed = planning_seed
        if diversity != "stable" and resolved_seed is None:
            resolved_seed = secrets.randbits(53)
        profile = self.intent_parser.parse(
            intent=intent,
            domain=domain,
            task_type=task_type,
            thinking_mode=thinking_mode,
            use_llm=not deterministic_intent,
        )
        if required_capabilities:
            selected = self.capability_catalog.expand_dependencies(required_capabilities)
            existing = {
                item.capability_id: item for item in profile.capability_candidates
            }
            profile.required_capabilities = selected
            profile.capability_candidates = [
                existing.get(capability_id)
                or CapabilityCandidate(
                    capabilityId=capability_id,
                    score=1.0,
                    matchedTerms=[],
                    source="workflow_template",
                )
                for capability_id in selected
            ]

        match = None
        if not force_dynamic and diversity == "stable":
            # 静态优选
            match = self.template_matcher.match(profile)
            if self.template_matcher.is_hit(match):
                task_plan = build_task_plan_for_workflow(
                    task_id=task_id,
                    workflow=match.workflow,
                    strategy="static_template",
                )
                blueprint = promote_workflow_to_acg(match.workflow, task_id=task_id)
                blueprint.objective = profile.primary_goal or blueprint.objective
                task_node_bindings = build_task_node_bindings(
                    task_plan=task_plan,
                    blueprint=blueprint,
                )
                return PlanResult(
                    blueprint=blueprint,
                    profile=profile,
                    task_plan=task_plan,
                    task_node_bindings=task_node_bindings,
                    strategy="static_template",
                    template_id=match.workflow.workflow_id,
                    template_score=match.score,
                    thinking_mode=thinking_mode,
                    planning_diversity=diversity,
                    planning_seed=resolved_seed,
                    capability_catalog_revision=capability_catalog_revision,
                    selected_capabilities=list(profile.required_capabilities),
                    notes=[f"matched template by {match.matched_by}"],
                )

        # 动态补位
        stable_network = self.cognitive_router.route(profile, domain=domain)
        if stable_network.unresolved_capabilities:
            raise ACGPlanningError(
                "No registered Agent can execute capabilities: "
                + ", ".join(stable_network.unresolved_capabilities)
            )
        if stable_network.over_budget:
            raise ACGPlanningError(
                f"Estimated entropy {stable_network.estimated_entropy} exceeds budget "
                f"{stable_network.entropy_budget}"
            )
        task_plan = build_task_plan_for_capabilities(
            task_id=task_id,
            capabilities=[binding.capability for binding in stable_network.bindings],
            capability_catalog=self.capability_catalog,
            strategy="dynamic_generation",
        )
        variant_set = self.variant_generator.generate(
            profile=profile,
            domain=domain,
            diversity=diversity,
            seed=resolved_seed,
        )
        valid: list[tuple[Any, ACGBlueprint]] = []
        rejected: list[str] = []
        for variant in variant_set.variants:
            if variant.network.unresolved_capabilities or variant.network.over_budget:
                rejected.append(f"{variant.variant_id}: unresolved capability or entropy budget")
                continue
            try:
                candidate = self.acg_builder.build(
                    task_id=task_id,
                    profile=profile,
                    network=variant.network,
                    task_plan=task_plan,
                    variant=variant,
                )
                self._validate_agents(candidate, domain=domain)
            except (KeyError, ValueError) as exc:
                rejected.append(f"{variant.variant_id}: {exc}")
                continue
            valid.append((variant, candidate))

        stochastic_fallback = False
        if valid:
            selection_random = random.Random(resolved_seed)
            selected_index = selection_random.randrange(len(valid)) if len(valid) > 1 else 0
            selected_variant, blueprint = valid[selected_index]
        else:
            stochastic_fallback = diversity != "stable"
            stable_set = self.variant_generator.generate(
                profile=profile,
                domain=domain,
                diversity="stable",
                seed=None,
            )
            selected_variant = stable_set.variants[0]
            blueprint = self.acg_builder.build(
                task_id=task_id,
                profile=profile,
                network=selected_variant.network,
                task_plan=task_plan,
                variant=selected_variant,
            )
            self._validate_agents(blueprint, domain=domain)
            valid = [(selected_variant, blueprint)]

        blueprint.metadata.update(
            {
                "planningDiversity": diversity,
                "planningSeed": resolved_seed,
                "plannerAlgorithmVersion": PLANNER_ALGORITHM_VERSION,
                "capabilityCatalogRevision": capability_catalog_revision,
                "candidateCount": len(valid),
                "selectedVariantId": selected_variant.variant_id,
            }
        )
        notes = [
            "force dynamic planning; generated ACG dynamically"
            if force_dynamic
            else "stochastic planning requested; generated ACG dynamically"
            if diversity != "stable"
            else "no template hit; generated ACG dynamically"
        ]
        notes.extend(selected_variant.network.notes)
        notes.extend(rejected)
        task_node_bindings = build_task_node_bindings(
            task_plan=task_plan,
            blueprint=blueprint,
        )
        return PlanResult(
            blueprint=blueprint,
            profile=profile,
            task_plan=task_plan,
            task_node_bindings=task_node_bindings,
            strategy="dynamic_generation",
            template_score=match.score if match else 0.0,
            thinking_mode=thinking_mode,
            planning_diversity=diversity,
            planning_seed=resolved_seed,
            capability_catalog_revision=capability_catalog_revision,
            candidate_count=len(valid),
            selected_variant_id=selected_variant.variant_id,
            selected_capabilities=list(profile.required_capabilities),
            selected_bindings=[
                {
                    "capabilityId": binding.capability,
                    "agentName": binding.agent_name,
                }
                for binding in selected_variant.network.bindings
            ],
            selection_reasons=list(selected_variant.selection_reasons),
            stochastic_fallback=stochastic_fallback,
            notes=notes,
        )

    def _validate_agents(self, blueprint: ACGBlueprint, *, domain: str) -> None:
        missing: list[str] = []
        for step in blueprint.step_nodes():
            try:
                self.cognitive_router.agent_registry.resolve(
                    domain=domain,
                    agent_name=step.agent_name,
                    capability=step.capability,
                )
            except KeyError:
                missing.append(step.agent_name or step.node_id)
        if missing:
            raise ACGPlanningError("ACG references unregistered Agents: " + ", ".join(sorted(set(missing))))


# Facade 和引擎共用一个实现，避免迁移期间分裂规划入口。
PlannerService = PlanningEngine


def build_task_plan_for_capabilities(
    *,
    task_id: str,
    capabilities: Sequence[str],
    capability_catalog: CapabilityCatalog,
    strategy: str,
    plan_version: int = 1,
) -> TaskPlan:
    """Planner 在选择执行资源前，先把能力需求发布为纯语义任务计划。"""
    ordered = list(dict.fromkeys(capabilities))
    if not ordered:
        raise ACGPlanningError("Planner produced no semantic capabilities")
    selected = set(ordered)
    nodes: list[TaskPlanNode] = []
    for capability in ordered:
        descriptor = capability_catalog.get(capability)
        dependencies = [item for item in descriptor.depends_on if item in selected]
        parent_key = (
            f"capability:{dependencies[0]}" if len(dependencies) == 1 else None
        )
        nodes.append(TaskPlanNode(
            key=f"capability:{descriptor.capability_id}",
            title=descriptor.display_name,
            objective=descriptor.description or f"完成 {descriptor.display_name}",
            constraints=[
                {"type": "required_capability", "value": descriptor.capability_id},
                *(
                    [{"type": "depends_on", "values": dependencies}]
                    if dependencies
                    else []
                ),
            ],
            capabilityRequirements=(descriptor.capability_id,),
            metadata={
                "plannerStrategy": strategy,
            },
        ))
    relations = tuple(
        TaskPlanRelation(
            sourceKey=f"capability:{dependency}",
            targetKey=f"capability:{capability}",
            relationType=TaskNodeRelationType.DEPENDS_ON,
        )
        for capability in ordered
        for dependency in (
            capability_catalog.get(capability).depends_on
            if capability_catalog.get(capability).depends_on
            else ()
        )
        if dependency in selected
    )
    return TaskPlan(
        taskId=task_id,
        planVersion=plan_version,
        nodes=tuple(nodes),
        relations=relations,
        metadata={"strategy": strategy},
    )


def build_task_plan_for_workflow(
    *,
    task_id: str,
    workflow: Any,
    strategy: str,
    plan_version: int = 1,
) -> TaskPlan:
    """Build semantic planning data from a workflow definition, never a Blueprint."""
    steps = tuple(getattr(workflow, "steps", ()) or ())
    if not steps:
        raise ACGPlanningError("Planner produced no semantic workflow nodes")
    nodes: list[TaskPlanNode] = []
    relations: list[TaskPlanRelation] = []
    keys = {str(getattr(step, "step_id", "")): f"step:{getattr(step, 'step_id', '')}" for step in steps}
    for step in steps:
        step_id = str(getattr(step, "step_id", "")).strip()
        if not step_id:
            raise ACGPlanningError("Workflow step is missing a stable semantic identifier")
        capability = str(getattr(step, "capability", "") or "").strip()
        parent_id = str(getattr(step, "parent_step_id", "") or "").strip()
        next_id = str(getattr(step, "next_step_id", "") or "").strip()
        nodes.append(TaskPlanNode(
            key=keys[step_id],
            title=str(getattr(step, "name", "") or step_id),
            objective=str(
                getattr(step, "goal", "")
                or getattr(step, "description", "")
                or getattr(step, "name", "")
                or step_id
            ),
            constraints=[],
            capabilityRequirements=((capability,) if capability else ()),
            acceptanceCriteria=tuple(
                str(item) for item in (getattr(step, "acceptance_criteria", ()) or ())
            ),
            metadata={"plannerStrategy": strategy},
        ))
        if parent_id and parent_id in keys:
            relations.append(TaskPlanRelation(
                sourceKey=keys[parent_id],
                targetKey=keys[step_id],
                relationType=TaskNodeRelationType.PARENT,
            ))
        if next_id and next_id in keys:
            relations.append(TaskPlanRelation(
                sourceKey=keys[step_id],
                targetKey=keys[next_id],
                relationType=TaskNodeRelationType.DEPENDS_ON,
            ))
    return TaskPlan(
        taskId=task_id,
        planVersion=plan_version,
        nodes=tuple(nodes),
        relations=tuple(relations),
        metadata={"strategy": strategy},
    )


def build_task_node_bindings(
    *,
    task_plan: TaskPlan,
    blueprint: ACGBlueprint,
) -> tuple[TaskNodeImplementationBinding, ...]:
    """Builder 发布 TaskNode 到 WKN Step 的显式、全覆盖实现映射。"""
    plan_keys = {node.key for node in task_plan.nodes}
    steps = blueprint.step_nodes()
    if len(steps) != len(task_plan.nodes):
        raise ACGPlanningError(
            "Blueprint implementation bindings must cover the complete TaskPlan"
        )
    for step, node in zip(steps, task_plan.nodes):
        step.metadata["taskPlanKey"] = node.key
    bindings = tuple(
        TaskNodeImplementationBinding(
            planNodeKey=node.key,
            acgNodeId=step.node_id,
        )
        for step, node in zip(steps, task_plan.nodes)
    )
    binding_keys = {item.plan_node_key for item in bindings}
    if binding_keys != plan_keys or len(bindings) != len(plan_keys):
        raise ACGPlanningError(
            "Blueprint implementation bindings must cover the complete TaskPlan"
        )
    return bindings


def apply_task_plan_patch(current: TaskPlan, patch: TaskPlanPatch) -> TaskPlan:
    """Planner-owned immutable semantic plan revision."""
    if current.task_id != patch.task_id:
        raise ACGPlanningError("TaskPlanPatch belongs to another UserTask")
    if current.plan_version != patch.base_plan_version:
        raise ACGPlanningError("TaskPlanPatch basePlanVersion is stale")
    nodes = {node.key: node for node in current.nodes}
    for key in (*patch.retire_keys, *patch.replace_keys):
        nodes.pop(key, None)
    for node in patch.add_nodes:
        if node.key in nodes:
            raise ACGPlanningError(f"TaskPlanPatch duplicates active semantic key: {node.key}")
        nodes[node.key] = node
    relations = [
        relation for relation in current.relations
        if relation.source_key in nodes and relation.target_key in nodes
    ]
    relations.extend(patch.relations)
    return TaskPlan(
        taskId=current.task_id,
        planVersion=patch.plan_version,
        nodes=tuple(nodes.values()),
        relations=tuple(relations),
        metadata={**current.metadata, **patch.metadata},
    )


__all__ = [
    "ACGPlanningError",
    "PlanResult",
    "PlannerService",
    "PlanningEngine",
    "build_task_node_bindings",
    "build_task_plan_for_capabilities",
    "build_task_plan_for_workflow",
    "apply_task_plan_patch",
]
