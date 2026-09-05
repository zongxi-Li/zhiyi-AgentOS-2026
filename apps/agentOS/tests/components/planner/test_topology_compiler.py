from __future__ import annotations

import pytest
import components.planner.topology.compiler as topology_compiler_module

from components.planner.topology import (
    CapabilityBindingSolver, CapabilityRequirement, EdgeMutationPolicy, EdgeOrigin,
    TaskPlanTopologyCompiler, TopologyCompileError,
    TopologyConflict, TopologyConflictCode, TopologyEdge, apply_repair_patch,
    catalog_fingerprint, is_model_repair_eligible, successful_topology_audit,
)
from components.planner.semantic_planner import SemanticPlanner
from components.planner.service import apply_task_plan_patch
from contracts.planning import (
    PlannedTask, TaskPlan, TaskPlanPatch, TaskPlanRelation, VerificationLoopPolicy,
)
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from support.acg.models import CapabilityCatalog, PlanningCapabilityDescriptor


def _task(key: str, capability: str) -> PlannedTask:
    return PlannedTask(
        key=key, title=key, objective=f"Execute {key}",
        capabilityRequirements=(capability,), acceptanceCriteria=("done",),
    )


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId="cap_a", displayName="A"),
        PlanningCapabilityDescriptor(
            capabilityId="cap_b", displayName="B", dependsOn=["cap_a"],
        ),
        PlanningCapabilityDescriptor(capabilityId="cap_c", displayName="C"),
        PlanningCapabilityDescriptor(capabilityId="verification", displayName="Verify"),
    ])


def test_case_b_conflict_contains_complete_cycle_and_edge_origins() -> None:
    compiler = TaskPlanTopologyCompiler(_catalog())
    with pytest.raises(TopologyCompileError) as captured:
        compiler.compile(
            nodes=[_task("A", "cap_a"), _task("B", "cap_b"), _task("C", "cap_c")],
            raw_relations=[
                TaskPlanRelation(sourceKey="B", targetKey="C", relationType="depends_on"),
                TaskPlanRelation(sourceKey="C", targetKey="A", relationType="depends_on"),
            ],
            control_policies=(),
        )

    conflict = captured.value.conflict
    assert conflict.code.value == "capability_binding_conflict"
    assert conflict.cycle_nodes == ("A", "B", "C", "A")
    assert [(edge.source_key, edge.target_key, edge.origin) for edge in conflict.cycle_edges] == [
        ("A", "B", EdgeOrigin.CAPABILITY_CATALOG),
        ("B", "C", EdgeOrigin.MODEL),
        ("C", "A", EdgeOrigin.MODEL),
    ]
    assert conflict.cycle_edges[0].mutation_policy is EdgeMutationPolicy.REBINDABLE
    assert all(edge.mutation_policy is EdgeMutationPolicy.REPAIRABLE for edge in conflict.cycle_edges[1:])


def test_terminal_edge_has_internal_provenance_but_public_relation_does_not() -> None:
    result = TaskPlanTopologyCompiler(_catalog()).compile(
        nodes=[_task("leaf", "cap_c"), _task("sink", "verification")],
        raw_relations=[], control_policies=(),
    )
    terminal = next(edge for edge in result.candidate.edges if edge.origin is EdgeOrigin.TERMINAL_CONNECTOR)
    assert (terminal.source_key, terminal.target_key) == ("leaf", "sink")
    assert terminal.mutation_policy is EdgeMutationPolicy.REGENERABLE
    assert result.task_plan_relations[0].model_dump(by_alias=True) == {
        "sourceKey": "leaf", "targetKey": "sink", "relationType": "depends_on",
    }


def test_verification_loop_is_not_projected_as_static_back_edge() -> None:
    policy = VerificationLoopPolicy(
        bodyEntryKey="draft", bodyExitKey="verify", conditionSourceKey="verify"
    )
    result = TaskPlanTopologyCompiler(_catalog()).compile(
        nodes=[_task("draft", "cap_c"), _task("verify", "verification")],
        raw_relations=[
            TaskPlanRelation(sourceKey="draft", targetKey="verify", relationType="depends_on")
        ],
        control_policies=(policy,),
    )
    pairs = {(edge.source_key, edge.target_key) for edge in result.candidate.edges}
    assert ("draft", "verify") in pairs
    assert ("verify", "draft") not in pairs


def test_real_storage_planning_cycle_preserves_catalog_and_model_provenance() -> None:
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId="process_decomposition", displayName="Process"),
        PlanningCapabilityDescriptor(
            capabilityId="cost_analysis", displayName="Cost",
            dependsOn=["process_decomposition"],
        ),
        PlanningCapabilityDescriptor(capabilityId="solution_design", displayName="Solution"),
    ])
    nodes = [
        _task("implementation-schedule-30weeks", "process_decomposition"),
        _task("storage-sizing-calculation", "cost_analysis"),
        _task("alternative-distributed-storage-design", "solution_design"),
        _task("candidate-economic-comparison", "solution_design"),
        _task("recommended-scheme-synthesis", "solution_design"),
    ]
    model_pairs = [
        ("storage-sizing-calculation", "alternative-distributed-storage-design"),
        ("alternative-distributed-storage-design", "candidate-economic-comparison"),
        ("candidate-economic-comparison", "recommended-scheme-synthesis"),
        ("recommended-scheme-synthesis", "implementation-schedule-30weeks"),
    ]
    with pytest.raises(TopologyCompileError) as captured:
        TaskPlanTopologyCompiler(catalog).compile(
            nodes=nodes,
            raw_relations=[
                TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")
                for source, target in model_pairs
            ],
            control_policies=(),
        )

    conflict_edges = captured.value.conflict.cycle_edges
    catalog_edge = next(edge for edge in conflict_edges if edge.origin is EdgeOrigin.CAPABILITY_CATALOG)
    assert (catalog_edge.source_key, catalog_edge.target_key) == (
        "implementation-schedule-30weeks", "storage-sizing-calculation"
    )
    assert catalog_edge.mutation_policy is EdgeMutationPolicy.REBINDABLE
    assert sum(edge.origin is EdgeOrigin.MODEL for edge in conflict_edges) == 4


def test_immutable_only_cycle_is_not_model_repair_eligible() -> None:
    fixed = (
        TopologyEdge("A", "B", "depends_on", EdgeOrigin.USER_DECLARED, EdgeMutationPolicy.FIXED),
        TopologyEdge("B", "A", "depends_on", EdgeOrigin.USER_DECLARED, EdgeMutationPolicy.FIXED),
    )
    conflict = TopologyConflict(
        code=TopologyConflictCode.DEPENDENCY_CYCLE, phase="final_validation",
        cycle_nodes=("A", "B", "A"), cycle_edges=fixed, fixed_edges=fixed,
    )
    assert is_model_repair_eligible(conflict) is False


def test_repair_patch_targets_original_model_relation_index() -> None:
    relations, policies = apply_repair_patch(
        relations=[
            {"sourceKey": "A", "targetKey": "B", "relationType": "depends_on"},
            {"sourceKey": "B", "targetKey": "A", "relationType": "depends_on"},
        ],
        control_policies=[],
        patch={"operations": [
            {"op": "remove_relation", "relationIndex": 1},
            {"op": "add_verification_loop", "bodyEntryKey": "A",
             "bodyExitKey": "B", "conditionSourceKey": "B"},
        ]},
        task_keys={"A", "B"},
    )
    assert [(item["sourceKey"], item["targetKey"]) for item in relations] == [("A", "B")]
    assert policies[0]["type"] == "verification_loop"


def test_multiple_patch_removals_use_stable_original_indexes() -> None:
    relations, _ = apply_repair_patch(
        relations=[
            {"sourceKey": "A", "targetKey": "B", "relationType": "depends_on"},
            {"sourceKey": "B", "targetKey": "C", "relationType": "depends_on"},
            {"sourceKey": "C", "targetKey": "A", "relationType": "depends_on"},
        ],
        control_policies=[],
        patch={"operations": [
            {"op": "remove_relation", "relationIndex": 0},
            {"op": "remove_relation", "relationIndex": 2},
        ]},
        task_keys={"A", "B", "C"},
    )
    assert relations == [{"sourceKey": "B", "targetKey": "C", "relationType": "depends_on"}]


def test_full_recompile_reselects_capability_binding_from_patched_proposal() -> None:
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId="producer", displayName="Producer"),
        PlanningCapabilityDescriptor(capabilityId="consumer", displayName="Consumer", dependsOn=["producer"]),
        PlanningCapabilityDescriptor(capabilityId="bridge", displayName="Bridge"),
    ])
    compiler = TaskPlanTopologyCompiler(catalog)
    nodes = [_task("P1", "producer"), _task("C", "consumer"),
             _task("X", "bridge"), _task("P2", "producer")]
    first = compiler.compile(nodes=nodes, raw_relations=[], control_policies=())
    first_binding = next(edge for edge in first.candidate.edges if edge.origin is EdgeOrigin.CAPABILITY_CATALOG)
    assert first_binding.source_key == "P1"
    second = compiler.compile(
        nodes=nodes,
        raw_relations=[
            TaskPlanRelation(sourceKey="C", targetKey="X", relationType="depends_on"),
            TaskPlanRelation(sourceKey="X", targetKey="P1", relationType="depends_on"),
        ],
        control_policies=(),
    )
    second_binding = next(edge for edge in second.candidate.edges if edge.origin is EdgeOrigin.CAPABILITY_CATALOG)
    assert second_binding.source_key == "P2"


def test_candidate_collection_order_does_not_change_binding() -> None:
    nodes = [_task("P2", "cap_a"), _task("C", "cap_b"), _task("P1", "cap_a")]
    solver = CapabilityBindingSolver()
    def selected(candidates):
        audit = solver.solve(
            nodes=nodes, base_edges=[], requirements=[CapabilityRequirement(
                "r", "cap_a", "cap_b", "C", tuple(candidates),
            )],
        )
        return audit.selected_bindings[0].source_key
    assert selected(["P1", "P2"]) == selected(["P2", "P1"]) == "P2"


def test_binding_fingerprint_is_deterministic_across_repeated_runs() -> None:
    compiler = TaskPlanTopologyCompiler(_catalog())
    nodes = [_task("A", "cap_a"), _task("B", "cap_b")]
    fingerprints = []
    for _ in range(5):
        result = compiler.compile(nodes=nodes, raw_relations=[], control_policies=())
        fingerprints.append(tuple(
            (edge.requirement_id, edge.source_key, edge.target_key)
            for edge in result.candidate.selected_bindings
        ))
    assert len(set(fingerprints)) == 1


def test_no_solution_returns_binding_conflict_with_candidate_evidence() -> None:
    nodes = [_task("P1", "cap_a"), _task("P2", "cap_a"),
             _task("C", "cap_b"), _task("X", "cap_c")]
    base = [
        TopologyEdge("C", "X", "depends_on", EdgeOrigin.MODEL, EdgeMutationPolicy.REPAIRABLE),
        TopologyEdge("X", "P1", "depends_on", EdgeOrigin.MODEL, EdgeMutationPolicy.REPAIRABLE),
        TopologyEdge("X", "P2", "depends_on", EdgeOrigin.MODEL, EdgeMutationPolicy.REPAIRABLE),
    ]
    with pytest.raises(TopologyCompileError) as captured:
        CapabilityBindingSolver().solve(
            nodes=nodes, base_edges=base, requirements=[CapabilityRequirement(
                "r", "cap_a", "cap_b", "C", ("P1", "P2"),
            )],
        )
    conflict = captured.value.conflict
    assert conflict.code is TopologyConflictCode.CAPABILITY_BINDING_CONFLICT
    assert {item.producer_task_key for item in conflict.binding_rejections} == {"P1", "P2"}
    assert all(item.reason == "cycle" and item.path for item in conflict.binding_rejections)


def test_search_budget_exhaustion_fails_closed() -> None:
    nodes = [_task("P1", "cap_a"), _task("C1", "cap_b"),
             _task("P2", "cap_a"), _task("C2", "cap_b")]
    requirements = [
        CapabilityRequirement("r1", "cap_a", "cap_b", "C1", ("P1", "P2")),
        CapabilityRequirement("r2", "cap_a", "cap_b", "C2", ("P1", "P2")),
    ]
    with pytest.raises(TopologyCompileError) as captured:
        CapabilityBindingSolver(max_search_states=1).solve(
            nodes=nodes, requirements=requirements, base_edges=[]
        )
    assert captured.value.conflict.code is TopologyConflictCode.CAPABILITY_BINDING_SEARCH_EXHAUSTED
    assert captured.value.conflict.search_states_explored == 2


def test_bounded_solver_backtracks_out_of_greedy_trap() -> None:
    nodes = [
        _task("P1", "producer_one"), _task("C1", "consumer_one"),
        _task("Q1", "producer_two"), _task("Q2", "producer_two"),
        _task("C2", "consumer_two"), _task("P2", "producer_one"),
    ]
    requirements = [
        CapabilityRequirement("r1", "producer_one", "consumer_one", "C1", ("P1", "P2")),
        CapabilityRequirement("r2", "producer_two", "consumer_two", "C2", ("Q1", "Q2")),
    ]
    base = [
        TopologyEdge("C2", "P1", "depends_on", EdgeOrigin.MODEL, EdgeMutationPolicy.REPAIRABLE),
        TopologyEdge("C1", "Q1", "depends_on", EdgeOrigin.MODEL, EdgeMutationPolicy.REPAIRABLE),
        TopologyEdge("C1", "Q2", "depends_on", EdgeOrigin.MODEL, EdgeMutationPolicy.REPAIRABLE),
    ]
    audit = CapabilityBindingSolver().solve(
        nodes=nodes, requirements=requirements, base_edges=base
    )
    bindings = {(edge.requirement_id, edge.source_key, edge.target_key) for edge in audit.selected_bindings}
    assert bindings == {("r1", "P2", "C1"), ("r2", "Q2", "C2")}
    assert audit.backtrack_count >= 1
    assert any(item.reason == "downstream_unsatisfied" for item in audit.rejected_candidates)


def test_existing_plan_relations_are_fixed_and_not_silently_repaired() -> None:
    with pytest.raises(TopologyCompileError) as captured:
        TaskPlanTopologyCompiler(_catalog()).validate_existing_plan(
            nodes=[_task("A", "cap_a"), _task("B", "cap_c")],
            raw_relations=[
                TaskPlanRelation(sourceKey="A", targetKey="B", relationType="depends_on"),
                TaskPlanRelation(sourceKey="B", targetKey="A", relationType="depends_on"),
            ],
            control_policies=(),
            relation_origin=EdgeOrigin.TEMPLATE_DECLARED,
        )

    conflict = captured.value.conflict
    assert conflict.code is TopologyConflictCode.DEPENDENCY_CYCLE
    assert conflict.repairable_edges == ()
    assert len(conflict.fixed_edges) == 2
    assert {edge.origin for edge in conflict.fixed_edges} == {EdgeOrigin.TEMPLATE_DECLARED}


def test_template_cycle_fails_before_acg_build_with_structured_conflict() -> None:
    workflow = WorkflowDefinition(
        workflowId="cyclic-template", name="Cyclic", domain="general",
        runtimeEngine="acg",
        planningNodes=[_task("A", "cap_a"), _task("B", "cap_c")],
        planningRelations=[
            TaskPlanRelation(sourceKey="A", targetKey="B", relationType="depends_on"),
            TaskPlanRelation(sourceKey="B", targetKey="A", relationType="depends_on"),
        ],
        steps=[WorkflowStepDefinition(
            stepId="execute", name="Execute", agentName="agent", capability="cap_a",
        )],
    )
    with pytest.raises(TopologyCompileError) as captured:
        SemanticPlanner(_catalog()).plan_template(
            mission_id="mission_0123456789ab", workflow=workflow, strategy="static_template"
        )
    assert captured.value.conflict.code is TopologyConflictCode.DEPENDENCY_CYCLE
    assert captured.value.conflict.repairable_edges == ()


def test_compatibility_plan_uses_shared_solver_without_duplicate_catalog_edge() -> None:
    plan = SemanticPlanner(_catalog()).plan_capabilities(
        mission_id="mission_0123456789ab", capabilities=["cap_a", "cap_b"],
        strategy="compatibility",
    )
    assert [(item.source_key, item.target_key) for item in plan.relations] == [
        ("capability:cap_a", "capability:cap_b")
    ]


def test_valid_patch_is_validated_and_returns_new_immutable_version() -> None:
    current = TaskPlan(
        missionId="mission_0123456789ab",
        nodes=(_task("A", "cap_a"), _task("B", "cap_c")),
        relations=(TaskPlanRelation(
            sourceKey="A", targetKey="B", relationType="depends_on"
        ),),
    )
    patch = TaskPlanPatch(
        missionId=current.mission_id, basePlanVersion=1, planVersion=2,
        addNodes=(_task("C", "verification"),),
        relations=(TaskPlanRelation(
            sourceKey="B", targetKey="C", relationType="depends_on"
        ),),
    )
    revised = apply_task_plan_patch(current, patch, _catalog())
    assert revised.plan_version == 2
    assert {(item.source_key, item.target_key) for item in revised.relations} == {
        ("A", "B"), ("B", "C")
    }
    assert current.plan_version == 1
    assert [node.key for node in current.nodes] == ["A", "B"]


def test_patch_cycle_fails_closed_with_structured_conflict() -> None:
    current = TaskPlan(
        missionId="mission_0123456789ab",
        nodes=(_task("A", "cap_a"), _task("B", "cap_c")),
        relations=(TaskPlanRelation(
            sourceKey="A", targetKey="B", relationType="depends_on"
        ),),
    )
    patch = TaskPlanPatch(
        missionId=current.mission_id, basePlanVersion=1, planVersion=2,
        relations=(TaskPlanRelation(
            sourceKey="B", targetKey="A", relationType="depends_on"
        ),),
    )
    with pytest.raises(TopologyCompileError) as captured:
        apply_task_plan_patch(current, patch, _catalog())
    assert captured.value.conflict.code is TopologyConflictCode.DEPENDENCY_CYCLE
    assert captured.value.conflict.repairable_edges == ()
    assert current.plan_version == 1
    assert [(item.source_key, item.target_key) for item in current.relations] == [("A", "B")]


def test_patch_capability_conflict_retains_requirement_and_rejection_path() -> None:
    catalog = CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId="producer", displayName="Producer"),
        PlanningCapabilityDescriptor(
            capabilityId="consumer", displayName="Consumer", dependsOn=["producer"]
        ),
        PlanningCapabilityDescriptor(capabilityId="bridge", displayName="Bridge"),
    ])
    current = TaskPlan(
        missionId="mission_0123456789ab",
        nodes=(_task("P", "producer"), _task("C", "consumer")),
    )
    patch = TaskPlanPatch(
        missionId=current.mission_id, basePlanVersion=1, planVersion=2,
        addNodes=(_task("X", "bridge"),),
        relations=(
            TaskPlanRelation(sourceKey="C", targetKey="X", relationType="depends_on"),
            TaskPlanRelation(sourceKey="X", targetKey="P", relationType="depends_on"),
        ),
    )
    with pytest.raises(TopologyCompileError) as captured:
        apply_task_plan_patch(current, patch, catalog)
    conflict = captured.value.conflict
    assert conflict.code is TopologyConflictCode.CAPABILITY_BINDING_CONFLICT
    assert conflict.capability_requirements[0].requirement_id == "catalog:producer->consumer:C"
    assert conflict.binding_rejections[0].producer_task_key == "P"
    assert conflict.binding_rejections[0].path == ("C", "X", "P")
    assert current.plan_version == 1


@pytest.mark.parametrize("producer", ["dynamic", "template", "fallback", "patch"])
def test_all_task_plan_producers_reach_the_shared_candidate_validator(
    producer: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = topology_compiler_module.validate_candidate

    def spy(candidate):
        nonlocal calls
        calls += 1
        return original(candidate)

    monkeypatch.setattr(topology_compiler_module, "validate_candidate", spy)
    catalog = _catalog()
    mission_id = "mission_0123456789ab"
    if producer == "dynamic":
        TaskPlanTopologyCompiler(catalog).compile(
            nodes=[_task("A", "cap_a")], raw_relations=[], control_policies=()
        )
    elif producer == "template":
        workflow = WorkflowDefinition(
            workflowId="template", name="Template", domain="general", runtimeEngine="acg",
            planningNodes=[_task("A", "cap_a")],
            steps=[WorkflowStepDefinition(
                stepId="execute", name="Execute", agentName="agent", capability="cap_a",
            )],
        )
        SemanticPlanner(catalog).plan_template(
            mission_id=mission_id, workflow=workflow, strategy="static_template"
        )
    elif producer == "fallback":
        SemanticPlanner(catalog).plan_capabilities(
            mission_id=mission_id, capabilities=["cap_a"], strategy="compatibility"
        )
    else:
        current = TaskPlan(missionId=mission_id, nodes=(_task("A", "cap_a"),))
        apply_task_plan_patch(
            current,
            TaskPlanPatch(
                missionId=mission_id, basePlanVersion=1, planVersion=2,
                addNodes=(_task("B", "cap_c"),),
            ),
            catalog,
        )
    assert calls >= 2


def test_success_audit_has_stable_fingerprints_and_search_summary() -> None:
    compiler = TaskPlanTopologyCompiler(_catalog())
    nodes = [_task("A", "cap_a"), _task("B", "cap_b")]
    result = compiler.compile(nodes=nodes, raw_relations=[], control_policies=())
    first = successful_topology_audit(
        result=result, nodes=nodes, catalog=_catalog(), producer_kind="dynamic",
        catalog_source="injected", capability_coverage_mode="complete",
    )
    second = successful_topology_audit(
        result=result, nodes=list(reversed(nodes)), catalog=_catalog(), producer_kind="dynamic",
        catalog_source="injected", capability_coverage_mode="complete",
    )
    assert first["compilerVersion"]
    assert first["catalogFingerprint"] == catalog_fingerprint(_catalog())
    assert first["topologyFingerprint"] == second["topologyFingerprint"]
    assert first["selectedBindings"][0]["requirementId"] == "catalog:cap_a->cap_b:B"
    assert first["bindingSearch"]["statesExplored"] >= 1
    assert first["status"] == "validated"


def test_failure_audit_is_structured_and_contains_no_raw_model_content() -> None:
    audits = []
    with pytest.raises(TopologyCompileError) as captured:
        from components.planner.topology import validate_task_plan_for_execution
        validate_task_plan_for_execution(
            capability_catalog=_catalog(), mission_id="mission_0123456789ab",
            nodes=[_task("A", "cap_a"), _task("B", "cap_c")],
            relations=[
                TaskPlanRelation(sourceKey="A", targetKey="B", relationType="depends_on"),
                TaskPlanRelation(sourceKey="B", targetKey="A", relationType="depends_on"),
            ], relation_origin=EdgeOrigin.PLAN_PATCH, producer_kind="patch",
            catalog_source="injected", audit_sink=audits.append,
        )
    audit = audits[0]
    assert captured.value.audit == audit
    assert audit["conflict"]["code"] == "dependency_cycle"
    assert audit["conflict"]["cycleEdges"][0]["origin"] == "plan_patch"
    assert audit["status"] == "rejected"
    assert "prompt" not in str(audit).lower()


def test_patch_default_catalog_is_explicitly_marked_compatibility() -> None:
    audits = []
    current = TaskPlan(
        missionId="mission_0123456789ab",
        nodes=(PlannedTask(key="A", title="A", objective="A"),),
    )
    apply_task_plan_patch(
        current, TaskPlanPatch(
            missionId=current.mission_id, basePlanVersion=1, planVersion=2,
            addNodes=(PlannedTask(key="B", title="B", objective="B"),),
        ), audit_sink=audits.append,
    )
    assert audits[0]["catalogSource"] == "default_compatibility"
    assert audits[0]["capabilityCoverageMode"] == "declared_producers_only"
