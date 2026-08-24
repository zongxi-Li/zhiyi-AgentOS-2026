"""Versioned semantic task decomposition without introducing another runtime."""

from __future__ import annotations

import json
import hashlib
import re
from collections.abc import Mapping
from typing import Any

from contracts.planning import PlannedTask, SemanticTaskRelationType, TaskPlan, TaskPlanRelation
from support.acg.models import CapabilityCatalog, TaskSemanticProfile
from .complexity import PLANNING_BUDGETS
from .intent_analyzer import IntentLLM


TASK_DECOMPOSITION_PROMPT_VERSION = "task-decomposition.v2"

_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "parentKey": {"type": ["string", "null"]},
                    "title": {"type": "string"},
                    "objective": {"type": "string"},
                    "capabilityId": {"type": "string"},
                    "constraints": {"type": "array", "items": {"type": "object"}},
                    "acceptanceCriteria": {"type": "array", "items": {"type": "string"}},
                    "sourceRefs": {"type": "array", "items": {"type": "string"}},
                    "decompositionRationale": {"type": "string"},
                    "logicalRole": {"type": "string"},
                },
                "required": ["key", "title", "objective", "capabilityId", "acceptanceCriteria"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sourceKey": {"type": "string"},
                    "targetKey": {"type": "string"},
                    "relationType": {"type": "string", "enum": ["depends_on", "parent"]},
                },
                "required": ["sourceKey", "targetKey", "relationType"],
            },
        },
        "budgetRationale": {"type": "string"},
    },
    "required": ["tasks", "relations"],
}


class TaskDecompositionError(ValueError):
    pass


class TaskDecomposer:
    def __init__(self, capability_catalog: CapabilityCatalog, llm: IntentLLM | None) -> None:
        self.capability_catalog = capability_catalog
        self.llm = llm
        self.last_audit: dict[str, Any] = {}

    def decompose(
        self,
        *,
        mission_id: str,
        profile: TaskSemanticProfile,
        strategy: str,
        task_input: Mapping[str, Any] | None,
        use_llm: bool,
    ) -> TaskPlan:
        self.last_audit = {
            "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION,
            "promptTemplateHash": hashlib.sha256(
                (TASK_DECOMPOSITION_PROMPT_VERSION + json.dumps(_SCHEMA, sort_keys=True)).encode("utf-8")
            ).hexdigest(),
            "modelVersion": str(getattr(self.llm, "model", None) or getattr(self.llm, "version", None) or "unreported"),
            "mode": "model" if use_llm and self.llm is not None else "deterministic",
        }
        if use_llm and self.llm is not None:
            prompt = self.build_prompt(profile=profile, task_input=task_input)
            first: Any = None
            try:
                first = self.llm.generate_json(
                    prompt,
                    _SCHEMA,
                    prompt_version=TASK_DECOMPOSITION_PROMPT_VERSION,
                )
                self._capture_model_audit(first)
                return self._to_plan(mission_id, profile, strategy, first)
            except Exception as first_error:
                try:
                    repaired = self.llm.generate_json(
                        prompt
                        + "\nThe previous result failed TaskPlan schema or topology validation. "
                        + "Repair it once. Preserve valid task semantics, remove every reported "
                        + "dependency cycle or reverse prerequisite path, and return the complete JSON again. "
                        + f"Validation detail: {first_error}",
                        _SCHEMA,
                        prompt_version=f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1",
                    )
                    self.last_audit["promptVersion"] = f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1"
                    self._capture_model_audit(repaired)
                    return self._to_plan(mission_id, profile, strategy, repaired)
                except Exception as repair_error:
                    self.last_audit["mode"] = "failed"
                    self.last_audit["error"] = type(repair_error).__name__
                    raise TaskDecompositionError(
                        "TASK_PLAN_VALIDATION_FAILED after one repair: "
                        f"{repair_error}"
                    ) from first_error
        return self._fallback(
            mission_id=mission_id,
            profile=profile,
            strategy=strategy,
            reason="model decomposition disabled or unavailable",
        )

    def _capture_model_audit(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        if result.get("model"):
            self.last_audit["modelVersion"] = str(result["model"])
        if result.get("provider"):
            self.last_audit["provider"] = str(result["provider"])

    def build_prompt(
        self,
        *,
        profile: TaskSemanticProfile,
        task_input: Mapping[str, Any] | None,
    ) -> str:
        level = profile.estimated_complexity
        minimum, maximum = PLANNING_BUDGETS[level]
        catalog = []
        visible_capabilities = self.capability_catalog.expand_dependencies(
            profile.required_capabilities
        )
        for capability_id in visible_capabilities:
            item = self.capability_catalog.get(capability_id)
            catalog.append({
                "capabilityId": item.capability_id,
                "purpose": item.prompt_profile.purpose,
                "whenToUse": item.prompt_profile.when_to_use,
                "whenNotToUse": item.prompt_profile.when_not_to_use,
                "decompositionHints": item.prompt_profile.decomposition_hints,
                "qualityCriteria": item.prompt_profile.quality_criteria,
                "dependsOn": list(item.depends_on),
                "optionalDependencies": list(item.optional_dependencies),
                "outputFields": list(item.output_contract.get("properties", {})),
            })
        contract = {
            "objective": (task_input or {}).get("objective") or profile.primary_goal,
            "constraints": (task_input or {}).get("constraints") or profile.key_constraints,
            "expectedArtifacts": (task_input or {}).get("expectedArtifacts") or profile.expected_artifacts,
            "verificationRequirements": profile.verification_requirements,
            "sourceRegistry": self._source_registry(profile),
            "materials": {
                key: value
                for key in ("materials", "sourceMaterials", "materialText", "contractText")
                if (value := (task_input or {}).get(key)) not in (None, "", [], {})
            },
        }
        return (
            f"Prompt version: {TASK_DECOMPOSITION_PROMPT_VERSION}\n"
            "Create an executable, acyclic, domain-neutral TaskPlan and return JSON only.\n"
            f"Complexity assessment: {profile.complexity_assessment.model_dump() if profile.complexity_assessment else level.value}.\n"
            f"Planning budget: normally {minimum}-{maximum} tasks; this is a budget, not a quota. Explain exceptions.\n"
            "Every task must have one business-specific objective, one primary capabilityId, explicit acceptance criteria, "
            "sourceRefs and a decomposition rationale. Do not write objectives such as 'Complete cost analysis'.\n"
            "The same capabilityId may be instantiated by multiple tasks when goals, alternatives or stages differ. "
            "Use depends_on relations as the authoritative execution topology and keep it acyclic.\n"
            "Capability catalog dependsOn entries are hard prerequisites that the system will enforce after generation. "
            "Never create a reverse path from a dependent task back to one of its prerequisite tasks. "
            "optionalDependencies are advisory and must not be added when they create a cycle.\n"
            "Cover every hard constraint and expected artifact; do not invent facts or domain capabilities.\n"
            "For coverage, copy stable sourceRegistry ref values into task.sourceRefs. Do not prove coverage "
            "by repeating or paraphrasing source text. Every sourceRegistry ref must be cited by a task.\n"
            f"Mission requirements: {json.dumps(contract, ensure_ascii=False, default=str)}\n"
            f"Semantic profile: {profile.model_dump_json(by_alias=True)}\n"
            f"Capability catalog: {json.dumps(catalog, ensure_ascii=False)}\n"
        )

    @staticmethod
    def _source_registry(profile: TaskSemanticProfile) -> list[dict[str, str]]:
        return [
            *(
                {"ref": f"constraint:{index}", "kind": "constraint", "text": str(value)}
                for index, value in enumerate(profile.key_constraints, start=1)
            ),
            *(
                {"ref": f"artifact:{index}", "kind": "expected_artifact", "text": str(value)}
                for index, value in enumerate(profile.expected_artifacts, start=1)
            ),
        ]

    def _to_plan(
        self,
        mission_id: str,
        profile: TaskSemanticProfile,
        strategy: str,
        raw: Any,
    ) -> TaskPlan:
        payload = raw.get("data", raw) if isinstance(raw, dict) else {}
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list) or not tasks:
            raise TaskDecompositionError("decomposer returned no tasks")
        nodes: list[PlannedTask] = []
        for item in tasks:
            capability = str(item.get("capabilityId") or "").strip().lower()
            self.capability_catalog.get(capability)
            objective = str(item.get("objective") or "").strip()
            if not objective or re.match(r"^(complete|完成)\s*\S*$", objective, re.IGNORECASE):
                raise TaskDecompositionError(f"task {item.get('key')} has no business objective")
            criteria = tuple(str(value).strip() for value in item.get("acceptanceCriteria", []) if str(value).strip())
            if not criteria:
                raise TaskDecompositionError(f"task {item.get('key')} has empty acceptance criteria")
            nodes.append(PlannedTask(
                key=str(item.get("key") or "").strip(),
                parentKey=item.get("parentKey"),
                title=str(item.get("title") or objective[:60]).strip(),
                objective=objective,
                constraints=self._normalize_constraints(item.get("constraints")),
                capabilityRequirements=(capability,),
                acceptanceCriteria=criteria,
                sourceRefs=tuple(str(value) for value in item.get("sourceRefs", []) if str(value)),
                decompositionRationale=str(item.get("decompositionRationale") or ""),
                logicalRole=str(item.get("logicalRole") or "task"),
                metadata={"plannerStrategy": strategy, "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION},
            ))
        self._complete_missing_capability_tasks(nodes, profile, strategy)
        relations = self._complete_capability_dependencies(
            nodes,
            [TaskPlanRelation.model_validate(item) for item in payload.get("relations", [])],
        )
        plan = TaskPlan(
            missionId=mission_id,
            nodes=tuple(nodes),
            relations=tuple(relations),
            metadata={
                "strategy": strategy,
                "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION,
                "complexityBand": profile.estimated_complexity.value,
                "degraded": False,
            },
        )
        self._validate_coverage(plan, profile)
        return plan

    @staticmethod
    def _normalize_constraints(value: Any) -> list[dict[str, Any]]:
        """Normalize model shorthand at the L1 contract boundary."""
        if value in (None, "", []):
            return []
        if not isinstance(value, list):
            raise TaskDecompositionError("task constraints must be an array")
        normalized: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(dict(item))
            elif isinstance(item, str) and item.strip():
                normalized.append({"type": "task_constraint", "value": item.strip()})
            else:
                raise TaskDecompositionError("task constraint must be an object or non-empty string")
        return normalized

    def _complete_missing_capability_tasks(
        self,
        nodes: list[PlannedTask],
        profile: TaskSemanticProfile,
        strategy: str,
    ) -> None:
        """Materialize catalog-required capabilities without adding domain logic."""
        present = {node.capability_requirements[0] for node in nodes}
        used_keys = {node.key for node in nodes}
        # The model may omit an indirect prerequisite even when the intent
        # profile lists only the requested leaf capabilities.  Materialize the
        # catalog's full required-dependency closure here so the subsequent
        # topology pass never has to invent a domain-specific fallback.
        required_capabilities = self.capability_catalog.expand_dependencies(
            profile.required_capabilities
        )
        for capability in required_capabilities:
            if capability in present:
                continue
            descriptor = self.capability_catalog.get(capability)
            base_key = f"required:{capability}"
            key = base_key
            suffix = 2
            while key in used_keys:
                key = f"{base_key}:{suffix}"
                suffix += 1
            nodes.append(PlannedTask(
                key=key,
                title=descriptor.display_name,
                objective=(
                    f"Apply {descriptor.display_name} as a required prerequisite for: "
                    f"{profile.primary_goal}"
                ),
                capabilityRequirements=(capability,),
                acceptanceCriteria=(
                    descriptor.prompt_profile.quality_criteria[0]
                    if descriptor.prompt_profile.quality_criteria
                    else "The capability output satisfies its declared contract.",
                ),
                decompositionRationale="Capability catalog required this missing prerequisite.",
                logicalRole="prerequisite",
                metadata={
                    "plannerStrategy": strategy,
                    "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION,
                },
            ))
            present.add(capability)
            used_keys.add(key)

    def _complete_capability_dependencies(
        self,
        nodes: list[PlannedTask],
        relations: list[TaskPlanRelation],
    ) -> list[TaskPlanRelation]:
        """Add only missing required catalog inputs; TaskPlan remains topology truth."""
        by_capability: dict[str, list[PlannedTask]] = {}
        node_positions = {node.key: index for index, node in enumerate(nodes)}
        existing = {
            (item.source_key, item.target_key, item.relation_type)
            for item in relations
        }
        for node in nodes:
            by_capability.setdefault(node.capability_requirements[0], []).append(node)
        existing_cycle = self._find_dependency_cycle(relations)
        if existing_cycle is not None:
            raise TaskDecompositionError(
                "TaskPlan dependency cycle: " + " -> ".join(existing_cycle)
            )
        for node in nodes:
            capability = node.capability_requirements[0]
            for required in self.capability_catalog.get(capability).depends_on:
                candidates = by_capability.get(required, [])
                if not candidates:
                    raise TaskDecompositionError(
                        f"task {node.key} requires missing predecessor capability {required}"
                    )
                preceding = [
                    candidate
                    for candidate in candidates
                    if node_positions[candidate.key] < node_positions[node.key]
                ]
                preferred = [*reversed(preceding), *(
                    candidate for candidate in candidates if candidate not in preceding
                )]
                source: PlannedTask | None = None
                blocked_cycles: list[tuple[str, ...]] = []
                for candidate in preferred:
                    identity = (
                        candidate.key,
                        node.key,
                        SemanticTaskRelationType.DEPENDS_ON,
                    )
                    if identity in existing:
                        source = candidate
                        break
                    reverse_path = self._find_dependency_path(
                        relations,
                        start=node.key,
                        target=candidate.key,
                    )
                    if reverse_path is None:
                        source = candidate
                        break
                    blocked_cycles.append((candidate.key, *reverse_path))
                if source is None:
                    cycle = blocked_cycles[0] if blocked_cycles else (node.key,)
                    raise TaskDecompositionError(
                        "required capability dependency "
                        f"{required} -> {capability} cannot be bound for task {node.key}; "
                        "the generated reverse path would create dependency cycle: "
                        + " -> ".join(cycle)
                    )
                identity = (source.key, node.key, SemanticTaskRelationType.DEPENDS_ON)
                if identity in existing:
                    continue
                relations.append(TaskPlanRelation(
                    sourceKey=source.key,
                    targetKey=node.key,
                    relationType=SemanticTaskRelationType.DEPENDS_ON,
                ))
                existing.add(identity)
        return relations

    @staticmethod
    def _dependency_adjacency(
        relations: list[TaskPlanRelation],
    ) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = {}
        for relation in relations:
            if relation.relation_type != SemanticTaskRelationType.DEPENDS_ON:
                continue
            targets = adjacency.setdefault(relation.source_key, [])
            if relation.target_key not in targets:
                targets.append(relation.target_key)
            adjacency.setdefault(relation.target_key, [])
        return adjacency

    @classmethod
    def _find_dependency_path(
        cls,
        relations: list[TaskPlanRelation],
        *,
        start: str,
        target: str,
    ) -> tuple[str, ...] | None:
        """Return one deterministic dependency path, including both endpoints."""
        adjacency = cls._dependency_adjacency(relations)
        pending: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
        visited: set[str] = set()
        while pending:
            current, path = pending.pop()
            if current == target:
                return path
            if current in visited:
                continue
            visited.add(current)
            for successor in reversed(adjacency.get(current, [])):
                if successor not in visited:
                    pending.append((successor, (*path, successor)))
        return None

    @classmethod
    def _find_dependency_cycle(
        cls,
        relations: list[TaskPlanRelation],
    ) -> tuple[str, ...] | None:
        """Return one deterministic cycle with its first node repeated at the end."""
        adjacency = cls._dependency_adjacency(relations)
        state: dict[str, int] = {}
        stack: list[str] = []
        stack_positions: dict[str, int] = {}

        def visit(node: str) -> tuple[str, ...] | None:
            state[node] = 1
            stack_positions[node] = len(stack)
            stack.append(node)
            for successor in adjacency.get(node, []):
                if state.get(successor, 0) == 0:
                    cycle = visit(successor)
                    if cycle is not None:
                        return cycle
                elif state.get(successor) == 1:
                    start = stack_positions[successor]
                    return (*stack[start:], successor)
            stack.pop()
            stack_positions.pop(node, None)
            state[node] = 2
            return None

        for node in adjacency:
            if state.get(node, 0) == 0:
                cycle = visit(node)
                if cycle is not None:
                    return cycle
        return None

    @staticmethod
    def _validate_coverage(plan: TaskPlan, profile: TaskSemanticProfile) -> None:
        searchable = json.dumps(plan.model_dump(by_alias=True), ensure_ascii=False).lower()
        cited_refs = {
            str(ref).strip().lower()
            for node in plan.nodes
            for ref in node.source_refs
            if str(ref).strip()
        }
        required = [
            *(
                (f"constraint:{index}", str(value))
                for index, value in enumerate(profile.key_constraints, start=1)
            ),
            *(
                (f"artifact:{index}", str(value))
                for index, value in enumerate(profile.expected_artifacts, start=1)
            ),
        ]
        missing_refs = [
            ref
            for ref, text in required
            if ref not in cited_refs and text.lower() not in searchable
        ]
        if missing_refs:
            raise TaskDecompositionError(
                "TaskPlan coverage gap for source refs: " + ", ".join(missing_refs)
            )

    def _fallback(
        self,
        *,
        mission_id: str,
        profile: TaskSemanticProfile,
        strategy: str,
        reason: str,
    ) -> TaskPlan:
        capabilities = list(dict.fromkeys(profile.required_capabilities))
        nodes: list[PlannedTask] = []
        selected = set(capabilities)
        for index, capability in enumerate(capabilities, start=1):
            descriptor = self.capability_catalog.get(capability)
            nodes.append(PlannedTask(
                key=f"task:{index:02d}:{capability}",
                title=descriptor.display_name,
                objective=f"Use {descriptor.display_name} to advance the mission goal: {profile.primary_goal}",
                constraints=[{"type": "mission_constraint", "value": item} for item in profile.key_constraints],
                capabilityRequirements=(capability,),
                acceptanceCriteria=(
                    descriptor.prompt_profile.quality_criteria[0]
                    if descriptor.prompt_profile.quality_criteria
                    else "Output satisfies the declared capability contract.",
                ),
                sourceRefs=tuple(profile.expected_artifacts),
                decompositionRationale="Explicit degraded deterministic plan after v2 decomposition failure.",
                logicalRole=descriptor.planning_stage,
                metadata={"plannerStrategy": strategy, "degraded": True, "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION},
            ))
        keys = {node.capability_requirements[0]: node.key for node in nodes}
        relations = tuple(
            TaskPlanRelation(sourceKey=keys[dependency], targetKey=keys[capability], relationType=SemanticTaskRelationType.DEPENDS_ON)
            for capability in capabilities
            for dependency in (
                *self.capability_catalog.get(capability).depends_on,
                *self.capability_catalog.get(capability).optional_dependencies,
            )
            if dependency in selected
        )
        return TaskPlan(
            missionId=mission_id,
            nodes=tuple(nodes),
            relations=relations,
            metadata={
                "strategy": strategy,
                "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION,
                "complexityBand": profile.estimated_complexity.value,
                "degraded": True,
                "degradationReason": reason[:1000],
            },
        )


__all__ = ["TASK_DECOMPOSITION_PROMPT_VERSION", "TaskDecomposer", "TaskDecompositionError"]
