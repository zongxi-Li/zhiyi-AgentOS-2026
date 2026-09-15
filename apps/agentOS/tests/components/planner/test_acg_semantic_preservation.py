from __future__ import annotations

import pytest

from components.planner.acg_builder import ACGBuilder
from components.planner.acg_semantic_validator import (
    ACGSemanticPreservationError, validate_acg_semantic_preservation,
)
from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation, VerificationLoopPolicy
from support.acg.models import (
    ACGBlueprint, CapabilityCatalog, ControlNode, ControlType, EdgeType,
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
