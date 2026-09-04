"""Capability contracts for industrial project design."""

from support.acg.models import CapabilityCatalog, CapabilityPromptProfile, PlanningCapabilityDescriptor


TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}
ROWS = {"type": "array", "items": {"type": "object"}}


def _profile(capability_id: str, purpose: str, *, tools: list[str] | None = None) -> CapabilityPromptProfile:
    return CapabilityPromptProfile(
        profileId=capability_id,
        promptProfileVersion="industrial-capability.v1",
        purpose=purpose,
        whenToUse=[purpose],
        whenNotToUse=["Do not invent plant measurements, supplier facts, standards or prices."],
        decompositionHints=["Separate alternatives or independently verifiable production stages."],
        executionPrinciples=[
            "Keep units explicit and preserve every assumption.",
            "Distinguish measured facts, calculations, engineering judgement and evidence gaps.",
        ],
        qualityCriteria=[
            "Every conclusion is traceable to an input, formula, cited source or declared assumption.",
            "The output can be reviewed by an industrial engineer without hidden calculations.",
        ],
        verificationQuestions=["Are units and formulas consistent?", "Are safety and acceptance gaps explicit?"],
        requiredTools=tools or [],
    )


def _descriptor(
    capability_id: str,
    display_name: str,
    purpose: str,
    *,
    stage: str,
    depends_on: list[str],
    required: list[str],
    properties: dict,
    risk: str = "normal",
    review: bool = False,
    artifact: bool = False,
    parallel: bool = True,
) -> PlanningCapabilityDescriptor:
    return PlanningCapabilityDescriptor(
        capabilityId=capability_id,
        displayName=display_name,
        aliases=[display_name, purpose],
        description=purpose,
        promptProfile=_profile(capability_id, purpose),
        planningStage=stage,
        dependsOn=depends_on,
        inputContract={"type": "object"},
        outputContract={"type": "object", "properties": properties, "required": required},
        producesArtifact=artifact,
        requiresEvidence=capability_id in {
            "industrial_safety_analysis", "industrial_acceptance_validation"
        },
        writesMemory=True,
        requiresReview=review,
        riskLevelHint=risk,
        parallelizable=parallel,
        domainHints=["industrial"],
        priority=40,
    )


def industrial_capabilities() -> tuple[PlanningCapabilityDescriptor, ...]:
    return (
        _descriptor(
            "industrial_capacity_analysis", "产能与节拍分析",
            "Calculate takt, cycle time, OEE, capacity, bottlenecks and buffers with explicit units and formulas.",
            stage="analyze", depends_on=["requirement_analysis", "process_decomposition"],
            required=["capacity_model", "calculations", "bottlenecks", "assumptions"],
            properties={"capacity_model": {"type": "object"}, "calculations": ROWS, "bottlenecks": ROWS, "assumptions": TEXTS},
        ),
        _descriptor(
            "industrial_station_design", "工位与产线设计",
            "Design station boundaries, work content, equipment, staffing, quality gates and balancing alternatives.",
            stage="design", depends_on=["industrial_capacity_analysis"],
            required=["stations", "balance", "alternatives"],
            properties={"stations": ROWS, "balance": {"type": "object"}, "alternatives": ROWS},
        ),
        _descriptor(
            "industrial_automation_design", "自动化边界与设备集成",
            "Define automation levels, equipment interfaces, controls, sensors, I/O and degraded/manual modes.",
            stage="design", depends_on=["industrial_station_design"],
            required=["automation_scope", "equipment_interfaces", "io_matrix", "fallback_modes"],
            properties={"automation_scope": ROWS, "equipment_interfaces": ROWS, "io_matrix": ROWS, "fallback_modes": ROWS},
        ),
        _descriptor(
            "industrial_layout_logistics", "布局与物流设计",
            "Design material flow, buffers, routes, storage, ergonomics and layout constraints.",
            stage="design", depends_on=["industrial_station_design"],
            required=["layout_zones", "material_flows", "buffers", "assumptions"],
            properties={"layout_zones": ROWS, "material_flows": ROWS, "buffers": ROWS, "assumptions": TEXTS},
        ),
        _descriptor(
            "industrial_ot_it_architecture", "OT/IT与控制架构",
            "Design PLC, robot, SCADA, MES, quality and enterprise integration with controlled data flows.",
            stage="design", depends_on=["industrial_automation_design", "architecture_design"],
            required=["layers", "interfaces", "data_flows", "security_boundaries"],
            properties={"layers": ROWS, "interfaces": ROWS, "data_flows": ROWS, "security_boundaries": ROWS},
        ),
        _descriptor(
            "industrial_safety_analysis", "工业安全与合规分析",
            "Identify machinery, process, ergonomic and cyber-physical hazards and define traceable mitigations.",
            stage="verify", depends_on=["industrial_automation_design", "industrial_layout_logistics"],
            required=["hazards", "risk_controls", "evidence_refs", "gaps"],
            properties={"hazards": ROWS, "risk_controls": ROWS, "evidence_refs": TEXTS, "gaps": TEXTS},
            risk="critical", review=True, parallel=False,
        ),
        _descriptor(
            "industrial_acceptance_validation", "工业验收与验证",
            "Verify throughput, quality, availability, safety, interfaces and deliverables against measurable acceptance criteria.",
            stage="verify", depends_on=["industrial_ot_it_architecture", "industrial_safety_analysis"],
            required=["verification", "acceptance_matrix", "evidence_refs"],
            properties={
                "verification": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["passed", "partial", "failed"]}, "unresolved_gaps": TEXTS},
                    "required": ["status", "unresolved_gaps"],
                },
                "acceptance_matrix": ROWS,
                "evidence_refs": TEXTS,
            },
            risk="critical", review=True, parallel=False,
        ),
        _descriptor(
            "industrial_visualization", "工业图表与交付集成",
            "Produce Mermaid architecture and process diagrams, equipment and I/O tables, KPI matrices and a report-ready design summary.",
            stage="deliver", depends_on=["industrial_acceptance_validation"],
            required=["mermaid_diagrams", "equipment_table", "io_table", "kpi_matrix", "final_answer"],
            properties={"mermaid_diagrams": ROWS, "equipment_table": ROWS, "io_table": ROWS, "kpi_matrix": ROWS, "final_answer": TEXT},
            artifact=True, parallel=False,
        ),
    )


INDUSTRIAL_CAPABILITY_IDS = tuple(item.capability_id for item in industrial_capabilities())


def register_industrial_capabilities(catalog: CapabilityCatalog) -> None:
    for descriptor in industrial_capabilities():
        catalog.register(descriptor)
    catalog.validate()


__all__ = ["INDUSTRIAL_CAPABILITY_IDS", "industrial_capabilities", "register_industrial_capabilities"]
