"""认知规划引擎。

“静态优选，动态补位”混合策略的总编排：

  意图解析 → 模板匹配
     ├─ 命中(≥阈值) → 复用模板，线性升格为 ACG（静态，零规划开销）
     └─ 未命中     → 认知路由 → ACG 构建器（动态生成 ACG）

产物统一为 ACGBlueprint，交付执行器。规划决策（走静态还是动态、命中哪个
模板、能力如何绑定）记录在 PlanResult，供审计与前端展示。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import random
import secrets
from time import monotonic
from typing import Any, Callable, Dict, Literal, Mapping, Optional, Sequence

from contracts.planning import (
    TaskImplementationBinding,
    TaskPlan,
    TaskPlanPatch,
)
from service.agents import AgentRegistry
from support.acg.models import ACGBlueprint, CapabilityCandidate, ControlNode
from .acg_builder import ACGBuilder
from .semantic_planner import SemanticPlanner
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
from .topology import EdgeOrigin, validate_task_plan_for_execution
from components.mission_manager.store import WorkflowRegistry


CapabilityProfile = Literal["auto", "standard", "full"]


def normalize_capability_profile(value: object | None) -> CapabilityProfile:
    normalized = str(value or "auto").strip().lower()
    if normalized not in {"auto", "standard", "full"}:
        raise ValueError("capabilityProfile must be one of: auto, standard, full")
    return normalized  # type: ignore[return-value]


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
    task_bindings: tuple[TaskImplementationBinding, ...]
    strategy: str  # "static_template" | "dynamic_generation"
    template_id: Optional[str] = None
    template_score: float = 0.0
    thinking_mode: Optional[str] = None
    reasoning_effort: Optional[str] = None
    requested_capability_profile: CapabilityProfile = "auto"
    effective_capability_profile: Literal["standard", "full"] = "standard"
    capability_profile_reason: str = "simple_or_medium_auto"
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
    prompt_audit: list[Dict[str, Any]] = field(default_factory=list)
    topology_audit: Dict[str, Any] = field(default_factory=dict)

    def to_decision(self) -> Dict[str, Any]:
        """将规划结果转换为审计/前端消费的别名键字典，不修改蓝图或画像。"""
        return {
            "strategy": self.strategy,
            "templateId": self.template_id,
            "templateScore": self.template_score,
            "thinkingMode": self.thinking_mode,
            "reasoningEffort": self.reasoning_effort,
            "requestedCapabilityProfile": self.requested_capability_profile,
            "effectiveCapabilityProfile": self.effective_capability_profile,
            "capabilityProfileReason": self.capability_profile_reason,
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
            "promptAudit": self.prompt_audit,
            "topologyAudit": self.topology_audit,
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
        self.semantic_planner = SemanticPlanner(self.capability_catalog, intent_llm)
        self.variant_generator = PlanningVariantGenerator(
            capability_catalog=self.capability_catalog,
            cognitive_router=self.cognitive_router,
        )

    def plan(
        self,
        *,
        mission_id: str,
        intent: str,
        domain: str = "general",
        task_type: str = "general",
        force_dynamic: bool = False,
        thinking_mode: str | None = None,
        reasoning_effort: str | None = None,
        deterministic_intent: bool = False,
        planning_diversity: str = "stable",
        planning_seed: int | None = None,
        capability_catalog_revision: str | None = None,
        required_capabilities: Sequence[str] | None = None,
        task_input: Dict[str, Any] | None = None,
        existing_semantic_tasks: Sequence[Mapping[str, Any]] = (),
        capability_profile: str = "auto",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        run_id: str | None = None,
    ) -> PlanResult:
        """为任务选择模板或动态生成 ACG。

        稳定多样性优先匹配模板；否则绑定能力、生成变体并在可执行候选中选取。种子控制
        随机选择的复现性，目录或绑定不满足约束时抛出 ``ACGPlanningError``；不持久化结果。
        """
        diversity = normalize_planning_diversity(planning_diversity)
        requested_profile = normalize_capability_profile(capability_profile)
        planning_deadline = monotonic() + self._planning_total_timeout_seconds()
        self.intent_parser.progress_callback = progress_callback
        self.semantic_planner.task_decomposer.progress_callback = progress_callback
        if progress_callback:
            progress_callback({"stage": "planning", "status": "started"})
        profile = self.intent_parser.parse(
            intent=intent,
            domain=domain,
            task_type=task_type,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
            use_llm=not deterministic_intent,
            task_input=task_input,
            declared_capabilities=list(required_capabilities or ()),
            planning_deadline=planning_deadline,
            run_id=run_id,
        )
        auto_full = profile.estimated_complexity.value in {"complex", "extreme"}
        if progress_callback:
            # 解析结果产生后的确定性事实；计数来自真实 profile，禁止由模型生成。
            progress_callback({
                "stage": "intent_profile",
                "status": "profile_resolved",
                "constraintCount": len(profile.key_constraints),
                "requiredCapabilityCount": len(profile.required_capabilities),
                "expectedArtifactCount": len(profile.expected_artifacts),
            })
        effective_profile: Literal["standard", "full"] = (
            "full" if requested_profile == "full" or (requested_profile == "auto" and auto_full)
            else "standard"
        )
        profile_reason = (
            "explicit_full" if requested_profile == "full"
            else "explicit_standard" if requested_profile == "standard"
            else "complexity_auto_full" if auto_full
            else "simple_or_medium_auto"
        )
        if effective_profile == "full" and diversity != "exploratory":
            diversity = "exploratory"
        resolved_seed = planning_seed
        if diversity != "stable" and resolved_seed is None:
            resolved_seed = secrets.randbits(53)
        planning_reasoning_effort = "max" if effective_profile == "full" else reasoning_effort
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
                task_plan = self.semantic_planner.plan_template(
                    mission_id=mission_id,
                    workflow=match.workflow,
                    strategy="static_template",
                )
                built = self.acg_builder.build_template(
                    workflow=match.workflow,
                    task_plan=task_plan,
                )
                built.blueprint.metadata["topologyAudit"] = dict(
                    self.semantic_planner.last_topology_audit
                )
                if progress_callback:
                    progress_callback({
                        "stage": "planning",
                        "status": "plan_parsed",
                        "taskCount": len(task_plan.nodes),
                        "dependencyCount": len(task_plan.relations),
                    })
                blueprint = built.blueprint
                blueprint.objective = profile.primary_goal or blueprint.objective
                return PlanResult(
                    blueprint=blueprint,
                    profile=profile,
                    task_plan=task_plan,
                    task_bindings=built.bindings,
                    strategy="static_template",
                    template_id=match.workflow.workflow_id,
                    template_score=match.score,
                    thinking_mode=thinking_mode,
                    reasoning_effort=reasoning_effort,
                    requested_capability_profile=requested_profile,
                    effective_capability_profile=effective_profile,
                    capability_profile_reason=profile_reason,
                    planning_diversity=diversity,
                    planning_seed=resolved_seed,
                    capability_catalog_revision=capability_catalog_revision,
                    selected_capabilities=list(profile.required_capabilities),
                    prompt_audit=[dict(self.intent_parser.last_audit)],
                    topology_audit=dict(self.semantic_planner.last_topology_audit),
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
        task_plan = self.semantic_planner.plan_profile(
            mission_id=mission_id,
            profile=profile,
            strategy="dynamic_generation",
            task_input={
                **dict(task_input or {}),
                "_effectiveCapabilityProfile": effective_profile,
            },
            reasoning_effort=planning_reasoning_effort,
            use_llm=not deterministic_intent,
            existing_semantic_tasks=existing_semantic_tasks,
            planning_deadline=planning_deadline,
            run_id=run_id,
        )
        task_plan = task_plan.model_copy(update={
            "metadata": {
                **task_plan.metadata,
                "requestedCapabilityProfile": requested_profile,
                "effectiveCapabilityProfile": effective_profile,
                "capabilityProfileReason": profile_reason,
            }
        })
        if progress_callback:
            progress_callback({
                "stage": "planning",
                "status": "plan_parsed",
                "taskCount": len(task_plan.nodes),
                "dependencyCount": len(task_plan.relations),
            })
        variant_set = self.variant_generator.generate(
            profile=profile,
            domain=domain,
            diversity=diversity,
            seed=resolved_seed,
        )
        valid: list[tuple[Any, ACGBlueprint]] = []
        rejected: list[str] = []
        for variant in variant_set.variants:
            if effective_profile == "full" and not variant.enable_parallel_controls:
                variant = replace(
                    variant,
                    enable_parallel_controls=True,
                    selection_reasons=(*variant.selection_reasons, "full profile requires explicit parallel controls"),
                )
            if variant.network.unresolved_capabilities or variant.network.over_budget:
                rejected.append(f"{variant.variant_id}: unresolved capability or entropy budget")
                continue
            try:
                candidate = self.acg_builder.build(
                    mission_id=mission_id,
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
            scored = [
                (self._score_candidate(task_plan, candidate), variant, candidate)
                for variant, candidate in valid
            ]
            best_score = max(item[0] for item in scored)
            tied = [item for item in scored if item[0] == best_score]
            selection_random = random.Random(resolved_seed)
            _, selected_variant, blueprint = (
                tied[selection_random.randrange(len(tied))] if len(tied) > 1 else tied[0]
            )
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
                mission_id=mission_id,
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
                "selectedVariantScore": self._score_candidate(task_plan, blueprint),
                "requestedCapabilityProfile": requested_profile,
                "effectiveCapabilityProfile": effective_profile,
                "capabilityProfileReason": profile_reason,
                "promptAudit": [
                    dict(self.intent_parser.last_audit),
                    dict(self.semantic_planner.task_decomposer.last_audit),
                ],
                "topologyAudit": dict(
                    self.semantic_planner.task_decomposer.last_audit.get("topologyCompilation") or {}
                ),
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
        notes.append(
            f"selected {selected_variant.variant_id} by deterministic quality score "
            f"{self._score_candidate(task_plan, blueprint):.3f}"
        )
        notes.extend(rejected)
        if task_plan.metadata.get("degraded"):
            notes.append(str(task_plan.metadata.get("degradationReason") or "v2 decomposition used explicit degraded plan"))
        built = self.acg_builder.finalize(
            task_plan=task_plan,
            blueprint=blueprint,
        )
        return PlanResult(
            blueprint=blueprint,
            profile=profile,
            task_plan=task_plan,
            task_bindings=built.bindings,
            strategy="dynamic_generation",
            template_score=match.score if match else 0.0,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
            requested_capability_profile=requested_profile,
            effective_capability_profile=effective_profile,
            capability_profile_reason=profile_reason,
            planning_diversity=diversity,
            planning_seed=resolved_seed,
            capability_catalog_revision=capability_catalog_revision,
            candidate_count=len(valid),
            selected_variant_id=selected_variant.variant_id,
            selected_capabilities=list(profile.required_capabilities),
            selected_bindings=[
                {
                    "planNodeKey": node.key,
                    "capabilityId": node.capability_requirements[0],
                    "agentName": next(
                        binding.agent_name
                        for binding in selected_variant.network.bindings
                        if binding.capability == node.capability_requirements[0]
                    ),
                }
                for node in task_plan.nodes
            ],
            selection_reasons=list(selected_variant.selection_reasons),
            stochastic_fallback=stochastic_fallback,
            notes=notes,
            prompt_audit=[
                dict(self.intent_parser.last_audit),
                dict(self.semantic_planner.task_decomposer.last_audit),
            ],
            topology_audit=dict(
                self.semantic_planner.task_decomposer.last_audit.get("topologyCompilation") or {}
            ),
        )

    @staticmethod
    def _planning_total_timeout_seconds() -> float:
        # Import lazily so planner tests can patch the environment before the
        # budget is created and so the engine has one deadline per Plan call.
        from .complexity import PLANNING_TOTAL_TIMEOUT_SECONDS

        return PLANNING_TOTAL_TIMEOUT_SECONDS

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

    @staticmethod
    def _score_candidate(task_plan: TaskPlan, blueprint: ACGBlueprint) -> float:
        """Score only auditable graph properties; the seed breaks exact ties."""
        steps = blueprint.step_nodes()
        expected_refs = {
            ref
            for node in task_plan.nodes
            for ref in node.source_refs
            if str(ref).startswith(("constraint:", "artifact:"))
        }
        covered_refs = {
            ref
            for step in steps
            for ref in step.source_refs
            if str(ref).startswith(("constraint:", "artifact:"))
        }
        coverage = 1.0 if not expected_refs else len(expected_refs & covered_refs) / len(expected_refs)
        controls = [node for node in blueprint.nodes if isinstance(node, ControlNode)]
        verification = any(
            step.capability in {"verification", "industrial_acceptance_validation"}
            for step in steps
        )
        graph_quality = 1.0 if verification else 0.6
        evidence = sum(bool(step.metadata.get("requiresEvidence")) for step in steps) / max(1, len(steps))
        control_types = {str(node.control_type.value) for node in controls}
        control_quality = min(1.0, len(control_types & {"parallel", "consensus", "loop"}) / 3)
        binding_quality = sum(
            min(1.0, max(0.0, float(step.metadata.get("routerScore") or 0)) / 4)
            for step in steps
        ) / max(1, len(steps))
        return round(
            coverage * 0.35
            + graph_quality * 0.25
            + evidence * 0.15
            + control_quality * 0.15
            + binding_quality * 0.10,
            6,
        )


# Facade 和引擎共用一个实现，避免迁移期间分裂规划入口。
PlannerService = PlanningEngine


def apply_task_plan_patch(
    current: TaskPlan,
    patch: TaskPlanPatch,
    capability_catalog: CapabilityCatalog | None = None,
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
    catalog_source: str | None = None,
) -> TaskPlan:
    """Planner-owned immutable semantic plan revision."""
    if current.mission_id != patch.mission_id:
        raise ACGPlanningError("TaskPlanPatch belongs to another Mission")
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
    catalog = capability_catalog or build_default_capability_catalog()
    return validate_task_plan_for_execution(
        capability_catalog=catalog,
        mission_id=current.mission_id,
        plan_version=patch.plan_version,
        nodes=tuple(nodes.values()),
        relations=relations,
        control_policies=current.control_policies,
        relation_origin=EdgeOrigin.PLAN_PATCH,
        producer_kind="patch",
        catalog_source=(catalog_source or (
            "injected" if capability_catalog is not None else "default_compatibility"
        )),
        audit_sink=audit_sink,
        metadata={**current.metadata, **patch.metadata},
    )


__all__ = [
    "ACGPlanningError",
    "PlanResult",
    "PlannerService",
    "PlanningEngine",
    "apply_task_plan_patch",
]
