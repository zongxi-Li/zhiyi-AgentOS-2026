from __future__ import annotations

from collections.abc import Sequence

from contracts.planning import SemanticTaskRelationType, TaskImplementationBinding, TaskPlan
from support.acg.models import ACGBlueprint, ControlNode, ControlType, EdgeType, StepNode


class ACGSemanticPreservationError(ValueError):
    pass


def validate_acg_semantic_preservation(task_plan: TaskPlan, blueprint: ACGBlueprint) -> None:
    """Prove that Builder lowering preserves semantic happens-before relations."""
    by_key: dict[str, StepNode] = {}
    for step in blueprint.step_nodes():
        key = step.metadata.get("taskPlanKey")
        if isinstance(key, str):
            if key in by_key:
                raise ACGSemanticPreservationError(f"duplicate ACG taskPlanKey mapping: {key}")
            by_key[key] = step
    expected = {node.key for node in task_plan.nodes}
    if set(by_key) != expected:
        missing = sorted(expected - set(by_key))
        extra = sorted(set(by_key) - expected)
        raise ACGSemanticPreservationError(
            f"ACG taskPlanKey mapping mismatch; missing={missing}, extra={extra}"
        )

    # ACGGraphCompiler and ACGExecutionGraph use DEPENDENCY exclusively for
    # ordinary ready-set predecessors. Other edge types are not scheduling proof.
    adjacency = _dependency_adjacency(blueprint)

    for relation in task_plan.relations:
        if relation.relation_type is not SemanticTaskRelationType.DEPENDS_ON:
            continue
        source = by_key[relation.source_key].node_id
        target = by_key[relation.target_key].node_id
        if not _has_path(adjacency, source, target):
            reverse = _has_path(adjacency, target, source)
            detail = " (reversed in execution graph)" if reverse else ""
            raise ACGSemanticPreservationError(
                f"semantic dependency not preserved: {relation.source_key} -> "
                f"{relation.target_key}{detail}"
            )

    loop_controls = [
        node for node in blueprint.nodes
        if isinstance(node, ControlNode) and node.control_type is ControlType.LOOP
        and node.metadata.get("taskPlanPolicy") == "verification_loop"
    ]
    if len(loop_controls) != len(task_plan.control_policies):
        raise ACGSemanticPreservationError(
            "verification loop policies were not preserved as LOOP controls"
        )
    semantic_pairs = {
        (item.source_key, item.target_key) for item in task_plan.relations
        if item.relation_type is SemanticTaskRelationType.DEPENDS_ON
    }
    for policy in task_plan.control_policies:
        if (policy.body_exit_key, policy.body_entry_key) in semantic_pairs:
            raise ACGSemanticPreservationError(
                "verification loop was reconstructed as a static semantic back edge"
            )


def _dependency_adjacency(blueprint: ACGBlueprint) -> dict[str, list[str]]:
    adjacency: dict[str, list[str]] = {}
    for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY):
        adjacency.setdefault(edge.source_id, []).append(edge.target_id)
    return adjacency


def semantic_reachability_projection(
    blueprint: ACGBlueprint,
    bindings: Sequence[TaskImplementationBinding],
) -> frozenset[tuple[str, str]]:
    """Project scheduling reachability onto explicitly bound semantic tasks."""
    active_steps = {
        step.node_id for step in blueprint.step_nodes()
        if str(step.metadata.get("lifecycleStatus", "active")).lower() != "retired"
    }
    keys = [item.plan_node_key for item in bindings]
    step_ids = [item.acg_node_id for item in bindings]
    if (len(keys) != len(set(keys)) or len(step_ids) != len(set(step_ids))
            or set(step_ids) != active_steps):
        raise ACGSemanticPreservationError("semantic bindings must cover each active Step exactly once")
    adjacency = _dependency_adjacency(blueprint)
    return frozenset(
        (source.plan_node_key, target.plan_node_key)
        for source in bindings for target in bindings
        if source != target and _has_path(adjacency, source.acg_node_id, target.acg_node_id)
    )


def validate_bound_acg_semantics(
    task_plan: TaskPlan,
    blueprint: ACGBlueprint,
    bindings: Sequence[TaskImplementationBinding],
    *,
    require_exact: bool = False,
) -> None:
    """Validate the explicit TaskPlan to Blueprint authority boundary."""
    keys = {node.key for node in task_plan.nodes}
    if {item.plan_node_key for item in bindings} != keys:
        raise ACGSemanticPreservationError("semantic bindings do not cover the complete TaskPlan")
    projection = semantic_reachability_projection(blueprint, bindings)
    plan_adjacency: dict[str, list[str]] = {}
    for relation in task_plan.relations:
        if relation.relation_type is not SemanticTaskRelationType.DEPENDS_ON:
            continue
        plan_adjacency.setdefault(relation.source_key, []).append(relation.target_key)
        pair = (relation.source_key, relation.target_key)
        if pair not in projection:
            reverse = (pair[1], pair[0]) in projection
            detail = " (reversed in execution graph)" if reverse else ""
            raise ACGSemanticPreservationError(
                f"semantic dependency not preserved: {pair[0]} -> {pair[1]}{detail}"
            )
    if require_exact:
        extra = sorted(pair for pair in projection
                       if not _has_path(plan_adjacency, pair[0], pair[1]))
        if extra:
            raise ACGSemanticPreservationError(
                f"Blueprint adds undeclared semantic dependency: {extra}"
            )


def _has_path(adjacency: dict[str, list[str]], start: str, target: str) -> bool:
    pending = [start]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(reversed(adjacency.get(current, ())))
    return False


__all__ = [
    "ACGSemanticPreservationError", "validate_acg_semantic_preservation",
    "validate_bound_acg_semantics", "semantic_reachability_projection",
]
