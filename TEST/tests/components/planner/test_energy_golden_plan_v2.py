from __future__ import annotations

from components.planner.task_decomposer import TaskDecomposer
from support.acg.models import ComplexityLevel, TaskSemanticProfile, build_default_capability_catalog


class _EnergyPlanLLM:
    def generate_json(self, _prompt: str, _schema: dict, **_kwargs) -> dict:
        definitions = [
            ("understand", "Clarify optimization boundary", "task_understanding"),
            ("load", "Analyze load profile and peak demand", "analysis"),
            ("solar", "Analyze photovoltaic generation profile", "analysis"),
            ("critical", "Define critical-load protection requirements", "requirement_analysis"),
            ("metering", "Design metering and data acquisition", "architecture_design"),
            ("response", "Design demand response candidate", "solution_design"),
            ("storage", "Design storage dispatch candidate", "solution_design"),
            ("charging", "Design managed charging candidate", "solution_design"),
            ("control", "Decompose control sequence and quality gates", "process_decomposition"),
            ("economics-response", "Calculate demand response economics", "cost_analysis"),
            ("economics-storage", "Calculate storage lifecycle economics", "cost_analysis"),
            ("economics-charging", "Calculate charging control economics", "cost_analysis"),
            ("retrieve", "Retrieve evidence for common comparison criteria", "information_retrieval"),
            ("evidence", "Assess retrieved evidence for common criteria", "evidence_analysis"),
            ("compare", "Compare three candidates with common criteria", "comparative_analysis"),
            ("ems", "Design EMS component and interface architecture", "architecture_design"),
            ("dataflow", "Analyze operational data flow and evidence lineage", "analysis"),
            ("resources", "Plan implementation resources and capacity", "resource_planning"),
            ("implementation", "Synthesize phased implementation plan", "solution_design"),
            ("safety", "Assess safety and operational risks", "risk_analysis"),
            ("acceptance", "Verify every acceptance criterion with evidence", "verification"),
            ("deliver", "Generate the complete optimization deliverable", "artifact_generation"),
        ]
        tasks = [{
            "key": key,
            "title": title,
            "objective": title + " using mission facts and explicit assumptions",
            "capabilityId": capability,
            "acceptanceCriteria": [title + " has a traceable, testable output"],
            "sourceRefs": ["energy optimization report", "budget cap", "critical-load continuity"],
            "decompositionRationale": "independently verifiable coverage item",
            "logicalRole": "task",
        } for key, title, capability in definitions]
        relations = []
        for target in ("load", "solar", "critical", "response", "storage", "charging", "control", "retrieve"):
            relations.append({"sourceKey": "understand", "targetKey": target, "relationType": "depends_on"})
        relations.extend(
            {"sourceKey": source, "targetKey": target, "relationType": "depends_on"}
            for source, target in (
                ("response", "economics-response"), ("storage", "economics-storage"),
                ("charging", "economics-charging"), ("economics-response", "compare"),
                ("economics-storage", "compare"), ("economics-charging", "compare"),
                ("retrieve", "evidence"), ("evidence", "compare"),
                ("metering", "ems"), ("critical", "control"), ("ems", "dataflow"),
                ("control", "dataflow"), ("compare", "resources"), ("compare", "implementation"),
                ("dataflow", "implementation"), ("implementation", "safety"),
                ("resources", "acceptance"), ("safety", "acceptance"),
                ("acceptance", "deliver"),
            )
        )
        return {"tasks": tasks, "relations": relations}


def test_energy_golden_plan_has_business_tasks_parallel_branches_and_joins() -> None:
    catalog = build_default_capability_catalog()
    capabilities = [
        "task_understanding", "analysis", "architecture_design", "solution_design",
        "requirement_analysis", "cost_analysis", "comparative_analysis",
        "process_decomposition", "evidence_analysis", "resource_planning",
        "risk_analysis", "verification", "artifact_generation",
    ]
    profile = TaskSemanticProfile(
        primaryGoal="Optimize an industrial energy system",
        keyConstraints=["budget cap", "critical-load continuity"],
        expectedArtifacts=["energy optimization report"],
        requiredCapabilities=capabilities,
        estimatedComplexity=ComplexityLevel.COMPLEX,
    )
    plan = TaskDecomposer(catalog, _EnergyPlanLLM()).decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert plan.metadata["degraded"] is False
    assert 18 <= len(plan.nodes) <= 26
    assert sum(node.capability_requirements == ("solution_design",) for node in plan.nodes) >= 3
    incoming: dict[str, int] = {node.key: 0 for node in plan.nodes}
    outgoing: dict[str, int] = {node.key: 0 for node in plan.nodes}
    for relation in plan.relations:
        outgoing[relation.source_key] += 1
        incoming[relation.target_key] += 1
    assert sum(count >= 3 for count in outgoing.values()) >= 1
    assert sum(count >= 2 for count in incoming.values()) >= 2
    assert all(node.acceptance_criteria and node.objective for node in plan.nodes)
