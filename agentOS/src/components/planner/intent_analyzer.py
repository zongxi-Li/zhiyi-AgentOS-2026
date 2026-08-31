"""将原始意图按目录解析为领域无关的语义画像。"""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from typing import Any, Dict, Optional, Protocol

from support.acg.models import (
    CapabilityCatalog,
    highest_planning_risk_level,
)
from support.acg.models import build_default_capability_catalog
from support.acg.models import CapabilityCandidate, TaskSemanticProfile
from .complexity import assess_complexity


INTENT_PROFILE_PROMPT_VERSION = "intent-profile.v2"


class IntentLLM(Protocol):
    """意图解析可选模型适配器协议；实现必须返回符合给定模式的 JSON 对象。"""

    def generate_json(self, prompt: str, schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """根据提示和输出模式生成 JSON；具体网络调用、重试和费用由实现方负责。"""
        ...


_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "primaryGoal": {"type": "string"},
        "keyConstraints": {"type": "array", "items": {"type": "string"}},
        "requiredCapabilities": {"type": "array", "items": {"type": "string"}},
        "expectedArtifacts": {"type": "array", "items": {"type": "string"}},
        "verificationRequirements": {"type": "array", "items": {"type": "string"}},
        "estimatedComplexity": {
            "type": "string",
            "enum": ["simple", "medium", "complex", "extreme"],
        },
        "domainHint": {"type": "string"},
        "taskTypeHint": {"type": "string"},
        "implicitRequirements": {"type": "array", "items": {"type": "string"}},
        "riskLevel": {"type": "string"},
    },
    "required": ["primaryGoal", "requiredCapabilities", "estimatedComplexity"],
}

_NATIVE_FALLBACK = ["task_understanding", "analysis", "artifact_generation"]


class IntentParser:
    """使用模型或确定性别名解析意图，且只选择已注册能力。"""

    def __init__(
        self,
        llm: Optional[IntentLLM] = None,
        capability_catalog: CapabilityCatalog | None = None,
    ) -> None:
        self.llm = llm
        self.capability_catalog = capability_catalog or build_default_capability_catalog()
        self.last_audit: dict[str, Any] = {}

    def parse(
        self,
        *,
        intent: str,
        domain: str = "general",
        task_type: str = "general",
        thinking_mode: str | None = None,
        reasoning_effort: str | None = None,
        use_llm: bool = True,
        task_input: Mapping[str, Any] | None = None,
        declared_capabilities: list[str] | tuple[str, ...] | None = None,
    ) -> TaskSemanticProfile:
        """把用户意图解析为标准语义画像。

        可使用模型补充信息；仅在模型禁用或不可用时采用显式确定性规划。模型输出违反
        合同时只修复一次，仍失败则抛出结构化错误。输出能力均按目录归一。
        """
        self.last_audit = {
            "promptVersion": INTENT_PROFILE_PROMPT_VERSION,
            "promptTemplateHash": hashlib.sha256(
                (INTENT_PROFILE_PROMPT_VERSION + json.dumps(_PROFILE_SCHEMA, sort_keys=True)).encode("utf-8")
            ).hexdigest(),
            "modelVersion": str(getattr(self.llm, "model", None) or getattr(self.llm, "version", None) or "unreported"),
            "mode": "model" if use_llm and self.llm is not None else "deterministic",
        }
        if use_llm and self.llm is not None:
            try:
                return self._parse_with_llm(
                    intent, domain, task_type, thinking_mode, task_input,
                    reasoning_effort=reasoning_effort,
                    declared_capabilities=declared_capabilities,
                )
            except Exception as first_error:
                try:
                    profile = self._parse_with_llm(
                        intent,
                        domain,
                        task_type,
                        thinking_mode,
                        task_input,
                        reasoning_effort=reasoning_effort,
                        prompt_version=f"{INTENT_PROFILE_PROMPT_VERSION}.repair1",
                        repair_error=str(first_error),
                        declared_capabilities=declared_capabilities,
                    )
                    self.last_audit["promptVersion"] = f"{INTENT_PROFILE_PROMPT_VERSION}.repair1"
                    return profile
                except Exception as repair_error:
                    self.last_audit["mode"] = "failed"
                    self.last_audit["error"] = type(repair_error).__name__
                    raise ValueError(
                        "INTENT_PROFILE_CONTRACT_FAILED after one repair: "
                        f"{repair_error}"
                    ) from first_error
        return self._heuristic(intent, domain, task_type, task_input)

    def _parse_with_llm(
        self,
        intent: str,
        domain: str,
        task_type: str,
        thinking_mode: str | None,
        task_input: Mapping[str, Any] | None,
        reasoning_effort: str | None = None,
        prompt_version: str = INTENT_PROFILE_PROMPT_VERSION,
        repair_error: str | None = None,
        declared_capabilities: list[str] | tuple[str, ...] | None = None,
    ) -> TaskSemanticProfile:
        result = self.llm.generate_json(
            self.build_prompt(intent=intent, domain=domain, task_type=task_type, task_input=task_input)
            + (f"\nRepair the previous contract error once: {repair_error}" if repair_error else ""),
            _PROFILE_SCHEMA,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
            prompt_version=prompt_version,
        )
        if isinstance(result, dict):
            if result.get("model"):
                self.last_audit["modelVersion"] = str(result["model"])
            if result.get("provider"):
                self.last_audit["provider"] = str(result["provider"])
        data = result.get("data", result) if isinstance(result, dict) else {}
        data = dict(data) if isinstance(data, dict) else {}
        data.pop("entropyBudget", None)
        data.pop("entropy_budget", None)
        data.setdefault("domainHint", domain)
        data.setdefault("taskTypeHint", task_type)
        data["rawIntent"] = intent
        data["requiredCapabilities"] = self._normalize_capabilities(
            data.get("requiredCapabilities") or [],
            domain=domain,
        )
        if not data["requiredCapabilities"] and declared_capabilities:
            data["requiredCapabilities"] = self._normalize_capabilities(
                declared_capabilities,
                domain=domain,
            )
        data["capabilityCandidates"] = [
            CapabilityCandidate(
                capabilityId=capability_id,
                score=1.0,
                matchedTerms=[],
                source="llm",
            ).model_dump(by_alias=True)
            for capability_id in data["requiredCapabilities"]
        ]
        profile = TaskSemanticProfile.model_validate(data)
        if not profile.primary_goal.strip() or not profile.required_capabilities:
            raise ValueError("LLM returned no executable registered capability")
        return self._finalize(profile, intent=intent, domain=domain, task_type=task_type, task_input=task_input)

    def build_prompt(
        self,
        *,
        intent: str,
        domain: str,
        task_type: str,
        task_input: Mapping[str, Any] | None = None,
    ) -> str:
        """构造供 ``IntentLLM`` 使用的受限 JSON 解析提示，不执行模型调用。"""
        options = "\n".join(
            "- " + json.dumps({
                "capabilityId": item.capability_id,
                "displayName": item.display_name,
                "purpose": item.prompt_profile.purpose,
                "whenToUse": item.prompt_profile.when_to_use,
                "whenNotToUse": item.prompt_profile.when_not_to_use,
                "outputType": list(item.output_contract.get("properties", {})),
                "qualityCriteria": item.prompt_profile.quality_criteria,
                "promptProfileVersion": item.prompt_profile.prompt_profile_version,
            }, ensure_ascii=False)
            for item in self.capability_catalog.available(domain)
        )
        contract = self._planning_contract(intent, task_input)
        return (
            f"提示版本：{INTENT_PROFILE_PROMPT_VERSION}\n"
            "你是任务规划的意图解析器。只返回 JSON。\n"
            "从下列目录选择实际需要执行的稳定 capabilityId，不得创造目录外能力。\n"
            f"可选执行能力：\n{options}\n\n"
            "返回 primaryGoal、keyConstraints、requiredCapabilities、expectedArtifacts、"
            "verificationRequirements、estimatedComplexity、domainHint、taskTypeHint、"
            "implicitRequirements、riskLevel。\n"
            "复杂度只描述约束与工作结构，不按文字长度判断；最终分级会由确定性六维评分校验。\n"
            f"领域提示：{domain}\n任务类型提示：{task_type}\n"
            f"任务契约：{json.dumps(contract, ensure_ascii=False, default=str)}\n"
        )

    def _heuristic(
        self,
        intent: str,
        domain: str,
        task_type: str,
        task_input: Mapping[str, Any] | None = None,
    ) -> TaskSemanticProfile:
        text = intent or ""
        candidates = self._infer_capability_candidates(text, domain)
        capabilities = [candidate.capability_id for candidate in candidates]
        contract = self._planning_contract(text, task_input)
        assessment = assess_complexity(
            intent=text,
            task_input=contract,
            profile_data={"requiredCapabilities": capabilities},
        )
        profile = TaskSemanticProfile(
            primaryGoal=str(contract.get("objective") or text[:80] or task_type),
            keyConstraints=[str(item) for item in contract.get("constraints", [])],
            requiredCapabilities=capabilities,
            capabilityCandidates=candidates,
            expectedArtifacts=(
                [str(item) for item in contract.get("expectedArtifacts", [])]
                or (["deliverable"] if "artifact_generation" in capabilities else [])
            ),
            verificationRequirements=["verification"] if "verification" in capabilities else [],
            estimatedComplexity=assessment.level,
            complexityAssessment=assessment,
            domainHint=domain,
            taskTypeHint=task_type,
            riskLevel="normal",
            rawIntent=text,
        )
        return self._finalize(profile, intent=text, domain=domain, task_type=task_type, task_input=task_input)

    def _finalize(
        self,
        profile: TaskSemanticProfile,
        *,
        intent: str,
        domain: str,
        task_type: str,
        task_input: Mapping[str, Any] | None = None,
    ) -> TaskSemanticProfile:
        normalized = self._normalize_capabilities(profile.required_capabilities, domain=domain)
        if not normalized:
            normalized = list(_NATIVE_FALLBACK)
        explicit_capabilities = set(normalized)
        profile.required_capabilities = self.capability_catalog.expand_dependencies(normalized)
        by_capability = {
            candidate.capability_id: candidate for candidate in profile.capability_candidates
        }
        profile.capability_candidates = [
            by_capability.get(capability_id)
            or CapabilityCandidate(
                capabilityId=capability_id,
                score=1.0,
                matchedTerms=[],
                source=(
                    "dependency"
                    if capability_id not in explicit_capabilities
                    else "fallback"
                    if capability_id in _NATIVE_FALLBACK
                    else "catalog_alias"
                ),
            )
            for capability_id in profile.required_capabilities
        ]
        profile.risk_level = highest_planning_risk_level(
            [
                profile.risk_level,
                *(
                    self.capability_catalog.get(capability).risk_level_hint
                    for capability in profile.required_capabilities
                ),
            ]
        )
        profile.primary_goal = profile.primary_goal.strip() or (intent or task_type or "Unnamed task")[:80]
        profile.domain_hint = profile.domain_hint or domain
        profile.task_type_hint = profile.task_type_hint or task_type
        profile.raw_intent = profile.raw_intent or intent
        contract = self._planning_contract(intent, task_input)
        if not profile.key_constraints:
            profile.key_constraints = [str(item) for item in contract.get("constraints", [])]
        if not profile.expected_artifacts:
            profile.expected_artifacts = [str(item) for item in contract.get("expectedArtifacts", [])]
        assessment = assess_complexity(
            intent=intent,
            task_input=contract,
            profile_data=profile.model_dump(by_alias=True),
        )
        profile.estimated_complexity = assessment.level
        profile.complexity_assessment = assessment
        return profile

    @staticmethod
    def _planning_contract(intent: str, task_input: Mapping[str, Any] | None) -> dict[str, Any]:
        payload = dict(task_input or {})
        contract: dict[str, Any] = {
            "objective": payload.get("objective") or payload.get("userIntent") or intent,
            "constraints": payload.get("constraints") or [],
            "expectedArtifacts": payload.get("expectedArtifacts") or [],
        }
        for key in ("materials", "sourceMaterials", "materialRefs", "materialText", "contractText"):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                contract[key] = value
        return contract

    def _infer_capabilities(self, text: str, domain: str) -> list[str]:
        return [
            candidate.capability_id
            for candidate in self._infer_capability_candidates(text, domain)
        ]

    def _infer_capability_candidates(
        self, text: str, domain: str
    ) -> list[CapabilityCandidate]:
        normalized_text = "".join(text.lower().split())
        matches: list[CapabilityCandidate] = []
        for descriptor in self.capability_catalog.available(domain):
            matched_terms = [
                term
                for term in descriptor.aliases
                if (term_normalized := "".join(term.lower().split()))
                and term_normalized in normalized_text
            ]
            if matched_terms:
                longest = max(len("".join(term.split())) for term in matched_terms)
                score = min(1.0, 0.6 + 0.08 * len(matched_terms) + longest / 200)
                matches.append(
                    CapabilityCandidate(
                        capabilityId=descriptor.capability_id,
                        score=round(score, 4),
                        matchedTerms=matched_terms,
                        source="catalog_alias",
                    )
                )

        if domain.strip().lower() == "general":
            specialized = [
                item for item in matches if item.capability_id not in _NATIVE_FALLBACK
            ]
            if not specialized:
                return [
                    CapabilityCandidate(
                        capabilityId=capability_id,
                        score=1.0,
                        matchedTerms=[],
                        source="fallback",
                    )
                    for capability_id in _NATIVE_FALLBACK
                ]
            matches = [
                CapabilityCandidate(
                    capabilityId="task_understanding",
                    score=1.0,
                    matchedTerms=[],
                    source="fallback",
                ),
                *specialized,
            ]
            if "artifact_generation" not in {
                item.capability_id for item in matches
            }:
                matches.append(
                    CapabilityCandidate(
                        capabilityId="artifact_generation",
                        score=1.0,
                        matchedTerms=[],
                        source="fallback",
                    )
                )
        normalized = self._normalize_capabilities(
            [item.capability_id for item in matches], domain=domain
        )
        by_capability = {item.capability_id: item for item in matches}
        return [by_capability[item] for item in normalized]

    def _normalize_capabilities(self, values, *, domain: str) -> list[str]:
        available = {
            descriptor.capability_id
            for descriptor in self.capability_catalog.available(domain)
        }
        normalized: list[str] = []
        for value in values:
            try:
                descriptor = self.capability_catalog.resolve(str(value))
            except KeyError:
                continue
            if descriptor.capability_id in available and descriptor.capability_id not in normalized:
                normalized.append(descriptor.capability_id)
        return normalized


__all__ = ["INTENT_PROFILE_PROMPT_VERSION", "IntentParser", "IntentLLM", "TaskSemanticProfile"]
