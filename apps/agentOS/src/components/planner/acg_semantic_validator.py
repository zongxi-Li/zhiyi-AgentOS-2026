from __future__ import annotations

from contracts.planning import SemanticTaskRelationType, TaskPlan
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
    adjacency: dict[str, list[str]] = {}
    for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY):
        adjacency.setdefault(edge.source_id, []).append(edge.target_id)
    for successors in adjacency.values():
        successors.sort()

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


__all__ = ["ACGSemanticPreservationError", "validate_acg_semantic_preservation"]
