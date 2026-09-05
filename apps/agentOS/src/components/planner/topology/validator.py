from __future__ import annotations

from contracts.planning import SemanticTaskRelationType

from .errors import TopologyCompileError, TopologyConflict, TopologyConflictCode
from .model import CandidateTopology, EdgeMutationPolicy, TopologyEdge


def validate_candidate(candidate: CandidateTopology) -> None:
    known = set(candidate.task_keys)
    required_ids = {item.requirement_id for item in candidate.capability_requirements}
    selected_ids = {edge.requirement_id for edge in candidate.selected_bindings}
    if selected_ids != required_ids or any(
        edge.origin.value != "capability_catalog"
        or edge.mutation_policy is not EdgeMutationPolicy.REBINDABLE
        for edge in candidate.selected_bindings
    ):
        raise TopologyCompileError(
            TopologyConflict(
                code=TopologyConflictCode.CAPABILITY_BINDING_CONFLICT,
                phase="final_validation",
                capability_requirements=candidate.capability_requirements,
            ),
            "candidate topology does not satisfy every capability requirement",
        )
    for edge in candidate.edges:
        if edge.source_key not in known or edge.target_key not in known:
            raise TopologyCompileError(
                TopologyConflict(code=TopologyConflictCode.UNKNOWN_TASK_REFERENCE, phase="final_validation"),
                "candidate topology edge references an unknown task",
            )
        if edge.source_key == edge.target_key:
            raise TopologyCompileError(
                TopologyConflict(code=TopologyConflictCode.SELF_DEPENDENCY, phase="final_validation"),
                f"candidate topology self dependency: {edge.source_key}",
            )
    cycle = _find_cycle(candidate.edges)
    if cycle is not None:
        by_pair = {(edge.source_key, edge.target_key): edge for edge in candidate.edges}
        cycle_edges = tuple(by_pair[(source, target)] for source, target in zip(cycle, cycle[1:]))
        conflict = TopologyConflict(
            code=TopologyConflictCode.DEPENDENCY_CYCLE, phase="final_validation",
            cycle_nodes=cycle, cycle_edges=cycle_edges,
            capability_requirements=candidate.capability_requirements,
            repairable_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.REPAIRABLE),
            rebindable_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.REBINDABLE),
            regenerable_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.REGENERABLE),
            fixed_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.FIXED),
        )
        detail = " -> ".join(cycle)
        origins = ", ".join(
            f"{edge.source_key}->{edge.target_key}:{edge.origin.value}" for edge in cycle_edges
        )
        raise TopologyCompileError(conflict, f"TaskPlan dependency cycle: {detail}; edges: {origins}")
    for policy in candidate.control_policies:
        if not {policy.body_entry_key, policy.body_exit_key, policy.condition_source_key} <= known:
            raise TopologyCompileError(
                TopologyConflict(code=TopologyConflictCode.INVALID_CONTROL_POLICY, phase="final_validation"),
                "control policy references an unknown task",
            )


def _find_cycle(edges: tuple[TopologyEdge, ...]) -> tuple[str, ...] | None:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if edge.relation_type != SemanticTaskRelationType.DEPENDS_ON.value:
            continue
        adjacency.setdefault(edge.source_key, []).append(edge.target_key)
        adjacency.setdefault(edge.target_key, [])
    state: dict[str, int] = {}
    stack: list[str] = []
    positions: dict[str, int] = {}
    def visit(node: str):
        state[node] = 1; positions[node] = len(stack); stack.append(node)
        for successor in adjacency.get(node, []):
            if state.get(successor, 0) == 0:
                found = visit(successor)
                if found: return found
            elif state.get(successor) == 1:
                return (*stack[positions[successor]:], successor)
        stack.pop(); positions.pop(node, None); state[node] = 2
        return None
    for node in adjacency:
        if state.get(node, 0) == 0:
            found = visit(node)
            if found: return _canonical_cycle(found)
    return None


def _canonical_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    """Rotate a closed cycle to a stable task-key origin for audit output."""
    body = cycle[:-1]
    start = min(range(len(body)), key=body.__getitem__)
    rotated = (*body[start:], *body[:start])
    return (*rotated, rotated[0])
