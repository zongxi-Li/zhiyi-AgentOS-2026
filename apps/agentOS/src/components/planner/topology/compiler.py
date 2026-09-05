from __future__ import annotations

from contracts.planning import PlannedTask, SemanticTaskRelationType, TaskPlanRelation, VerificationLoopPolicy

from .model import (CandidateTopology, CapabilityRequirement, EdgeMutationPolicy, EdgeOrigin,
                    TopologyCompilationAudit, TopologyCompileResult, TopologyEdge)
from .binding_solver import CapabilityBindingSolver
from .errors import TopologyCompileError, TopologyConflict, TopologyConflictCode
from .validator import validate_candidate


class TaskPlanTopologyCompiler:
    def __init__(self, capability_catalog, *, max_search_states: int = 512) -> None:
        self.capability_catalog = capability_catalog
        self.binding_solver = CapabilityBindingSolver(max_search_states=max_search_states)

    def compile(self, *, nodes: list[PlannedTask], raw_relations: list[TaskPlanRelation],
                control_policies: tuple[VerificationLoopPolicy, ...]) -> TopologyCompileResult:
        return self._compile(
            nodes=nodes, raw_relations=raw_relations, control_policies=control_policies,
            relation_origin=EdgeOrigin.MODEL,
            relation_mutation_policy=EdgeMutationPolicy.REPAIRABLE,
            normalize_reversed_requirements=True,
            require_all_catalog_dependencies=True,
        )

    def validate_existing_plan(
        self,
        *,
        nodes: list[PlannedTask],
        raw_relations: list[TaskPlanRelation],
        control_policies: tuple[VerificationLoopPolicy, ...],
        relation_origin: EdgeOrigin,
    ) -> TopologyCompileResult:
        """Validate a non-proposal semantic plan through the shared topology pipeline.

        Explicit relations from templates, deterministic fallback, and plan patches
        are fixed declarations.  They are never normalized away or offered to the
        model repair protocol.
        """
        if relation_origin not in {
            EdgeOrigin.TEMPLATE_DECLARED,
            EdgeOrigin.FALLBACK_GENERATED,
            EdgeOrigin.PLAN_PATCH,
        }:
            raise ValueError(f"unsupported existing-plan relation origin: {relation_origin}")
        return self._compile(
            nodes=nodes, raw_relations=raw_relations, control_policies=control_policies,
            relation_origin=relation_origin,
            relation_mutation_policy=EdgeMutationPolicy.FIXED,
            normalize_reversed_requirements=False,
            require_all_catalog_dependencies=False,
        )

    def _compile(
        self,
        *,
        nodes: list[PlannedTask],
        raw_relations: list[TaskPlanRelation],
        control_policies: tuple[VerificationLoopPolicy, ...],
        relation_origin: EdgeOrigin,
        relation_mutation_policy: EdgeMutationPolicy,
        normalize_reversed_requirements: bool,
        require_all_catalog_dependencies: bool,
    ) -> TopologyCompileResult:
        positions = {node.key: index for index, node in enumerate(nodes)}
        capabilities = {
            node.key: (node.capability_requirements[0] if node.capability_requirements else None)
            for node in nodes
        }
        edges: list[TopologyEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for index, relation in enumerate(raw_relations):
            source_cap = capabilities.get(relation.source_key)
            target_cap = capabilities.get(relation.target_key)
            if (normalize_reversed_requirements
                    and relation.relation_type == SemanticTaskRelationType.DEPENDS_ON
                    and source_cap and target_cap
                    and target_cap in self.capability_catalog.get(source_cap).depends_on):
                continue
            self._append(edges, seen, TopologyEdge(
                relation.source_key, relation.target_key, relation.relation_type.value,
                relation_origin, relation_mutation_policy,
                reason=("model relation proposal" if relation_origin is EdgeOrigin.MODEL
                        else f"{relation_origin.value} semantic relation"),
                original_relation_index=(index if relation_origin is EdgeOrigin.MODEL else None),
            ))
        # A cycle that already exists in the proposal remains a repairable
        # dependency-cycle conflict; it must not be misclassified by binding.
        validate_candidate(CandidateTopology(
            tuple(node.key for node in nodes), tuple(edges), (), control_policies, ()
        ))
        by_capability: dict[str, list[PlannedTask]] = {}
        for node in nodes:
            capability = capabilities[node.key]
            if capability is not None:
                by_capability.setdefault(capability, []).append(node)
        requirements: list[CapabilityRequirement] = []
        for consumer in nodes:
            consumer_cap = capabilities[consumer.key]
            if consumer_cap is None:
                continue
            for producer_cap in self.capability_catalog.get(consumer_cap).depends_on:
                candidates = by_capability.get(producer_cap, [])
                requirement = CapabilityRequirement(
                    requirement_id=f"catalog:{producer_cap}->{consumer_cap}:{consumer.key}",
                    producer_capability=producer_cap, consumer_capability=consumer_cap,
                    consumer_task_key=consumer.key,
                    candidate_producer_keys=tuple(item.key for item in candidates),
                )
                requirements.append(requirement)
                if not candidates:
                    if not require_all_catalog_dependencies:
                        requirements.pop()
                        continue
                    raise TopologyCompileError(
                        TopologyConflict(
                            code=TopologyConflictCode.CAPABILITY_BINDING_CONFLICT,
                            phase="capability_binding",
                            capability_requirements=tuple(requirements),
                            fixed_edges=tuple(
                                edge for edge in edges
                                if edge.mutation_policy is EdgeMutationPolicy.FIXED
                            ),
                        ),
                        f"task {consumer.key} requires missing predecessor capability {producer_cap}",
                    )
        binding_audit = self.binding_solver.solve(
            nodes=nodes, requirements=requirements, base_edges=edges
        )
        for edge in binding_audit.selected_bindings:
            self._append(edges, seen, edge)
        sinks = [node for node in nodes if capabilities[node.key] in {"verification", "artifact_generation"}]
        outgoing = {edge.source_key for edge in edges if edge.relation_type == SemanticTaskRelationType.DEPENDS_ON.value}
        for leaf in nodes:
            if leaf.key in outgoing or leaf in sinks:
                continue
            ordered = sorted(sinks, key=lambda node: (positions[node.key] <= positions[leaf.key], capabilities[node.key] != "artifact_generation", positions[node.key]))
            for sink in ordered:
                if not self._has_path(edges, sink.key, leaf.key):
                    self._append(edges, seen, TopologyEdge(
                        leaf.key, sink.key, SemanticTaskRelationType.DEPENDS_ON.value,
                        EdgeOrigin.TERMINAL_CONNECTOR, EdgeMutationPolicy.REGENERABLE,
                        reason="connect semantic leaf to declared result sink",
                    )); outgoing.add(leaf.key); break
            else:
                if sinks:
                    raise TopologyCompileError(
                        TopologyConflict(
                            code=TopologyConflictCode.TERMINAL_CONNECTION_CONFLICT,
                            phase="terminal_completion",
                            capability_requirements=tuple(requirements),
                            fixed_edges=tuple(
                                edge for edge in edges
                                if edge.mutation_policy is EdgeMutationPolicy.FIXED
                            ),
                            rebindable_edges=tuple(
                                edge for edge in edges
                                if edge.mutation_policy is EdgeMutationPolicy.REBINDABLE
                            ),
                        ),
                        f"terminal task {leaf.key} cannot reach a verification or artifact sink",
                    )
        candidate = CandidateTopology(
            tuple(node.key for node in nodes), tuple(edges), tuple(requirements),
            control_policies, binding_audit.selected_bindings,
        )
        validate_candidate(candidate)
        audit = TopologyCompilationAudit(
            original_model_relations=tuple(raw_relations),
            normalized_model_edges=tuple(
                edge for edge in edges if edge.origin is relation_origin
            ),
            capability_requirements=tuple(requirements),
            selected_concrete_bindings=binding_audit.selected_bindings,
            terminal_edges=tuple(edge for edge in edges if edge.origin is EdgeOrigin.TERMINAL_CONNECTOR),
            binding_audit=binding_audit,
        )
        return TopologyCompileResult(
            candidate, tuple(edge.to_relation() for edge in edges), control_policies, audit
        )

    @staticmethod
    def _append(edges, seen, edge):
        identity = (edge.source_key, edge.target_key, edge.relation_type)
        if identity not in seen: edges.append(edge); seen.add(identity)

    @staticmethod
    def _has_path(edges, start, target):
        adjacency: dict[str, list[str]] = {}
        for edge in edges:
            if edge.relation_type == SemanticTaskRelationType.DEPENDS_ON.value:
                adjacency.setdefault(edge.source_key, []).append(edge.target_key)
        pending = [start]; visited = set()
        while pending:
            current = pending.pop()
            if current == target: return True
            if current in visited: continue
            visited.add(current); pending.extend(reversed(adjacency.get(current, [])))
        return False
