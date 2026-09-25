from __future__ import annotations

import pytest

from components.planner.acg_builder import ACGBuilder
from components.planner.acg_semantic_validator import (
    ACGSemanticPreservationError, semantic_reachability_projection,
    validate_acg_semantic_preservation, validate_bound_acg_semantics,
)
from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
from components.planner.topology.compiler import TaskPlanTopologyCompiler
from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan, TaskPlanRelation, VerificationLoopPolicy
from support.acg.models import (
    ACGBlueprint, ACGEdge, CapabilityCatalog, ControlNode, ControlType, EdgeType, StepNode,
    PlanningCapabilityDescriptor, TaskSemanticProfile,
)


def _task(key: str) -> PlannedTask:
    return PlannedTask(
        key=key, title=key, objective=f"Execute {key}",
        capabilityRequirements=(key.lower(),), acceptanceCriteria=("done",),
    )


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog([
        PlanningCapabilityDescriptor(
            capabilityId=key.lower(), displayName=key, planningStage=stage,
            parallelizable=key in {"B", "C"},
        )
        for key, stage in (("A", "source"), ("B", "branch"),
                           ("C", "branch"), ("D", "sink"))
    ])


def _build(plan: TaskPlan) -> ACGBlueprint:
    bindings = [
        CapabilityBinding(capability=node.capability_requirements[0], agent_name="agent", score=1.0)
        for node in plan.nodes
    ]
    return ACGBuilder(_catalog()).build(
        mission_id=plan.mission_id,
        profile=TaskSemanticProfile(
            primaryGoal="prove lowering",
            requiredCapabilities=[item.capability for item in bindings],
        ),
        network=CollaborationNetwork(bindings=bindings), task_plan=plan,
    )


def _plan(*pairs: tuple[str, str], policies=()) -> TaskPlan:
    keys = tuple(dict.fromkeys(item for pair in pairs for item in pair))
    return TaskPlan(
        missionId="mission_0123456789ab", nodes=tuple(_task(key) for key in keys),
        relations=tuple(TaskPlanRelation(
            sourceKey=source, targetKey=target, relationType="depends_on"
        ) for source, target in pairs), controlPolicies=policies,
    )


@pytest.mark.parametrize("pairs", [
    (("A", "B"),),
    (("A", "B"), ("B", "C")),
])
def test_direct_and_chain_semantic_dependencies_survive_lowering(pairs) -> None:
    plan = _plan(*pairs)
    blueprint = _build(plan)
    validate_acg_semantic_preservation(plan, blueprint)


def test_parallel_join_preserves_dependencies_without_serializing_siblings() -> None:
    plan = _plan(("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))
    blueprint = _build(plan)
    by_key = {step.metadata["taskPlanKey"]: step.node_id for step in blueprint.step_nodes()}
    dependencies = {(edge.source_id, edge.target_id) for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY)}

    validate_acg_semantic_preservation(plan, blueprint)
    assert (by_key["B"], by_key["C"]) not in dependencies
    assert (by_key["C"], by_key["B"]) not in dependencies
    assert any(
        isinstance(node, ControlNode) and node.control_type is ControlType.PARALLEL
        for node in blueprint.nodes
    )


def test_parallel_join_does_not_make_unrelated_sibling_precede_consumer() -> None:
    plan = _plan(("A", "B"), ("A", "C"), ("B", "D"))
    blueprint = _build(plan)
    bindings = tuple(TaskImplementationBinding(
        planNodeKey=step.metadata["taskPlanKey"], acgNodeId=step.node_id,
    ) for step in blueprint.step_nodes())

    assert ("C", "D") not in semantic_reachability_projection(blueprint, bindings)
    validate_bound_acg_semantics(plan, blueprint, bindings, require_exact=True)


def test_verification_loop_remains_control_topology_not_semantic_back_edge() -> None:
    policy = VerificationLoopPolicy(
        bodyEntryKey="A", bodyExitKey="D", conditionSourceKey="D"
    )
    plan = _plan(("A", "D"), policies=(policy,))
    blueprint = _build(plan)
    validate_acg_semantic_preservation(plan, blueprint)
    assert ("D", "A") not in {(item.source_key, item.target_key) for item in plan.relations}
    assert any(
        isinstance(node, ControlNode) and node.control_type is ControlType.LOOP
        for node in blueprint.nodes
    )


def test_model_retry_back_edge_compiles_to_acyclic_dependencies_and_loop_control() -> None:
    policy = VerificationLoopPolicy(
        bodyEntryKey="A", bodyExitKey="D", conditionSourceKey="D"
    )
    catalog = _catalog()
    result = TaskPlanTopologyCompiler(catalog).compile(
        nodes=[_task("A"), _task("D")],
        raw_relations=[
            TaskPlanRelation(sourceKey="A", targetKey="D", relationType="depends_on"),
            TaskPlanRelation(sourceKey="D", targetKey="A", relationType="depends_on"),
        ],
        control_policies=(policy,),
    )
    plan = TaskPlan(
        missionId="mission_0123456789ab",
        nodes=(_task("A"), _task("D")),
        relations=result.task_plan_relations,
        controlPolicies=result.control_policies,
    )
    blueprint = _build(plan)

    validate_acg_semantic_preservation(plan, blueprint)
    by_key = {step.metadata["taskPlanKey"]: step.node_id for step in blueprint.step_nodes()}
    dependency_pairs = {
        (edge.source_id, edge.target_id)
        for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY)
        if edge.source_id in by_key.values() and edge.target_id in by_key.values()
    }
    assert dependency_pairs == {(by_key["A"], by_key["D"])}
    assert any(
        isinstance(node, ControlNode) and node.control_type is ControlType.LOOP
        for node in blueprint.nodes
    )


def test_preservation_validator_rejects_a_dropped_semantic_dependency() -> None:
    plan = _plan(("A", "B"))
    blueprint = _build(plan)
    by_key = {step.metadata["taskPlanKey"]: step.node_id for step in blueprint.step_nodes()}
    blueprint.edges = [
        edge for edge in blueprint.edges
        if not (edge.edge_type is EdgeType.DEPENDENCY
                and edge.source_id == by_key["A"] and edge.target_id == by_key["B"])
    ]
    with pytest.raises(ACGSemanticPreservationError, match="not preserved"):
        validate_acg_semantic_preservation(plan, blueprint)


def test_builder_always_invokes_semantic_preservation_guard(monkeypatch) -> None:
    import components.planner.acg_builder as builder_module

    calls = []
    original = builder_module.validate_acg_semantic_preservation

    def spy(plan, blueprint):
        calls.append((plan, blueprint))
        return original(plan, blueprint)

    monkeypatch.setattr(builder_module, "validate_acg_semantic_preservation", spy)
    plan = _plan(("A", "B"))
    blueprint = _build(plan)
    assert calls == [(plan, blueprint)]


def test_explicit_bindings_reject_reversed_semantic_dependency() -> None:
    plan = _plan(("A", "B"))
    blueprint = ACGBlueprint(
        graphId="explicit-reversed",
        nodes=[StepNode(nodeId="step-b"), StepNode(nodeId="step-a")],
        edges=[ACGEdge(sourceId="step-b", targetId="step-a")],
    )
    bindings = (
        TaskImplementationBinding(planNodeKey="A", acgNodeId="step-a"),
        TaskImplementationBinding(planNodeKey="B", acgNodeId="step-b"),
    )
    with pytest.raises(ACGSemanticPreservationError, match="reversed"):
        validate_bound_acg_semantics(plan, blueprint, bindings)


def test_explicit_bindings_accept_dependency_through_control() -> None:
    plan = _plan(("A", "B"))
    blueprint = ACGBlueprint(
        graphId="explicit-control",
        nodes=[StepNode(nodeId="step-b"), ControlNode(nodeId="control-x", controlType=ControlType.START),
               StepNode(nodeId="step-a")],
        edges=[ACGEdge(sourceId="step-a", targetId="control-x"),
               ACGEdge(sourceId="control-x", targetId="step-b")],
    )
    bindings = (
        TaskImplementationBinding(planNodeKey="B", acgNodeId="step-b"),
        TaskImplementationBinding(planNodeKey="A", acgNodeId="step-a"),
    )
    validate_bound_acg_semantics(plan, blueprint, bindings)
    assert semantic_reachability_projection(blueprint, bindings) == {("A", "B")}


def test_explicit_bindings_reject_missing_and_duplicate_semantics() -> None:
    plan = _plan(("A", "B"))
    blueprint = ACGBlueprint(
        graphId="explicit-extra", nodes=[StepNode(nodeId="step-a"), StepNode(nodeId="step-b")],
        edges=[ACGEdge(sourceId="step-a", targetId="step-b")],
    )
    with pytest.raises(ACGSemanticPreservationError, match="do not cover"):
        validate_bound_acg_semantics(plan, blueprint, (
            TaskImplementationBinding(planNodeKey="A", acgNodeId="step-a"),
        ))
    with pytest.raises(ACGSemanticPreservationError, match="exactly once"):
        validate_bound_acg_semantics(plan, blueprint, (
            TaskImplementationBinding(planNodeKey="A", acgNodeId="step-a"),
            TaskImplementationBinding(planNodeKey="B", acgNodeId="step-a"),
        ))
    without_dependency = TaskPlan(missionId=plan.mission_id, nodes=plan.nodes)
    with pytest.raises(ACGSemanticPreservationError, match="undeclared"):
        validate_bound_acg_semantics(without_dependency, blueprint, (
            TaskImplementationBinding(planNodeKey="A", acgNodeId="step-a"),
            TaskImplementationBinding(planNodeKey="B", acgNodeId="step-b"),
        ), require_exact=True)
