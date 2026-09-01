"""Versioned semantic task decomposition without introducing another runtime."""

from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from contracts.planning import (
    PlannedTask,
    SemanticTaskRelationType,
    TaskPlan,
    TaskPlanRelation,
    VerificationLoopPolicy,
    WorksetSpec,
)
from support.acg.models import CapabilityCatalog, TaskSemanticProfile

from .complexity import PLANNING_BUDGETS
from .intent_analyzer import IntentLLM


TASK_DECOMPOSITION_PROMPT_VERSION = "task-decomposition.v6"

# 规划期模型调用的传输层超时预算。重型 Mission 的分阶段 outline/detail 推理
# 常超 2 分钟（provider 客户端默认 120s 读超时不足以覆盖），规划调用必须
# 显式声明更大的每调用预算；该值随调用透传到 provider 连接层。
PLANNING_MODEL_TIMEOUT_SECONDS = 480.0


def _is_model_timeout(exc: Exception) -> bool:
    """识别超时类异常（跨层不绑定具体错误类型，按稳定特征识别）。"""
    text = f"{getattr(exc, 'code', '')} {exc}".lower()
    return "timeout" in text or "timed out" in text

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
                    "workset": {
                        "type": ["object", "null"],
                        "properties": {
                            "sourceManifestRefs": {"type": "array", "items": {"type": "string"}},
                            "unitKind": {"type": "string", "enum": ["chunk", "section", "item"]},
                            "cursorStrategy": {"type": "string"},
                            "packingPolicy": {"type": "string", "enum": ["api_capacity"]},
                            "parallelismPolicy": {"type": "string"},
                            "estimatedUnitCount": {"type": ["integer", "null"]},
                        },
                        "required": ["sourceManifestRefs"],
                    },
                },
                "required": [
                    "key", "title", "objective", "capabilityId",
                    "acceptanceCriteria", "sourceRefs", "decompositionRationale",
                ],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sourceKey": {
                        "type": "string",
                        "description": "For depends_on, the prerequisite task executed first.",
                    },
                    "targetKey": {
                        "type": "string",
                        "description": "For depends_on, the dependent task executed afterward.",
                    },
                    "relationType": {"type": "string", "enum": ["depends_on", "parent"]},
                },
                "required": ["sourceKey", "targetKey", "relationType"],
            },
        },
        "controlPolicies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["verification_loop"]},
                    "bodyEntryKey": {"type": "string"},
                    "bodyExitKey": {"type": "string"},
                    "conditionSourceKey": {"type": "string"},
                    "statusPointer": {"type": "string"},
                    "repeatValues": {"type": "array", "items": {"type": "string"}},
                    "maxRevisions": {"type": "integer", "minimum": 0, "maximum": 8},
                    "onExhausted": {"type": "string", "enum": ["human_review", "fail"]},
                },
                "required": [
                    "type", "bodyEntryKey", "bodyExitKey", "conditionSourceKey",
                    "statusPointer", "repeatValues", "maxRevisions", "onExhausted",
                ],
            },
        },
        "budgetRationale": {"type": "string"},
    },
    "required": ["tasks", "relations"],
}


class TaskDecompositionError(ValueError):
    pass


class TaskDecomposer:
    def __init__(
        self,
        capability_catalog: CapabilityCatalog,
        llm: IntentLLM | None,
        model_timeout_seconds: float | None = None,
    ) -> None:
        self.capability_catalog = capability_catalog
        self.llm = llm
        self.model_timeout_seconds = float(
            model_timeout_seconds or PLANNING_MODEL_TIMEOUT_SECONDS
        )
        if self.model_timeout_seconds <= 0:
            raise ValueError("model_timeout_seconds must be positive")
        self.last_audit: dict[str, Any] = {}

    def _call_llm(self, *, stage: str, prompt: str, schema: dict, **kwargs) -> Any:
        """带超时预算声明的模型调用：单点超时自动重试一次并留审计。

        瞬态读超时不应判死整条规划链（2026-09-01 run_1a25f0d4ad89 根因），
        但也不得无限放大延迟：同一调用点最多两次尝试，持续超时按既有失败
        路径上抛。
        """
        kwargs.setdefault("timeout_seconds", self.model_timeout_seconds)
        try:
            return self.llm.generate_json(prompt, schema, **kwargs)
        except Exception as exc:
            if not _is_model_timeout(exc):
                raise
            self.last_audit.setdefault("timeoutRetries", []).append(stage)
            return self.llm.generate_json(prompt, schema, **kwargs)

    def decompose(
        self,
        *,
        mission_id: str,
        profile: TaskSemanticProfile,
        strategy: str,
        task_input: Mapping[str, Any] | None,
        use_llm: bool,
        reasoning_effort: str | None = None,
        existing_semantic_tasks: tuple[Mapping[str, Any], ...] = (),
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
            prompt = self.build_prompt(
                profile=profile,
                task_input=task_input,
                existing_semantic_tasks=existing_semantic_tasks,
            )
            if (task_input or {}).get("_effectiveCapabilityProfile") == "full":
                return self._decompose_staged(
                    mission_id=mission_id,
                    profile=profile,
                    strategy=strategy,
                    task_input=task_input,
                    existing_semantic_tasks=existing_semantic_tasks,
                    prompt=prompt,
                    reasoning_effort=reasoning_effort,
                )
            first: Any = None
            try:
                first = self._call_llm(
                    stage="decompose",
                    prompt=prompt,
                    schema=_SCHEMA,
                    max_tokens=16_384,
                    reasoning_effort=reasoning_effort,
                    prompt_version=TASK_DECOMPOSITION_PROMPT_VERSION,
                )
                self._capture_model_audit(first)
                return self._to_plan(
                    mission_id,
                    profile,
                    strategy,
                    first,
                    task_input=task_input,
                    existing_semantic_tasks=existing_semantic_tasks,
                )
            except Exception as first_error:
                try:
                    missing_refs = self._coverage_gap_refs(first_error)
                    if missing_refs and first is not None:
                        repaired = self._repair_source_ref_coverage(
                            raw=first,
                            profile=profile,
                            missing_refs=missing_refs,
                            reasoning_effort=reasoning_effort,
                        )
                        repair_version = f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1.coverage"
                    else:
                        invalid_plan = json.dumps(first, ensure_ascii=False, default=str)
                        repaired = self._call_llm(
                            stage="repair",
                            prompt=prompt
                            + "\nThe previous result failed TaskPlan schema or topology validation. "
                            + "Repair it once. Preserve valid task semantics, remove every reported "
                            + "dependency cycle or reverse prerequisite path, and return the complete JSON again. "
                            + f"Validation detail: {first_error}\n"
                            + f"Previous invalid TaskPlan JSON: {invalid_plan}",
                            schema=_SCHEMA,
                            max_tokens=16_384,
                            reasoning_effort=reasoning_effort,
                            prompt_version=f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1",
                        )
                        repair_version = f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1"
                    self.last_audit["promptVersion"] = repair_version
                    self._capture_model_audit(repaired)
                    return self._to_plan(
                        mission_id,
                        profile,
                        strategy,
                        repaired,
                        task_input=task_input,
                        existing_semantic_tasks=existing_semantic_tasks,
                    )
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
            existing_semantic_tasks=existing_semantic_tasks,
        )

    def _decompose_staged(
        self,
        *,
        mission_id: str,
        profile: TaskSemanticProfile,
        strategy: str,
        task_input: Mapping[str, Any] | None,
        existing_semantic_tasks: tuple[Mapping[str, Any], ...],
        prompt: str,
        reasoning_effort: str | None,
    ) -> TaskPlan:
        """Build a large TaskPlan through bounded JSON units.

        Stable semantic keys are fixed by the outline. Detail failures retry only
        their five-task batch and relation failures retry only the relation unit.
        """
        task_item_schema = deepcopy(_SCHEMA["properties"]["tasks"]["items"])
        outline_schema = {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "title": {"type": "string"},
                            "capabilityId": {"type": "string"},
                            "logicalRole": {"type": "string"},
                            "sourceRefs": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["key", "title", "capabilityId", "logicalRole", "sourceRefs"],
                    },
                }
            },
            "required": ["tasks"],
        }
        self.last_audit.update({"mode": "model_staged", "stages": []})
        try:
            outline_result = self._call_llm(
                stage="outline",
                prompt=prompt + "\nSTAGE OUTLINE: return only stable task identities, titles, primary capabilities, roles and sourceRefs. Do not return relations or verbose objectives.",
                schema=outline_schema,
                max_tokens=16_384,
                reasoning_effort=reasoning_effort,
                prompt_version=f"{TASK_DECOMPOSITION_PROMPT_VERSION}.outline",
            )
            outline_payload = outline_result.get("data", outline_result)
            outline = outline_payload.get("tasks") if isinstance(outline_payload, dict) else None
            if not isinstance(outline, list) or not outline:
                raise TaskDecompositionError("staged outline returned no tasks")
            keys = [str(item.get("key") or "").strip() for item in outline if isinstance(item, dict)]
            if len(keys) != len(outline) or not all(keys) or len(keys) != len(set(keys)):
                raise TaskDecompositionError("staged outline contains empty or duplicate task keys")
            self.last_audit["stages"].append({"stage": "outline", "taskCount": len(keys)})

            detailed_tasks: list[dict[str, Any]] = []
            for offset in range(0, len(outline), 5):
                batch = outline[offset:offset + 5]
                batch_keys = [str(item["key"]) for item in batch]
                detail_schema = {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "minItems": len(batch),
                            "maxItems": len(batch),
                            "items": task_item_schema,
                        }
                    },
                    "required": ["tasks"],
                }
                detail_prompt = (
                    "STAGE DETAIL: expand exactly this outline batch into complete TaskPlan task objects. "
                    "Preserve every key and capabilityId exactly; return no other tasks and no relations. "
                    "Every task needs a business objective, acceptance criteria, source refs and rationale.\n"
                    f"Mission planning context: {prompt}\n"
                    f"Frozen outline batch: {json.dumps(batch, ensure_ascii=False)}"
                )
                try:
                    detail_result = self._call_llm(
                        stage="detail",
                        prompt=detail_prompt,
                        schema=detail_schema,
                        max_tokens=16_384,
                        reasoning_effort=reasoning_effort,
                        prompt_version=f"{TASK_DECOMPOSITION_PROMPT_VERSION}.detail",
                    )
                except Exception as exc:
                    detail_result = self._call_llm(
                        stage="detail.repair",
                        prompt=detail_prompt + f"\nRepair this batch once. Previous error: {exc}",
                        schema=detail_schema,
                        max_tokens=16_384,
                        reasoning_effort=reasoning_effort,
                        prompt_version=f"{TASK_DECOMPOSITION_PROMPT_VERSION}.detail.repair1",
                    )
                detail_payload = detail_result.get("data", detail_result)
                rows = detail_payload.get("tasks") if isinstance(detail_payload, dict) else None
                returned_keys = [str(item.get("key") or "") for item in rows or [] if isinstance(item, dict)]
                if set(returned_keys) != set(batch_keys) or len(returned_keys) != len(batch_keys):
                    raise TaskDecompositionError("staged detail batch changed frozen task identities")
                detailed_tasks.extend(rows)
                self.last_audit["stages"].append({"stage": "detail", "keys": batch_keys})

            relation_schema = {
                "type": "object",
                "properties": {
                    "relations": deepcopy(_SCHEMA["properties"]["relations"]),
                    "controlPolicies": deepcopy(_SCHEMA["properties"]["controlPolicies"]),
                },
                "required": ["relations", "controlPolicies"],
            }
            compact = [
                {
                    "key": item["key"],
                    "capabilityId": item["capabilityId"],
                    "logicalRole": item.get("logicalRole", "task"),
                    "objective": item.get("objective", ""),
                }
                for item in detailed_tasks
            ]
            relation_prompt = (
                "STAGE RELATIONS: create the acyclic prerequisite-to-dependent topology for these frozen tasks. "
                "Add a verification_loop only when a refinement-to-verification region is present; use maxRevisions=2.\n"
                f"Tasks: {json.dumps(compact, ensure_ascii=False)}"
            )
            try:
                relation_result = self._call_llm(
                    stage="relations",
                    prompt=relation_prompt,
                    schema=relation_schema,
                    max_tokens=16_384,
                    reasoning_effort=reasoning_effort,
                    prompt_version=f"{TASK_DECOMPOSITION_PROMPT_VERSION}.relations",
                )
            except Exception as exc:
                relation_result = self._call_llm(
                    stage="relations.repair",
                    prompt=relation_prompt + f"\nRepair the relation unit once. Previous error: {exc}",
                    schema=relation_schema,
                    max_tokens=16_384,
                    reasoning_effort=reasoning_effort,
                    prompt_version=f"{TASK_DECOMPOSITION_PROMPT_VERSION}.relations.repair1",
                )
            relation_payload = relation_result.get("data", relation_result)
            combined = {
                "tasks": detailed_tasks,
                "relations": relation_payload.get("relations", []),
                "controlPolicies": relation_payload.get("controlPolicies", []),
            }
            self.last_audit["stages"].append({"stage": "relations"})
            try:
                plan = self._to_plan(
                    mission_id, profile, strategy, combined,
                    task_input=task_input,
                    existing_semantic_tasks=existing_semantic_tasks,
                )
            except Exception as exc:
                missing_refs = self._coverage_gap_refs(exc)
                if not missing_refs:
                    raise
                combined = self._repair_source_ref_coverage(
                    raw=combined,
                    profile=profile,
                    missing_refs=missing_refs,
                    reasoning_effort=reasoning_effort,
                )
                plan = self._to_plan(
                    mission_id, profile, strategy, combined,
                    task_input=task_input,
                    existing_semantic_tasks=existing_semantic_tasks,
                )
            self._capture_model_audit(outline_result)
            return plan
        except Exception as exc:
            self.last_audit["mode"] = "failed"
            self.last_audit["error"] = type(exc).__name__
            raise TaskDecompositionError(f"TASK_PLAN_STAGED_FAILED: {exc}") from exc

    @staticmethod
    def _coverage_gap_refs(error: Exception) -> tuple[str, ...]:
        prefix = "TaskPlan coverage gap for source refs:"
        detail = str(error)
        if not isinstance(error, TaskDecompositionError) or not detail.startswith(prefix):
            return ()
        return tuple(
            ref.strip()
            for ref in detail[len(prefix):].split(",")
            if ref.strip()
        )

    def _repair_source_ref_coverage(
        self,
        *,
        raw: Any,
        profile: TaskSemanticProfile,
        missing_refs: tuple[str, ...],
        reasoning_effort: str | None = None,
    ) -> Any:
        """Repair provenance annotations without rewriting valid task semantics/topology."""
        payload = raw.get("data", raw) if isinstance(raw, dict) else {}
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list) or not tasks:
            raise TaskDecompositionError("coverage repair requires the original task list")
        task_keys = tuple(
            str(item.get("key") or "").strip()
            for item in tasks
            if isinstance(item, dict) and str(item.get("key") or "").strip()
        )
        if not task_keys:
            raise TaskDecompositionError("coverage repair requires stable task keys")

        source_registry = {
            item["ref"]: item["text"]
            for item in self._source_registry(profile)
        }
        missing_registry = [
            {"ref": ref, "text": source_registry[ref]}
            for ref in missing_refs
            if ref in source_registry
        ]
        if len(missing_registry) != len(missing_refs):
            raise TaskDecompositionError("coverage repair contains unknown source refs")

        schema = {
            "type": "object",
            "properties": {
                "assignments": {
                    "type": "array",
                    "minItems": len(missing_refs),
                    "maxItems": len(missing_refs),
                    "items": {
                        "type": "object",
                        "properties": {
                            "sourceRef": {"type": "string", "enum": list(missing_refs)},
                            "taskKey": {"type": "string", "enum": list(task_keys)},
                            "rationale": {"type": "string"},
                        },
                        "required": ["sourceRef", "taskKey", "rationale"],
                    },
                },
            },
            "required": ["assignments"],
        }
        task_catalog = [
            {
                "key": str(item.get("key") or ""),
                "title": str(item.get("title") or ""),
                "objective": str(item.get("objective") or ""),
                "acceptanceCriteria": item.get("acceptanceCriteria") or [],
                "sourceRefs": item.get("sourceRefs") or [],
            }
            for item in tasks
            if isinstance(item, dict)
        ]
        repair_version = f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1.coverage"
        self.last_audit["promptVersion"] = repair_version
        assignment_result = self._call_llm(
            stage="repair_coverage",
            prompt="Repair only the missing TaskPlan source-reference annotations. "
            "Do not create, delete, rename or rewrite tasks and do not change relations. "
            "Assign every missing sourceRef exactly once to the existing task whose objective "
            "and acceptance criteria will produce or verify that requirement. Return JSON only.\n"
            f"Missing source registry entries: {json.dumps(missing_registry, ensure_ascii=False)}\n"
            f"Existing tasks: {json.dumps(task_catalog, ensure_ascii=False)}",
            schema=schema,
            max_tokens=16_384,
            reasoning_effort=reasoning_effort,
            prompt_version=repair_version,
        )
        self._capture_model_audit(assignment_result)
        assignment_payload = (
            assignment_result.get("data", assignment_result)
            if isinstance(assignment_result, dict)
            else {}
        )
        assignments = (
            assignment_payload.get("assignments")
            if isinstance(assignment_payload, dict)
            else None
        )
        if not isinstance(assignments, list):
            raise TaskDecompositionError("coverage repair returned no assignments")

        assigned_refs: list[str] = []
        assignments_by_task: dict[str, list[str]] = {}
        for item in assignments:
            if not isinstance(item, dict):
                raise TaskDecompositionError("coverage repair assignment must be an object")
            source_ref = str(item.get("sourceRef") or "").strip()
            task_key = str(item.get("taskKey") or "").strip()
            if source_ref not in missing_refs or task_key not in task_keys:
                raise TaskDecompositionError("coverage repair returned an unknown ref or task key")
            assigned_refs.append(source_ref)
            assignments_by_task.setdefault(task_key, []).append(source_ref)
        if len(assigned_refs) != len(set(assigned_refs)) or set(assigned_refs) != set(missing_refs):
            raise TaskDecompositionError(
                "coverage repair must assign every missing source ref exactly once"
            )

        repaired = deepcopy(raw)
        repaired_payload = repaired.get("data", repaired)
        for item in repaired_payload["tasks"]:
            task_key = str(item.get("key") or "").strip()
            additions = assignments_by_task.get(task_key, [])
            if additions:
                item["sourceRefs"] = list(dict.fromkeys([
                    *(str(ref) for ref in item.get("sourceRefs", []) if str(ref)),
                    *additions,
                ]))
        return repaired

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
        existing_semantic_tasks: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        level = profile.estimated_complexity
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
        material_refs = tuple(
            str(item) for item in ((task_input or {}).get("materialRefs") or []) if str(item)
        )
        contract = {
            "objective": (task_input or {}).get("objective") or profile.primary_goal,
            "constraints": (task_input or {}).get("constraints") or profile.key_constraints,
            "expectedArtifacts": (task_input or {}).get("expectedArtifacts") or profile.expected_artifacts,
            "verificationRequirements": profile.verification_requirements,
            "sourceRegistry": [
                *self._source_registry(profile),
                *(
                    {"ref": item, "kind": "material_manifest", "text": "immutable content manifest"}
                    for item in material_refs
                ),
            ],
            "materials": {
                key: value
                for key in ("materials", "sourceMaterials", "materialText", "contractText")
                if (value := (task_input or {}).get(key)) not in (None, "", [], {})
            },
        }
        budget_lo, budget_hi = PLANNING_BUDGETS[level]
        identity_guidance = (
            "This Mission already has a canonical semantic task key catalog. "
            "Reuse an existing key when it represents the same logical step, even when "
            "the objective, constraints, inputs or planning metadata changed. "
            "Create a new key only when the logical step itself is new. Existing keys are "
            f"{json.dumps(list(existing_semantic_tasks), ensure_ascii=False)}.\n"
            if existing_semantic_tasks else
            "Choose each key as a descriptive, Mission-scoped logical identity. Do not use "
            "ordinal-only keys such as task-1 or step-2, and do not derive a key from a "
            "title/objective/constraints hash.\n"
        )
        return (
            f"Prompt version: {TASK_DECOMPOSITION_PROMPT_VERSION}\n"
            "Create an executable, acyclic, domain-neutral TaskPlan and return JSON only.\n"
            f"Complexity assessment: {profile.complexity_assessment.model_dump() if profile.complexity_assessment else level.value}.\n"
            f"Planning budget: complexity band {level.value} should decompose into approximately "
            f"{int(budget_lo)}-{int(budget_hi)} tasks (inclusive). Treat the budget as a semantic "
            "coverage target: do not pad or split tasks merely to satisfy it, and do not merge "
            "genuinely separable deliverables just to stay under it.\n"
            "Choose the task count from semantic coverage, verifiable deliverables, useful "
            "dependencies, parallel work and aggregation needs, steered by that planning budget. "
            "Material chunks are Workset units inside a logical task, not reasons to "
            "manufacture one business task per chunk.\n"
            "Every task must have one business-specific objective, one primary capabilityId, explicit acceptance criteria, "
            "sourceRefs and a decomposition rationale. Do not write objectives such as 'Complete cost analysis'.\n"
            "A task key is a stable logical identity across Runs, not a semantic-content version. "
            "Planning content belongs to the Run-specific TaskPlan snapshot.\n"
            + identity_guidance
            + "The same capabilityId may be instantiated by multiple tasks when goals, alternatives or stages differ. "
            "Use depends_on relations as the authoritative execution topology and keep it acyclic.\n"
            "For every depends_on relation, sourceKey is the prerequisite or producer executed first, "
            "and targetKey is the dependent or consumer executed afterward. "
            "Example: if extraction depends on understanding, use "
            "{\"sourceKey\":\"understand\",\"targetKey\":\"extract\",\"relationType\":\"depends_on\"}; "
            "the reverse edge from extract to understand is forbidden.\n"
            "Capability catalog dependsOn entries are hard prerequisites that the system will enforce after generation. "
            "Never create a reverse path from a dependent task back to one of its prerequisite tasks. "
            "optionalDependencies are advisory and must not be added when they create a cycle.\n"
            "For complex work with solution refinement and verification, declare a "
            "verification_loop in controlPolicies instead of creating a dependency cycle. "
            "The condition source must expose verification.status, maxRevisions must be 2, "
            "and onExhausted must be human_review.\n"
            "Cover every hard constraint and expected artifact; do not invent facts or domain capabilities.\n"
            "When source material is represented by materialRefs, attach a WorksetSpec to the "
            "logical task that scans it. Consume pages by cursor; do not copy all fragments into "
            "one ContextPack and do not create one semantic task per storage fragment.\n"
            "For coverage, copy stable sourceRegistry ref values into task.sourceRefs. Do not prove coverage "
            "by repeating or paraphrasing source text. Every sourceRegistry ref must be cited by a task.\n"
            f"Mission requirements: {json.dumps(contract, ensure_ascii=False, default=str)}\n"
            f"Semantic profile: {profile.model_dump_json(by_alias=True)}\n"
            f"Capability catalog: {json.dumps(catalog, ensure_ascii=False)}\n"
        )

    @staticmethod
    def _budget_metadata(profile: TaskSemanticProfile, node_count: int) -> dict[str, Any]:
        """记录档位预算三元组：只做审计观测，不在生成侧拦截。"""
        budget_lo, budget_hi = PLANNING_BUDGETS[profile.estimated_complexity]
        lo, hi = int(budget_lo), int(budget_hi)
        return {
            "budgetRange": [lo, hi],
            "actualTaskCount": int(node_count),
            "withinBudget": bool(lo <= node_count <= hi),
        }

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
        task_input: Mapping[str, Any] | None = None,
        existing_semantic_tasks: tuple[Mapping[str, Any], ...] = (),
    ) -> TaskPlan:
        payload = raw.get("data", raw) if isinstance(raw, dict) else {}
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list) or not tasks:
            raise TaskDecompositionError("decomposer returned no tasks")
        nodes: list[PlannedTask] = []
        key_map: dict[str, str] = {}
        raw_parent_keys: list[str | None] = []
        used_keys: set[str] = set()
        for item in tasks:
            capability = str(item.get("capabilityId") or "").strip().lower()
            self.capability_catalog.get(capability)
            objective = str(item.get("objective") or "").strip()
            if not objective or re.match(r"^(complete|完成)\s*\S*$", objective, re.IGNORECASE):
                raise TaskDecompositionError(f"task {item.get('key')} has no business objective")
            criteria = tuple(str(value).strip() for value in item.get("acceptanceCriteria", []) if str(value).strip())
            if not criteria:
                raise TaskDecompositionError(f"task {item.get('key')} has empty acceptance criteria")
            raw_key = str(item.get("key") or "").strip()
            key = self._resolve_semantic_task_key(
                raw_key=raw_key,
                capability=capability,
                logical_role=str(item.get("logicalRole") or "task").strip(),
                existing_semantic_tasks=existing_semantic_tasks,
                used_keys=used_keys,
            )
            if raw_key in key_map:
                raise TaskDecompositionError(f"duplicate semantic task key: {raw_key}")
            key_map[raw_key] = key
            used_keys.add(key)
            raw_parent_keys.append(item.get("parentKey"))
            nodes.append(PlannedTask(
                key=key,
                parentKey=None,
                title=str(item.get("title") or objective[:60]).strip(),
                objective=objective,
                constraints=self._normalize_constraints(item.get("constraints")),
                capabilityRequirements=(capability,),
                acceptanceCriteria=criteria,
                sourceRefs=tuple(str(value) for value in item.get("sourceRefs", []) if str(value)),
                decompositionRationale=str(item.get("decompositionRationale") or ""),
                logicalRole=str(item.get("logicalRole") or "task"),
                workset=(WorksetSpec.model_validate(item["workset"]) if item.get("workset") else None),
                metadata={"plannerStrategy": strategy, "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION},
            ))
        nodes = [
            node.model_copy(update={
                "parent_key": key_map.get(raw_parent, raw_parent) if raw_parent else None,
            })
            for node, raw_parent in zip(nodes, raw_parent_keys)
        ]
        material_refs = tuple(
            str(item) for item in ((task_input or {}).get("materialRefs") or []) if str(item)
        )
        if material_refs and not any(node.workset is not None for node in nodes):
            preferred = next(
                (
                    index for index, node in enumerate(nodes)
                    if node.capability_requirements[0] in {
                        "information_extraction", "task_understanding", "analysis", "evidence_analysis"
                    }
                ),
                0,
            )
            nodes[preferred] = nodes[preferred].model_copy(
                update={
                    "workset": WorksetSpec(sourceManifestRefs=material_refs),
                    "source_refs": tuple(dict.fromkeys((*nodes[preferred].source_refs, *material_refs))),
                }
            )
        self._complete_missing_capability_tasks(nodes, profile, strategy)
        relations = self._normalize_direct_reversed_required_dependencies(
            nodes,
            [
                TaskPlanRelation(
                    sourceKey=key_map.get(str(item.get("sourceKey") or "").strip(), str(item.get("sourceKey") or "").strip()),
                    targetKey=key_map.get(str(item.get("targetKey") or "").strip(), str(item.get("targetKey") or "").strip()),
                    relationType=item.get("relationType"),
                )
                for item in payload.get("relations", [])
            ],
        )
        relations = self._complete_capability_dependencies(nodes, relations)
        relations = self._connect_terminal_results(nodes, relations)
        control_policies = tuple(
            VerificationLoopPolicy.model_validate({
                **item,
                "bodyEntryKey": key_map.get(
                    str(item.get("bodyEntryKey") or "").strip(),
                    str(item.get("bodyEntryKey") or "").strip(),
                ),
                "bodyExitKey": key_map.get(
                    str(item.get("bodyExitKey") or "").strip(),
                    str(item.get("bodyExitKey") or "").strip(),
                ),
                "conditionSourceKey": key_map.get(
                    str(item.get("conditionSourceKey") or "").strip(),
                    str(item.get("conditionSourceKey") or "").strip(),
                ),
            })
            for item in payload.get("controlPolicies", [])
            if isinstance(item, dict)
        )
        plan = TaskPlan(
            missionId=mission_id,
            nodes=tuple(nodes),
            relations=tuple(relations),
            controlPolicies=control_policies,
            metadata={
                "strategy": strategy,
                "promptVersion": TASK_DECOMPOSITION_PROMPT_VERSION,
                "complexityBand": profile.estimated_complexity.value,
                "planningBudget": self._budget_metadata(profile, len(nodes)),
                "degraded": False,
            },
        )
        self._validate_coverage(plan, profile)
        return plan

    @staticmethod
    def _resolve_semantic_task_key(
        *,
        raw_key: str,
        capability: str,
        logical_role: str,
        existing_semantic_tasks: tuple[Mapping[str, Any], ...],
        used_keys: set[str],
    ) -> str:
        """Resolve unstable ordinal model keys without hashing semantic content.

        A descriptive model key remains authoritative when it is already in the catalog.
        Otherwise an existing key is reused only when its role/capability match is
        unambiguous; ordinal placeholders fall back to a deterministic logical-role/
        capability key without hashing semantic content.
        """
        if not raw_key:
            raise TaskDecompositionError("task has no semantic logical key")
        if raw_key in {str(item.get("key") or "").strip() for item in existing_semantic_tasks}:
            return raw_key
        matches = [
            str(item.get("key") or "").strip()
            for item in existing_semantic_tasks
            if str(item.get("capabilityId") or item.get("capability") or "").strip().lower() == capability
            and str(item.get("logicalRole") or item.get("logical_role") or "task").strip().lower() == (logical_role or "task").lower()
        ]
        matches = [item for item in matches if item and item not in used_keys]
        if len(matches) == 1:
            return matches[0]
        ordinal = re.fullmatch(r"(?:task|step|node)[\s_:/-]*\d+(?:[\s_:/-].*)?", raw_key.lower())
        if ordinal:
            role = re.sub(r"[^a-z0-9]+", "_", (logical_role or "task").lower()).strip("_") or "task"
            capability_slug = re.sub(r"[^a-z0-9]+", "_", capability.lower()).strip("_") or "capability"
            base = f"{role}:{capability_slug}"
            candidate = base
            suffix = 2
            while candidate in used_keys:
                candidate = f"{base}:{suffix}"
                suffix += 1
            return candidate
        return raw_key

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

    def _normalize_direct_reversed_required_dependencies(
        self,
        nodes: list[PlannedTask],
        relations: list[TaskPlanRelation],
    ) -> list[TaskPlanRelation]:
        """Remove only catalog-provable reversed hard-dependency edges.

        The normal dependency completion pass then installs the authoritative
        prerequisite -> dependent edge and performs the usual cycle checks.
        """
        capability_by_key = {
            node.key: node.capability_requirements[0]
            for node in nodes
        }
        normalized: list[TaskPlanRelation] = []
        for relation in relations:
            if relation.relation_type != SemanticTaskRelationType.DEPENDS_ON:
                normalized.append(relation)
                continue
            source_capability = capability_by_key.get(relation.source_key)
            target_capability = capability_by_key.get(relation.target_key)
            is_proven_reverse = bool(
                source_capability
                and target_capability
                and target_capability in self.capability_catalog.get(source_capability).depends_on
            )
            if not is_proven_reverse:
                normalized.append(relation)
        return normalized

    def _connect_terminal_results(
        self,
        nodes: list[PlannedTask],
        relations: list[TaskPlanRelation],
    ) -> list[TaskPlanRelation]:
        """Ensure every semantic leaf reaches a verification or artifact sink.

        This is a domain-neutral topology invariant, not a replacement planner.  The model
        remains responsible for task meaning and ordering; Core only connects otherwise
        orphaned terminal results to an existing declared sink so final assembly cannot
        silently omit a completed branch.
        """
        sink_capabilities = {"verification", "artifact_generation"}
        sinks = [
            node for node in nodes
            if node.capability_requirements[0] in sink_capabilities
        ]
        if not sinks:
            return relations
        existing = {
            (item.source_key, item.target_key, item.relation_type)
            for item in relations
        }
        outgoing = {
            item.source_key
            for item in relations
            if item.relation_type == SemanticTaskRelationType.DEPENDS_ON
        }
        positions = {node.key: index for index, node in enumerate(nodes)}
        for leaf in nodes:
            if leaf.key in outgoing or leaf in sinks:
                continue
            # Prefer a later artifact sink, then a later verification sink.  If the model
            # ordered the sink earlier, use any cycle-safe declared sink instead of inventing
            # a new task or dropping the leaf.
            candidates = sorted(
                sinks,
                key=lambda node: (
                    positions[node.key] <= positions[leaf.key],
                    node.capability_requirements[0] != "artifact_generation",
                    positions[node.key],
                ),
            )
            for sink in candidates:
                identity = (leaf.key, sink.key, SemanticTaskRelationType.DEPENDS_ON)
                if identity in existing:
                    break
                if self._find_dependency_path(
                    relations, start=sink.key, target=leaf.key
                ) is not None:
                    continue
                relation = TaskPlanRelation(
                    sourceKey=leaf.key,
                    targetKey=sink.key,
                    relationType=SemanticTaskRelationType.DEPENDS_ON,
                )
                relations.append(relation)
                existing.add(identity)
                outgoing.add(leaf.key)
                break
            else:
                raise TaskDecompositionError(
                    f"terminal task {leaf.key} cannot reach a verification or artifact sink"
                )
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
        existing_semantic_tasks: tuple[Mapping[str, Any], ...] = (),
    ) -> TaskPlan:
        capabilities = list(dict.fromkeys(profile.required_capabilities))
        nodes: list[PlannedTask] = []
        selected = set(capabilities)
        used_keys: set[str] = set()
        for index, capability in enumerate(capabilities, start=1):
            descriptor = self.capability_catalog.get(capability)
            key = self._resolve_semantic_task_key(
                raw_key=f"task-{index}",
                capability=capability,
                logical_role=descriptor.planning_stage,
                existing_semantic_tasks=existing_semantic_tasks,
                used_keys=used_keys,
            )
            used_keys.add(key)
            nodes.append(PlannedTask(
                key=key,
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
                "planningBudget": self._budget_metadata(profile, len(nodes)),
                "degraded": True,
                "degradationReason": reason[:1000],
            },
        )


__all__ = [
    "PLANNING_MODEL_TIMEOUT_SECONDS",
    "TASK_DECOMPOSITION_PROMPT_VERSION",
    "TaskDecomposer",
    "TaskDecompositionError",
]
