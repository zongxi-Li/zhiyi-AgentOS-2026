from __future__ import annotations

from dataclasses import dataclass

from contracts.planning import PlannedTask, SemanticTaskRelationType

from .errors import TopologyCompileError, TopologyConflict, TopologyConflictCode
from .model import (CapabilityBindingAudit, CapabilityBindingCandidate, CapabilityBindingRejection,
                    CapabilityBindingScore, CapabilityRequirement, EdgeMutationPolicy, EdgeOrigin,
                    TopologyEdge)


@dataclass
class _SearchState:
    explored: int = 0
    backtracks: int = 0


class CapabilityBindingSolver:
    def __init__(self, *, max_search_states: int = 512) -> None:
        if max_search_states < 1:
            raise ValueError("max_search_states must be positive")
        self.max_search_states = max_search_states

    def solve(self, *, nodes: list[PlannedTask], requirements: list[CapabilityRequirement],
              base_edges: list[TopologyEdge]) -> CapabilityBindingAudit:
        positions = {node.key: index for index, node in enumerate(nodes)}
        explicit_pairs = {(edge.source_key, edge.target_key) for edge in base_edges}
        ordered: dict[str, tuple[CapabilityBindingCandidate, ...]] = {}
        for requirement in requirements:
            candidates = [CapabilityBindingCandidate(
                requirement_id=requirement.requirement_id, producer_task_key=key,
                consumer_task_key=requirement.consumer_task_key,
                score=CapabilityBindingScore(
                    explicit_dependency_rank=0 if (key, requirement.consumer_task_key) in explicit_pairs else 1,
                    preceding_rank=0 if positions[key] < positions[requirement.consumer_task_key] else 1,
                    ordinal_distance=abs(positions[key] - positions[requirement.consumer_task_key]),
                    producer_task_key=key,
                ),
            ) for key in requirement.candidate_producer_keys]
            ordered[requirement.requirement_id] = tuple(sorted(candidates, key=lambda item: item.score))
        viable_counts = {
            requirement.requirement_id: sum(
                _find_path(base_edges, candidate.consumer_task_key, candidate.producer_task_key) is None
                for candidate in ordered[requirement.requirement_id]
            )
            for requirement in requirements
        }
        requirement_order = sorted(
            requirements,
            key=lambda item: (viable_counts[item.requirement_id], item.consumer_task_key, item.requirement_id),
        )
        state = _SearchState(); rejections: list[CapabilityBindingRejection] = []

        def search(index: int, selected: list[TopologyEdge]) -> list[TopologyEdge] | None:
            if index == len(requirement_order): return list(selected)
            requirement = requirement_order[index]
            for candidate in ordered[requirement.requirement_id]:
                state.explored += 1
                if state.explored > self.max_search_states:
                    raise self._failure(TopologyConflictCode.CAPABILITY_BINDING_SEARCH_EXHAUSTED,
                                        requirements, rejections, state.explored, base_edges)
                path = _find_path([*base_edges, *selected], candidate.consumer_task_key,
                                  candidate.producer_task_key)
                if path is not None:
                    rejections.append(CapabilityBindingRejection(
                        candidate.requirement_id, candidate.producer_task_key,
                        candidate.consumer_task_key, "cycle", path,
                    )); continue
                edge = TopologyEdge(
                    candidate.producer_task_key, candidate.consumer_task_key,
                    SemanticTaskRelationType.DEPENDS_ON.value, EdgeOrigin.CAPABILITY_CATALOG,
                    EdgeMutationPolicy.REBINDABLE,
                    reason=(f"required capability {requirement.producer_capability} -> "
                            f"{requirement.consumer_capability}"),
                    requirement_id=requirement.requirement_id,
                )
                result = search(index + 1, [*selected, edge])
                if result is not None: return result
                state.backtracks += 1
                rejections.append(CapabilityBindingRejection(
                    candidate.requirement_id, candidate.producer_task_key,
                    candidate.consumer_task_key, "downstream_unsatisfied",
                ))
            return None

        selected = search(0, [])
        if selected is None:
            raise self._failure(TopologyConflictCode.CAPABILITY_BINDING_CONFLICT,
                                requirements, rejections, state.explored, base_edges)
        return CapabilityBindingAudit(
            ordered_candidates=tuple((item.requirement_id, ordered[item.requirement_id])
                                     for item in requirement_order),
            selected_bindings=tuple(selected), rejected_candidates=tuple(rejections),
            search_states_explored=state.explored, backtrack_count=state.backtracks,
        )

    @staticmethod
    def _failure(code, requirements, rejections, explored, base_edges):
        cycle_rejection = next((item for item in rejections if item.reason == "cycle" and item.path), None)
        cycle_nodes: tuple[str, ...] = ()
        cycle_edges: tuple[TopologyEdge, ...] = ()
        if cycle_rejection is not None:
            catalog_edge = TopologyEdge(
                cycle_rejection.producer_task_key, cycle_rejection.consumer_task_key,
                SemanticTaskRelationType.DEPENDS_ON.value, EdgeOrigin.CAPABILITY_CATALOG,
                EdgeMutationPolicy.REBINDABLE, requirement_id=cycle_rejection.requirement_id,
                reason="rejected capability binding candidate",
            )
            cycle_nodes = (cycle_rejection.producer_task_key, *cycle_rejection.path)
            by_pair = {(edge.source_key, edge.target_key): edge for edge in base_edges}
            cycle_edges = (catalog_edge, *(
                by_pair[(source, target)]
                for source, target in zip(cycle_rejection.path, cycle_rejection.path[1:])
            ))
        conflict = TopologyConflict(
            code=code, phase="capability_binding",
            cycle_nodes=cycle_nodes, cycle_edges=cycle_edges,
            capability_requirements=tuple(requirements),
            binding_rejections=tuple(rejections), search_states_explored=explored,
            repairable_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.REPAIRABLE),
            rebindable_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.REBINDABLE),
            regenerable_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.REGENERABLE),
            fixed_edges=tuple(edge for edge in cycle_edges if edge.mutation_policy is EdgeMutationPolicy.FIXED),
        )
        return TopologyCompileError(conflict, f"{code.value}: no globally valid capability assignment")


def _find_path(edges: list[TopologyEdge], start: str, target: str) -> tuple[str, ...] | None:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if edge.relation_type == SemanticTaskRelationType.DEPENDS_ON.value:
            adjacency.setdefault(edge.source_key, []).append(edge.target_key)
    pending = [(start, (start,))]; visited: set[str] = set()
    while pending:
        current, path = pending.pop()
        if current == target: return path
        if current in visited: continue
        visited.add(current)
        for successor in reversed(sorted(adjacency.get(current, []))):
            if successor not in visited: pending.append((successor, (*path, successor)))
    return None
