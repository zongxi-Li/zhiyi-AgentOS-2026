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
    def __init__(self, *, max_search_states: int | None = None) -> None:
        if max_search_states is not None and max_search_states < 1:
            raise ValueError("max_search_states must be positive")
        # Compatibility only. A finite valid graph does not become invalid
        # because its historical requirements exceeded an arbitrary counter.
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
        state = _SearchState()
        rejections: list[CapabilityBindingRejection] = []

        # Explicit DFS frames avoid turning graph growth into Python recursion
        # exhaustion. Each frame advances through a finite ordered candidate set;
        # rejected cycles and genuinely exhausted alternatives drive backtracking.
        selected: list[TopologyEdge] | None = []
        next_candidates = [0] * len(requirement_order)
        index = 0
        while index < len(requirement_order):
            requirement = requirement_order[index]
            candidates = ordered[requirement.requirement_id]
            while next_candidates[index] < len(candidates):
                candidate = candidates[next_candidates[index]]
                next_candidates[index] += 1
                state.explored += 1
                path = _find_path([*base_edges, *selected], candidate.consumer_task_key,
                                  candidate.producer_task_key)
                if path is not None:
                    rejections.append(CapabilityBindingRejection(
                        candidate.requirement_id, candidate.producer_task_key,
                        candidate.consumer_task_key, "cycle", path,
                    ))
                    continue
                edge = TopologyEdge(
                    candidate.producer_task_key, candidate.consumer_task_key,
                    SemanticTaskRelationType.DEPENDS_ON.value, EdgeOrigin.CAPABILITY_CATALOG,
                    EdgeMutationPolicy.REBINDABLE,
                    reason=(f"required capability {requirement.producer_capability} -> "
                            f"{requirement.consumer_capability}"),
                    requirement_id=requirement.requirement_id,
                )
                selected.append(edge)
                index += 1
                if index < len(requirement_order):
                    next_candidates[index] = 0
                break
            else:
                if index == 0:
                    selected = None
                    break
                next_candidates[index] = 0
                index -= 1
                edge = selected.pop()
                state.backtracks += 1
                rejections.append(CapabilityBindingRejection(
                    edge.requirement_id, edge.source_key,
                    edge.target_key, "downstream_unsatisfied",
                ))
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
            # A cycle witness can traverse an earlier selected binding that was
            # subsequently rolled back. Its rejected assignment remains part of
            # the audit, so reconstruct that catalog edge instead of losing the
            # witness or mistaking it for a base/model edge.
            for rejected in rejections:
                by_pair.setdefault((rejected.producer_task_key, rejected.consumer_task_key), TopologyEdge(
                    rejected.producer_task_key, rejected.consumer_task_key,
                    SemanticTaskRelationType.DEPENDS_ON.value, EdgeOrigin.CAPABILITY_CATALOG,
                    EdgeMutationPolicy.REBINDABLE, requirement_id=rejected.requirement_id,
                    reason="capability binding candidate from rejected assignment",
                ))
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
    pending = [(start, (start,))]
    visited: set[str] = set()
    while pending:
        current, path = pending.pop()
        if current == target:
            return path
        if current in visited:
            continue
        visited.add(current)
        for successor in reversed(sorted(adjacency.get(current, []))):
            if successor not in visited:
                pending.append((successor, (*path, successor)))
    return None
