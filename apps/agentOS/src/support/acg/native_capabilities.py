"""Core-owned native capability declarations."""

from __future__ import annotations

from .capabilities import (
    CapabilityCatalog, CapabilityPromptProfile, PlanningCapabilityDescriptor,
)

def build_default_capability_catalog() -> CapabilityCatalog:
    """创建并校验内置能力目录；每次调用返回独立实例，不共享可变注册状态。"""
    catalog = CapabilityCatalog()
    register_native_capabilities(catalog)
    catalog.validate()
    return catalog


"""Core-owned, bounded capability contribution for native domain-neutral tasks."""


# 同文件定义的能力描述合同在运行时按名称解析。


def _schema(*required: str) -> dict:
    return {
        "type": "object",
        "properties": {name: {} for name in required},
        "required": list(required),
    }


def _record(properties: dict, *required: str) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
    }


def _records(properties: dict, *required: str, max_items: int | None = None) -> dict:
    schema = {
        "type": "array",
        "items": _record(properties, *required),
    }
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


_TEXT = {"type": "string"}
_DELIVERABLE_TEXT = {"type": "string", "minLength": 1}


def _text_list(*, max_items: int | None = None, max_length: int | None = None) -> dict:
    item_schema: dict[str, object] = {"type": "string"}
    if max_length is not None:
        item_schema["maxLength"] = max_length
    schema: dict[str, object] = {
        "type": "array",
        "items": item_schema,
    }
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


_TEXT_LIST = _text_list()


def _output_schema(capability_id: str) -> dict:
    schemas = {
        "task_understanding": _record(
            {
                "task_summary": _TEXT,
                "constraints": _records(
                    {"constraint": _TEXT, "source": _TEXT, "mandatory": {"type": "boolean"}},
                    "constraint",
                    "source",
                    "mandatory",
                ),
                "success_criteria": _text_list(),
                "assumptions": _TEXT_LIST,
                "open_questions": _TEXT_LIST,
            },
            "task_summary",
            "constraints",
        ),
        "information_extraction": _record(
            {
                "extracted_information": _record(
                    {
                        "facts": _records(
                            {"name": _TEXT, "value": {}, "source": _TEXT},
                            "name",
                            "value",
                            "source",
                        ),
                        "metrics": _records(
                            {"name": _TEXT, "value": {}, "unit": _TEXT, "source": _TEXT},
                            "name",
                            "value",
                            "unit",
                            "source",
                        ),
                        "entities": _TEXT_LIST,
                        "unknowns": _TEXT_LIST,
                    },
                    "facts",
                    "metrics",
                    "entities",
                    "unknowns",
                )
            },
            "extracted_information",
        ),
        "information_retrieval": _record(
            {
                "retrieved_information": _TEXT_LIST,
                "evidence_refs": _TEXT_LIST,
                "sources": {"type": "array", "items": {"type": "object"}},
                "retrieval_mode": _TEXT,
            },
            "retrieved_information",
            "evidence_refs",
        ),
        "requirement_analysis": _record(
            {
                "requirements": _records(
                    {"id": _TEXT, "requirement": _TEXT, "priority": _TEXT, "source": _TEXT},
                    "id",
                    "requirement",
                    "priority",
                    "source",
                ),
                "acceptance_criteria": _records(
                    {"requirement_id": _TEXT, "criterion": _TEXT, "metric": _TEXT, "target": _TEXT},
                    "requirement_id",
                    "criterion",
                    "metric",
                    "target",
                ),
                "assumptions": _TEXT_LIST,
                "open_questions": _TEXT_LIST,
            },
            "requirements",
            "acceptance_criteria",
        ),
        "process_decomposition": _record(
            {
                "process_steps": _records(
                    {
                        "id": _TEXT,
                        "name": _TEXT,
                        "inputs": _TEXT_LIST,
                        "activities": _TEXT_LIST,
                        "outputs": _TEXT_LIST,
                        "owner": _TEXT,
                        "quality_gate": _TEXT,
                    },
                    "id",
                    "name",
                    "inputs",
                    "activities",
                    "outputs",
                    "owner",
                    "quality_gate",
                )
            },
            "process_steps",
        ),
        "resource_planning": _record(
            {
                "resource_plan": _record(
                    {"people": _TEXT_LIST, "equipment": _TEXT_LIST, "systems": _TEXT_LIST, "materials": _TEXT_LIST},
                    "people",
                    "equipment",
                    "systems",
                    "materials",
                ),
                "capacity_plan": _record(
                    {"assumptions": _TEXT_LIST, "calculations": _TEXT_LIST, "conclusion": _TEXT},
                    "assumptions",
                    "calculations",
                    "conclusion",
                ),
            },
            "resource_plan",
            "capacity_plan",
        ),
        "architecture_design": _record(
            {
                "architecture": _record({"style": _TEXT, "rationale": _TEXT, "deployment": _TEXT}, "style", "rationale", "deployment"),
                "components": _records({"name": _TEXT, "responsibility": _TEXT, "interfaces": _TEXT_LIST}, "name", "responsibility", "interfaces"),
                "data_flow": _records({"source": _TEXT, "target": _TEXT, "data": _TEXT, "controls": _TEXT_LIST}, "source", "target", "data", "controls"),
            },
            "architecture",
            "components",
            "data_flow",
        ),
        "analysis": _record(
            {
                "analysis": _record(
                    {
                        "findings": _text_list(),
                        "assumptions": {
                            **_text_list(),
                            "default": [],
                        },
                        "gaps": {
                            **_text_list(),
                            "default": [],
                        },
                    },
                    "findings",
                    "assumptions",
                    "gaps",
                )
            },
            "analysis",
        ),
        "evidence_analysis": _record(
            {"evidence_analysis": _records({"claim": _TEXT, "evidence_ref": _TEXT, "assessment": _TEXT, "confidence": {"type": "number"}}, "claim", "evidence_ref", "assessment", "confidence"), "evidence_refs": _TEXT_LIST},
            "evidence_analysis",
            "evidence_refs",
        ),
        "comparative_analysis": _record(
            {"comparison": _record({"criteria": _TEXT_LIST, "scores": {"type": "array", "items": {"type": "object"}}, "recommendation": _TEXT}, "criteria", "scores", "recommendation"), "alternatives": _records({"name": _TEXT, "advantages": _TEXT_LIST, "disadvantages": _TEXT_LIST}, "name", "advantages", "disadvantages")},
            "comparison",
            "alternatives",
        ),
        "cost_analysis": _record(
            {"cost_analysis": _record({"currency": _TEXT, "items": _records({"item": _TEXT, "amount": {"type": "number"}, "basis": _TEXT}, "item", "amount", "basis"), "total": {"type": "number"}, "assumptions": _TEXT_LIST}, "currency", "items", "total", "assumptions"), "cost_drivers": _TEXT_LIST},
            "cost_analysis",
            "cost_drivers",
        ),
        "risk_analysis": _record(
            {"risk_analysis": _record({"summary": _TEXT, "overall_level": _TEXT}, "summary", "overall_level"), "risks": _records({"risk": _TEXT, "probability": _TEXT, "impact": _TEXT, "trigger": _TEXT, "owner": _TEXT, "mitigation": _TEXT}, "risk", "probability", "impact", "trigger", "owner", "mitigation")},
            "risk_analysis",
            "risks",
        ),
        "solution_design": _record(
            {"solution_design": _record({"overview": _TEXT, "phases": _records({"name": _TEXT, "milestones": _TEXT_LIST, "dependencies": _TEXT_LIST, "deliverables": _TEXT_LIST}, "name", "milestones", "dependencies", "deliverables")}, "overview", "phases")},
            "solution_design",
        ),
        "verification": _record(
            {"verification": _record({"status": {"type": "string", "enum": ["passed", "partial", "failed"]}, "checks": _records({"criterion": _TEXT, "result": _TEXT, "evidence": _TEXT}, "criterion", "result", "evidence"), "unresolved_gaps": _TEXT_LIST}, "status", "checks", "unresolved_gaps")},
            "verification",
        ),
        "artifact_generation": _record(
            {
                "deliverable": _record(
                    {
                        "title": _TEXT,
                        "executiveSummary": _TEXT,
                        "sections": _records(
                            {"title": _TEXT, "content": _TEXT, "sourceFields": _TEXT_LIST},
                            "title",
                            "content",
                            "sourceFields",
                        ),
                        "calculations": _records(
                            {"name": _TEXT, "formula": _TEXT, "inputs": _TEXT_LIST, "result": _TEXT, "assumptions": _TEXT_LIST},
                            "name",
                            "formula",
                            "inputs",
                            "result",
                            "assumptions",
                        ),
                        "assumptions": _TEXT_LIST,
                        "openQuestions": _TEXT_LIST,
                        "sourceRefs": _TEXT_LIST,
                    },
                    "title",
                    "executiveSummary",
                    "sections",
                    "calculations",
                    "assumptions",
                    "openQuestions",
                    "sourceRefs",
                ),
                "final_answer": _DELIVERABLE_TEXT,
                "verification": _record(
                    {
                        "status": {"type": "string", "enum": ["passed", "partial", "failed"]},
                        "checks": _records(
                            {"criterion": _TEXT, "result": _TEXT, "evidence": _TEXT},
                            "criterion",
                            "result",
                            "evidence",
                        ),
                        "unresolvedGaps": _TEXT_LIST,
                    },
                    "status",
                    "checks",
                    "unresolvedGaps",
                ),
                "artifact": _record(
                    {"artifactId": _TEXT, "artifactKey": _TEXT, "artifactType": _TEXT, "type": {"type": "string", "enum": ["report", "primary_artifact", "supporting_artifact", "run_deliverable"]}, "title": _TEXT, "mediaType": {"type": "string", "enum": ["text/markdown"]}, "content": _DELIVERABLE_TEXT, "structuredData": {"type": "object"}, "manifestId": _TEXT, "checksum": _TEXT, "metadata": {"type": "object"}},
                    "artifactId",
                    "type",
                    "title",
                    "mediaType",
                    "content",
                    "structuredData",
                ),
                "artifacts": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "deliverable",
            "final_answer",
            "verification",
            "artifact",
        ),
    }
    return schemas[capability_id]


def native_capability_descriptors() -> tuple[PlanningCapabilityDescriptor, ...]:
    """返回内置通用能力描述符的有序不可变集合，供目录初始化或测试比较。"""
    general = ["general"]
    descriptors = (
        PlanningCapabilityDescriptor(
            capabilityId="task_understanding", displayName="任务理解",
            aliases=["理解任务", "任务目标", "目标", "约束"], planningStage="understand",
            outputContract=_output_schema("task_understanding"), parallelizable=False,
            domainHints=general, priority=10,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="information_extraction", displayName="信息提取",
            aliases=["信息提取", "抽取", "要素梳理"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("information_extraction"), domainHints=general, priority=20,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="information_retrieval", displayName="资料检索",
            aliases=["资料梳理", "资料检索", "信息检索", "调研", "文献"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("information_retrieval"),
            requiresEvidence=True, domainHints=general, priority=21,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="requirement_analysis", displayName="需求分析",
            aliases=["需求", "需求分析", "验收条件", "功能要求"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("requirement_analysis"),
            writesMemory=True, domainHints=general, priority=22,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="process_decomposition", displayName="流程拆解",
            aliases=["工序", "流程拆解", "流程规划", "步骤拆解", "生产流程"], planningStage="decompose",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("process_decomposition"), writesMemory=True,
            domainHints=general, priority=23,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="resource_planning", displayName="资源规划",
            aliases=["资源", "设备资源", "人员配置", "产能"], planningStage="analyze",
            dependsOn=["process_decomposition"], inputContract=_schema("process_steps"),
            outputContract=_output_schema("resource_planning"),
            domainHints=general, priority=30,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="architecture_design", displayName="架构设计",
            aliases=["系统架构", "技术架构", "架构设计", "组件", "接口", "数据流"],
            planningStage="analyze", dependsOn=["requirement_analysis"],
            inputContract=_schema("requirements"),
            outputContract=_output_schema("architecture_design"),
            writesMemory=True, domainHints=general, priority=31,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="analysis", displayName="通用分析",
            aliases=["分析", "评估"], planningStage="analyze",
            dependsOn=["task_understanding"], inputContract=_schema("task_summary"),
            outputContract=_output_schema("analysis"), domainHints=general, priority=32,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="evidence_analysis", displayName="证据分析",
            aliases=["证据分析", "依据分析", "资料分析"], planningStage="analyze",
            dependsOn=["information_retrieval"], inputContract=_schema("retrieved_information"),
            outputContract=_output_schema("evidence_analysis"),
            requiresEvidence=True, writesMemory=True, domainHints=general, priority=33,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="comparative_analysis", displayName="比较分析",
            aliases=["方案比较", "对比分析", "比较", "备选方案"], planningStage="analyze",
            dependsOn=["evidence_analysis"], inputContract=_schema("evidence_analysis"),
            outputContract=_output_schema("comparative_analysis"),
            domainHints=general, priority=34,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="cost_analysis", displayName="成本分析",
            aliases=["成本", "预算", "费用"], planningStage="analyze",
            dependsOn=["process_decomposition"], inputContract=_schema("process_steps"),
            outputContract=_output_schema("cost_analysis"),
            domainHints=general, priority=35,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="risk_analysis", displayName="风险分析",
            aliases=["风险", "安全风险", "风险分析", "风险控制"], planningStage="analyze",
            dependsOn=["task_understanding"],
            optionalDependencies=["requirement_analysis", "process_decomposition", "architecture_design"],
            inputContract=_schema("task_summary"), outputContract=_output_schema("risk_analysis"),
            writesMemory=True, riskLevelHint="high", domainHints=general, priority=36,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="solution_design", displayName="方案设计",
            aliases=["解决方案", "方案设计", "实施方案"], planningStage="synthesize",
            dependsOn=["analysis"], optionalDependencies=["requirement_analysis", "process_decomposition", "architecture_design"],
            inputContract=_schema("analysis"), outputContract=_output_schema("solution_design"),
            producesArtifact=True, writesMemory=True, domainHints=general, priority=40,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="verification", displayName="验证",
            aliases=["验证", "验收", "质量控制", "结论验证", "测试方式"], planningStage="verify",
            dependsOn=["task_understanding"],
            optionalDependencies=["requirement_analysis", "process_decomposition", "resource_planning", "architecture_design", "analysis", "comparative_analysis", "evidence_analysis", "cost_analysis", "risk_analysis", "solution_design"],
            inputContract=_schema("task_summary"), outputContract=_output_schema("verification"),
            parallelizable=False, domainHints=general, priority=50,
        ),
        PlanningCapabilityDescriptor(
            capabilityId="artifact_generation", displayName="成果生成",
            aliases=["报告", "方案", "交付物", "文档"], planningStage="deliver",
            dependsOn=["task_understanding"],
            optionalDependencies=["information_extraction", "information_retrieval", "requirement_analysis", "process_decomposition", "resource_planning", "architecture_design", "analysis", "comparative_analysis", "evidence_analysis", "cost_analysis", "risk_analysis", "solution_design", "verification"],
            # A Run deliverable consumes the declared leaf outputs as a
            # multi-source ContextPack.  Mission/task facts are already present
            # in the runtime request, so no single upstream field is mandatory.
            inputContract=_schema(),
            outputContract=_output_schema("artifact_generation"),
            producesArtifact=True, writesMemory=True, parallelizable=False,
            domainHints=general, priority=60,
        ),
    )
    purposes = {
        "task_understanding": "Turn the mission into explicit goals, constraints, artifacts, facts, assumptions and unknowns.",
        "information_extraction": "Extract traceable facts, entities and metrics from supplied materials without adding facts.",
        "information_retrieval": "Retrieve missing information with source references and an explicit evidence boundary.",
        "requirement_analysis": "Translate stakeholder needs and hard constraints into testable requirements and acceptance criteria.",
        "process_decomposition": "Describe an executable process with inputs, outputs, ownership, dependencies and quality gates.",
        "resource_planning": "Estimate people, systems, equipment and capacity with assumptions and calculations.",
        "architecture_design": "Define components, interfaces, deployment boundaries and controlled data flows.",
        "analysis": "Analyze a bounded question and separate findings, assumptions and unresolved gaps.",
        "evidence_analysis": "Assess claims against cited evidence and state confidence and evidence gaps.",
        "comparative_analysis": "Compare independently produced alternatives against consistent criteria and explain the recommendation.",
        "cost_analysis": "Calculate costs from explicit quantities, rates, units, formulas and assumptions.",
        "risk_analysis": "Identify risks, triggers, probability, impact, ownership and mitigations.",
        "solution_design": "Design one coherent candidate solution with phases, dependencies, milestones and deliverables.",
        "verification": "Verify acceptance criteria against evidence; never pass a criterion without supporting evidence.",
        "artifact_generation": "Synthesize verified outputs into the requested artifacts while preserving gaps and source references.",
    }
    policy_overrides = {
        "task_understanding": ["Separate the explicit mission, constraints, success criteria, assumptions and open questions."],
        "information_extraction": ["Map every extracted item to supplied source content and preserve conflicting values."],
        "information_retrieval": ["Retrieve only through runtime-authorized tools and preserve source identity and retrieval gaps."],
        "requirement_analysis": ["Make each requirement testable and trace it to a stakeholder need or mission constraint."],
        "process_decomposition": ["Define steps with inputs, outputs, ownership, dependencies and quality gates without inventing execution."],
        "resource_planning": ["State capacity basis, units, utilization assumptions, bottlenecks and missing resource inputs."],
        "architecture_design": ["Define component boundaries, interfaces, data ownership, dependency direction, failure boundaries and trade-offs; mark unsupported components as assumptions."],
        "analysis": ["Keep findings within the bounded question and distinguish observations, derivations and unresolved gaps."],
        "evidence_analysis": ["Map each claim to evidence, assess source quality, conflicts, coverage and unresolved contradictions."],
        "comparative_analysis": ["Apply the same criteria and evidence standard to every alternative and disclose missing data before ranking."],
        "cost_analysis": ["For every cost state the calculation basis, formula, inputs, units, assumptions, result and source; missing prices or rates remain unknown."],
        "risk_analysis": ["For every risk distinguish cause, trigger, impact, likelihood basis, mitigation, residual risk and evidence; never fabricate probabilities."],
        "solution_design": ["Trace the design to requirements, constraints, interfaces, resources, risks and a verification path; add no out-of-scope features."],
        "verification": ["Evaluate the candidate without repairing it; a passed criterion requires supporting evidence independent of the candidate's own assertion."],
        "artifact_generation": ["Let expected artifacts and the output contract determine structure; synthesize supported content without inventing universal report sections."],
    }
    evidence_overrides = {
        "evidence_analysis": "Assess claim-to-evidence coverage, source quality and conflicts; source existence alone does not prove a claim.",
        "comparative_analysis": "Use equivalent evidence standards for every alternative and expose missing-data asymmetry.",
        "cost_analysis": "Cite the source of each input or label it as an assumption or missing input.",
        "risk_analysis": "Cite the basis for likelihood and impact; otherwise keep them qualitative or unknown.",
        "verification": "A passed result requires evidence for every passed check; candidate self-attestation is insufficient.",
        "artifact_generation": "Preserve source and upstream artifact references and distinguish verified evidence from agent-generated conclusions.",
    }
    return tuple(
        descriptor.model_copy(update={
            "description": purposes[descriptor.capability_id],
            "prompt_profile": CapabilityPromptProfile(
                profileId=descriptor.capability_id,
                promptProfileVersion="capability-profile.v2",
                purpose=purposes[descriptor.capability_id],
                whenToUse=[f"The planned task primarily needs {descriptor.display_name}."],
                whenNotToUse=["Another capability owns the primary output; use this only for a distinct task."],
                decompositionHints=["Create separate instances when alternatives, stages or independently verifiable outputs differ."],
                executionPrinciples=[
                    "Use only mission facts, allowlisted context and tool-returned evidence.",
                    "Separate known facts, derivations, assumptions and unknowns.",
                    *policy_overrides[descriptor.capability_id],
                ],
                qualityCriteria=[
                    "The output directly satisfies the planned task goal and every acceptance criterion.",
                    "Claims and calculations remain traceable to inputs, evidence or declared assumptions.",
                ],
                verificationQuestions=[
                    "Is every acceptance criterion answered?",
                    "Are unsupported claims marked as assumptions or unknowns?",
                ],
                requiredTools=(
                    ["knowledge_search"]
                    if descriptor.capability_id == "information_retrieval"
                    else []
                ),
                evidencePolicy=(
                    evidence_overrides.get(
                        descriptor.capability_id,
                        "Use only supplied or tool-returned evidence and cite it when making a factual claim.",
                    )
                ),
            ),
        })
        for descriptor in descriptors
    )


NATIVE_CAPABILITY_IDS = tuple(
    descriptor.capability_id for descriptor in native_capability_descriptors()
)


def register_native_capabilities(catalog: CapabilityCatalog) -> None:
    """按内置声明顺序注册能力到给定目录；直接修改该目录并沿用其冲突校验。"""
    for descriptor in native_capability_descriptors():
        catalog.register(descriptor)


"""任务语义画像。

意图解析模块的产物，是后续认知路由与 ACG 构建的统一输入。
"""


from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "NATIVE_CAPABILITY_IDS", "build_default_capability_catalog",
    "native_capability_descriptors", "register_native_capabilities",
]
