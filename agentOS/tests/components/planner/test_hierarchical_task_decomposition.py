from __future__ import annotations

import pytest

from components.planner.acg_builder import ACGBuilder
from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
from components.planner.task_decomposer import TASK_DECOMPOSITION_PROMPT_VERSION, TaskDecomposer
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation
from support.acg.models import ComplexityLevel, TaskSemanticProfile, build_default_capability_catalog


class _PlanLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def generate_json(self, prompt: str, schema: dict, **kwargs) -> dict:
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        return self.payload


class _SequencePlanLLM(_PlanLLM):
    def __init__(self, *payloads: dict) -> None:
        super().__init__(payloads[0])
        self.payloads = list(payloads)

    def generate_json(self, prompt: str, schema: dict, **kwargs) -> dict:
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        return self.payloads[len(self.calls) - 1]


def _profile() -> TaskSemanticProfile:
    return TaskSemanticProfile(
        primaryGoal="Produce and compare three independently testable solution candidates",
        requiredCapabilities=[
            "task_understanding", "analysis", "information_retrieval",
            "evidence_analysis", "solution_design", "comparative_analysis",
        ],
        estimatedComplexity=ComplexityLevel.COMPLEX,
        rawIntent="three alternatives and comparison",
    )


def test_repeated_capability_instances_survive_taskplan_and_acg_build() -> None:
    payload = {
        "tasks": [
            {"key": "understand", "title": "Understand", "objective": "Define the mission comparison boundary", "capabilityId": "task_understanding", "acceptanceCriteria": ["Mission boundary is explicit"]},
            {"key": "analyze", "title": "Analyze", "objective": "Analyze common solution assumptions", "capabilityId": "analysis", "acceptanceCriteria": ["Common assumptions are explicit"]},
            {"key": "retrieve", "title": "Retrieve", "objective": "Retrieve comparison evidence", "capabilityId": "information_retrieval", "acceptanceCriteria": ["Evidence references are returned"]},
            {"key": "evidence", "title": "Evidence", "objective": "Assess evidence for comparison criteria", "capabilityId": "evidence_analysis", "acceptanceCriteria": ["Criteria have evidence assessments"]},
            {"key": "candidate-a", "title": "Candidate A", "objective": "Design candidate A against the mission constraints", "capabilityId": "solution_design", "acceptanceCriteria": ["Candidate A has phases and deliverables"], "sourceRefs": ["mission"], "decompositionRationale": "independent alternative", "logicalRole": "alternative"},
            {"key": "candidate-b", "title": "Candidate B", "objective": "Design candidate B against the mission constraints", "capabilityId": "solution_design", "acceptanceCriteria": ["Candidate B has phases and deliverables"], "sourceRefs": ["mission"], "decompositionRationale": "independent alternative", "logicalRole": "alternative"},
            {"key": "candidate-c", "title": "Candidate C", "objective": "Design candidate C against the mission constraints", "capabilityId": "solution_design", "acceptanceCriteria": ["Candidate C has phases and deliverables"], "sourceRefs": ["mission"], "decompositionRationale": "independent alternative", "logicalRole": "alternative"},
            {"key": "compare", "title": "Compare candidates", "objective": "Compare A, B and C with one consistent scoring model", "capabilityId": "comparative_analysis", "acceptanceCriteria": ["All candidates are scored against the same criteria"], "sourceRefs": ["candidate-a", "candidate-b", "candidate-c"], "decompositionRationale": "convergence", "logicalRole": "join"},
        ],
        "relations": [
            {"sourceKey": "understand", "targetKey": "analyze", "relationType": "depends_on"},
            {"sourceKey": "understand", "targetKey": "retrieve", "relationType": "depends_on"},
            {"sourceKey": "retrieve", "targetKey": "evidence", "relationType": "depends_on"},
        ] + [
            {"sourceKey": "analyze", "targetKey": key, "relationType": "depends_on"}
            for key in ("candidate-a", "candidate-b", "candidate-c")
        ] + [
            {"sourceKey": key, "targetKey": "compare", "relationType": "depends_on"}
            for key in ("candidate-a", "candidate-b", "candidate-c")
        ] + [{"sourceKey": "evidence", "targetKey": "compare", "relationType": "depends_on"}],
    }
    llm = _PlanLLM(payload)
    catalog = build_default_capability_catalog()
    plan = TaskDecomposer(catalog, llm).decompose(
        mission_id="mission_0123456789ab",
        profile=_profile(),
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )
    network = CollaborationNetwork(bindings=[
        CapabilityBinding(capability=capability, agent_name="native_general_agent", score=1)
        for capability in _profile().required_capabilities
    ])
    blueprint = ACGBuilder(catalog).build(
        mission_id="mission_0123456789ab",
        profile=_profile(),
        network=network,
        task_plan=plan,
    )
    built = ACGBuilder(catalog).finalize(blueprint=blueprint, task_plan=plan)

    assert [node.capability_requirements[0] for node in plan.nodes].count("solution_design") == 3
    assert [step.name for step in blueprint.step_nodes()][-4:] == ["Candidate A", "Candidate B", "Candidate C", "Compare candidates"]
    assert next(step for step in blueprint.step_nodes() if step.name == "Candidate A").goal.startswith("Design candidate A")
    assert {item.plan_node_key for item in built.bindings} == {node.key for node in plan.nodes}
    assert llm.calls[0]["prompt_version"] == TASK_DECOMPOSITION_PROMPT_VERSION


def test_dependency_cycle_is_rejected() -> None:
    nodes = tuple(
        PlannedTask(key=key, title=key, objective=f"Analyze {key}", capabilityRequirements=("analysis",), acceptanceCriteria=("done",))
        for key in ("a", "b")
    )
    with pytest.raises(ValueError, match="dependency cycle"):
        TaskPlan(
            missionId="mission_0123456789ab",
            nodes=nodes,
            relations=(
                TaskPlanRelation(sourceKey="a", targetKey="b", relationType="depends_on"),
                TaskPlanRelation(sourceKey="b", targetKey="a", relationType="depends_on"),
            ),
        )


def test_failed_contract_raises_after_exactly_one_repair() -> None:
    llm = _PlanLLM({"tasks": [], "relations": []})
    with pytest.raises(Exception, match="TASK_PLAN_VALIDATION_FAILED"):
        TaskDecomposer(build_default_capability_catalog(), llm).decompose(
            mission_id="mission_0123456789ab",
            profile=_profile(),
            strategy="dynamic_generation",
            task_input={},
            use_llm=True,
        )

    assert len(llm.calls) == 2


def test_prompt_exposes_hard_capability_dependencies_and_uses_requirement_wording() -> None:
    llm = _PlanLLM({"tasks": [], "relations": []})
    prompt = TaskDecomposer(build_default_capability_catalog(), llm).build_prompt(
        profile=TaskSemanticProfile(
            primaryGoal="Verify an evidence-backed result",
            requiredCapabilities=["verification"],
            estimatedComplexity=ComplexityLevel.SIMPLE,
        ),
        task_input={},
    )

    assert '"capabilityId": "verification"' in prompt
    assert '"dependsOn": ["task_understanding"]' in prompt
    assert '"capabilityId": "task_understanding"' in prompt
    assert "Mission requirements:" in prompt
    assert "Mission contract:" not in prompt


def test_ordinal_model_key_reuses_existing_logical_identity_without_content_hashing() -> None:
    payload = {
        "tasks": [{
            "key": "task-1",
            "title": "Updated planning step",
            "objective": "Produce the updated planning result under the new constraints",
            "capabilityId": "analysis",
            "logicalRole": "analysis",
            "acceptanceCriteria": ["The planning result is traceable"],
        }],
        "relations": [],
    }
    plan = TaskDecomposer(build_default_capability_catalog(), _PlanLLM(payload)).decompose(
        mission_id="mission_0123456789ab",
        profile=TaskSemanticProfile(
            primaryGoal="Produce a planning result",
            requiredCapabilities=["analysis"],
            estimatedComplexity=ComplexityLevel.SIMPLE,
        ),
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
        existing_semantic_tasks=(
            {"key": "equipment_staff_plan", "capabilityId": "analysis", "logicalRole": "analysis"},
        ),
    )

    assert plan.nodes[0].key == "equipment_staff_plan"
    assert plan.nodes[0].objective.startswith("Produce the updated")


def test_changed_model_key_reuses_unique_logical_role_without_content_hashing() -> None:
    payload = {
        "tasks": [{
            "key": "new-planning-label",
            "title": "Updated planning step",
            "objective": "Produce the updated planning result under the new constraints",
            "capabilityId": "analysis",
            "logicalRole": "analysis",
            "acceptanceCriteria": ["The planning result is traceable"],
        }],
        "relations": [],
    }
    plan = TaskDecomposer(build_default_capability_catalog(), _PlanLLM(payload)).decompose(
        mission_id="mission_0123456789ab",
        profile=TaskSemanticProfile(
            primaryGoal="Produce a planning result",
            requiredCapabilities=["analysis"],
            estimatedComplexity=ComplexityLevel.SIMPLE,
        ),
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
        existing_semantic_tasks=(
            {"key": "equipment_staff_plan", "capabilityId": "analysis", "logicalRole": "analysis"},
        ),
    )

    assert plan.nodes[0].key == "equipment_staff_plan"


def test_reverse_catalog_dependency_is_reported_with_cycle_path_and_repaired() -> None:
    tasks = [
        {
            "key": "understand",
            "title": "Understand mission",
            "objective": "Define the mission boundary",
            "capabilityId": "task_understanding",
            "acceptanceCriteria": ["Mission boundary is explicit"],
        },
        {
            "key": "analyze",
            "title": "Analyze mission",
            "objective": "Analyze the mission within the defined boundary",
            "capabilityId": "analysis",
            "acceptanceCriteria": ["Analysis is traceable to the boundary"],
        },
    ]
    invalid = {
        "tasks": tasks,
        "relations": [
            {"sourceKey": "analyze", "targetKey": "understand", "relationType": "depends_on"},
        ],
    }
    repaired = {
        "tasks": tasks,
        "relations": [
            {"sourceKey": "understand", "targetKey": "analyze", "relationType": "depends_on"},
        ],
    }
    llm = _SequencePlanLLM(invalid, repaired)
    profile = TaskSemanticProfile(
        primaryGoal="Analyze a mission",
        requiredCapabilities=["task_understanding", "analysis"],
        estimatedComplexity=ComplexityLevel.SIMPLE,
    )

    plan = TaskDecomposer(build_default_capability_catalog(), llm).decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert len(llm.calls) == 2
    assert "understand -> analyze -> understand" in llm.calls[1]["prompt"]
    assert llm.calls[1]["prompt_version"] == f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1"
    assert any(
        relation.source_key == "understand" and relation.target_key == "analyze"
        for relation in plan.relations
    )


def test_long_requirement_coverage_uses_stable_refs_instead_of_verbatim_copy() -> None:
    long_constraint = "预算不得超过六百万元且首期必须在二十四周内完成，不得影响门诊业务连续性"
    expected_artifact = "门诊现状与目标分析报告"
    payload = {
        "tasks": [
            {
                "key": "understand",
                "title": "Clarify outpatient optimization boundary",
                "objective": "Define the outpatient optimization boundary and measurable targets",
                "capabilityId": "task_understanding",
                "acceptanceCriteria": ["Targets and operating boundaries are explicit"],
                "sourceRefs": ["constraint:1", "artifact:1"],
            },
        ],
        "relations": [],
    }
    profile = TaskSemanticProfile(
        primaryGoal="Optimize outpatient operations",
        keyConstraints=[long_constraint],
        expectedArtifacts=[expected_artifact],
        requiredCapabilities=["task_understanding"],
        estimatedComplexity=ComplexityLevel.SIMPLE,
    )
    llm = _PlanLLM(payload)

    plan = TaskDecomposer(build_default_capability_catalog(), llm).decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert plan.nodes[0].source_refs == ("constraint:1", "artifact:1")
    assert long_constraint not in plan.model_dump_json()
    assert '"ref": "constraint:1"' in llm.calls[0]["prompt"]


def test_coverage_gap_uses_focused_source_ref_assignment_repair() -> None:
    initial = {
        "tasks": [
            {
                "key": "understand",
                "title": "Define delivery scope",
                "objective": "Define the mission boundary and management deliverables",
                "capabilityId": "task_understanding",
                "acceptanceCriteria": ["Every management deliverable has an accountable task"],
                "sourceRefs": ["artifact:3"],
                "decompositionRationale": "Establish the delivery contract",
            },
        ],
        "relations": [],
    }
    assignments = {
        "assignments": [
            {
                "sourceRef": "artifact:1",
                "taskKey": "understand",
                "rationale": "The scope task owns the executive summary contract",
            },
            {
                "sourceRef": "artifact:2",
                "taskKey": "understand",
                "rationale": "The scope task owns the requirements register contract",
            },
        ],
    }
    profile = TaskSemanticProfile(
        primaryGoal="Prepare a management review package",
        expectedArtifacts=["Executive summary", "Requirements register", "Decision record"],
        requiredCapabilities=["task_understanding"],
        estimatedComplexity=ComplexityLevel.SIMPLE,
    )
    llm = _SequencePlanLLM(initial, assignments)

    plan = TaskDecomposer(build_default_capability_catalog(), llm).decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert len(llm.calls) == 2
    assert llm.calls[1]["prompt_version"] == (
        f"{TASK_DECOMPOSITION_PROMPT_VERSION}.repair1.coverage"
    )
    assert "Do not create, delete, rename or rewrite tasks" in llm.calls[1]["prompt"]
    assert llm.calls[1]["schema"]["properties"]["assignments"]["minItems"] == 2
    assert plan.nodes[0].source_refs == ("artifact:3", "artifact:1", "artifact:2")
    assert plan.nodes[0].objective == initial["tasks"][0]["objective"]
    assert plan.relations == ()


def test_focused_coverage_repair_rejects_incomplete_assignments() -> None:
    initial = {
        "tasks": [
            {
                "key": "understand",
                "title": "Define delivery scope",
                "objective": "Define the mission boundary and management deliverables",
                "capabilityId": "task_understanding",
                "acceptanceCriteria": ["Every management deliverable has an accountable task"],
                "sourceRefs": [],
                "decompositionRationale": "Establish the delivery contract",
            },
        ],
        "relations": [],
    }
    incomplete = {
        "assignments": [
            {
                "sourceRef": "artifact:1",
                "taskKey": "understand",
                "rationale": "The scope task owns the executive summary contract",
            },
        ],
    }
    profile = TaskSemanticProfile(
        primaryGoal="Prepare a management review package",
        expectedArtifacts=["Executive summary", "Requirements register"],
        requiredCapabilities=["task_understanding"],
        estimatedComplexity=ComplexityLevel.SIMPLE,
    )
    llm = _SequencePlanLLM(initial, incomplete)

    with pytest.raises(Exception, match="every missing source ref exactly once"):
        TaskDecomposer(build_default_capability_catalog(), llm).decompose(
            mission_id="mission_0123456789ab",
            profile=profile,
            strategy="dynamic_generation",
            task_input={},
            use_llm=True,
        )

    assert len(llm.calls) == 2


def test_catalog_dependency_completion_does_not_depend_on_model_task_order() -> None:
    payload = {
        "tasks": [
            {
                "key": "analysis-first",
                "title": "Analyze operating conditions",
                "objective": "Analyze operating conditions after the mission boundary is established",
                "capabilityId": "analysis",
                "acceptanceCriteria": ["Operating conditions are explicit"],
            },
            {
                "key": "understanding-second",
                "title": "Define mission boundary",
                "objective": "Define the mission boundary and decision scope",
                "capabilityId": "task_understanding",
                "acceptanceCriteria": ["Mission boundary is explicit"],
            },
        ],
        "relations": [],
    }
    profile = TaskSemanticProfile(
        primaryGoal="Analyze a mission",
        requiredCapabilities=["task_understanding", "analysis"],
        estimatedComplexity=ComplexityLevel.SIMPLE,
    )

    plan = TaskDecomposer(build_default_capability_catalog(), _PlanLLM(payload)).decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    assert any(
        relation.source_key == "understanding-second"
        and relation.target_key == "analysis-first"
        for relation in plan.relations
    )


def test_model_shorthand_constraints_and_missing_capability_are_normalized() -> None:
    payload = {
        "tasks": [
            {
                "key": "verify",
                "title": "Verify acceptance",
                "objective": "Verify all acceptance criteria against available evidence",
                "capabilityId": "verification",
                "constraints": ["必须覆盖所有约束", {"type": "evidence", "value": "traceable"}],
                "acceptanceCriteria": ["Every criterion has an explicit status"],
            },
        ],
        "relations": [],
    }
    profile = TaskSemanticProfile(
        primaryGoal="Produce an evidence-backed result",
        requiredCapabilities=["evidence_analysis", "verification"],
        estimatedComplexity=ComplexityLevel.SIMPLE,
    )

    plan = TaskDecomposer(build_default_capability_catalog(), _PlanLLM(payload)).decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    verification = next(node for node in plan.nodes if node.key == "verify")
    evidence = next(
        node for node in plan.nodes
        if node.capability_requirements == ("evidence_analysis",)
    )
    retrieval = next(
        node for node in plan.nodes
        if node.capability_requirements == ("information_retrieval",)
    )
    understanding = next(
        node for node in plan.nodes
        if node.capability_requirements == ("task_understanding",)
    )
    assert verification.constraints[0] == {
        "type": "task_constraint",
        "value": "必须覆盖所有约束",
    }
    assert evidence.logical_role == "prerequisite"
    assert any(
        relation.source_key == understanding.key and relation.target_key == retrieval.key
        for relation in plan.relations
    )
    assert any(
        relation.source_key == retrieval.key and relation.target_key == evidence.key
        for relation in plan.relations
    )
    assert any(
        relation.source_key == understanding.key and relation.target_key == verification.key
        for relation in plan.relations
    )


def test_terminal_semantic_results_are_connected_to_final_artifact() -> None:
    payload = {
        "tasks": [
            {
                "key": "understand", "title": "Understand", "objective": "Define the mission boundary",
                "capabilityId": "task_understanding", "acceptanceCriteria": ["Boundary is explicit"],
            },
            {
                "key": "branch-a", "title": "Branch A", "objective": "Analyze the first independent branch",
                "capabilityId": "analysis", "acceptanceCriteria": ["Branch A is traceable"],
            },
            {
                "key": "branch-b", "title": "Branch B", "objective": "Analyze the second independent branch",
                "capabilityId": "analysis", "acceptanceCriteria": ["Branch B is traceable"],
            },
            {
                "key": "deliver", "title": "Deliver", "objective": "Assemble all verified branch results",
                "capabilityId": "artifact_generation", "acceptanceCriteria": ["Every branch is represented"],
            },
        ],
        "relations": [
            {"sourceKey": "understand", "targetKey": "branch-a", "relationType": "depends_on"},
            {"sourceKey": "understand", "targetKey": "branch-b", "relationType": "depends_on"},
        ],
    }
    profile = TaskSemanticProfile(
        primaryGoal="Analyze two branches and deliver one result",
        requiredCapabilities=["task_understanding", "analysis", "artifact_generation"],
    )

    plan = TaskDecomposer(build_default_capability_catalog(), _PlanLLM(payload)).decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input={},
        use_llm=True,
    )

    edges = {(item.source_key, item.target_key) for item in plan.relations}
    assert ("branch-a", "deliver") in edges
    assert ("branch-b", "deliver") in edges
