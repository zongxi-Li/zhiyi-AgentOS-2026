"""Runtime graph adapter for the planner's immutable ACG packages."""

from __future__ import annotations

from contracts import stable_checksum
from contracts.compiled_acg import CompiledACGPackage
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from components.executor.graph import ACGConditionalRoute, ACGExecutionGraph, ACGNodeSpec
from contracts.acg.schema import ACGBlueprint, EdgeType
from components.planner import (
    ACGPackageCompiler, IncompleteACGCompilationError, UnsupportedCommunicationModeError,
)


class ACGGraphCompiler(ACGPackageCompiler):
    """Adapt the planner package into the executor runtime graph."""

    def compile(
        self,
        blueprint: ACGBlueprint,
        *,
        run_id: str | None = None,
        package: CompiledACGPackage | None = None,
    ) -> ACGExecutionGraph:
        """Build the runtime graph view exclusively from a compiled package."""
        compiled = package or self.compile_package(blueprint, run_id=run_id)
        if compiled.blueprint_id != blueprint.graph_id or compiled.blueprint_version != blueprint.version:
            raise IncompleteACGCompilationError("compiled package does not belong to blueprint")
        expected_hash = stable_checksum(blueprint.model_dump(by_alias=True, mode="json"))
        if compiled.blueprint_hash != expected_hash:
            raise IncompleteACGCompilationError("compiled package blueprint hash mismatch")

        controls = {rule.control_id: rule for rule in compiled.control_manifest.rules}
        node_specs: dict[str, ACGNodeSpec] = {}
        for node in compiled.nodes:
            control = controls.get(node.node_id)
            condition = None
            if control is not None and control.condition is not None:
                condition = ACGConditionalRoute(
                    source_step_id=control.condition.source_step_id,
                    json_pointer=control.condition.json_pointer,
                    operator=control.condition.operator,
                    targets_by_case=dict(control.condition.targets_by_case),
                    default_target=control.condition.default_target,
                    # The package's blueprint hash above authenticates this
                    # existing declaration. Keep it as local scheduling metadata;
                    # no persisted package/schema migration is introduced.
                    join_node_id=blueprint.get_node(node.node_id).join_node_id,
                )
            node_specs[node.node_id] = ACGNodeSpec(
                node_id=node.node_id,
                kind=node.kind.value,
                communication_mode=node.communication_mode.value,
                review_required=node.review_required,
                condition=condition,
                control_type=node.control_type,
            )
        dependency_edges = tuple(
            (edge.source_id, edge.target_id)
            for edge in compiled.edges
            if edge.edge_type == EdgeType.DEPENDENCY.value
        )
        return ACGExecutionGraph(
            nodes=tuple(node.node_id for node in compiled.nodes),
            edges=dependency_edges,
            node_specs=node_specs,
            communication_manifest=self._runtime_communication_manifest(
                compiled.communication_manifest
            ),
            compiled_package=compiled,
        )

    @staticmethod
    def _runtime_communication_manifest(spec):
        if not spec.run_id:
            return None
        return CommunicationManifest(
            run_id=spec.run_id,
            rules=tuple(CommunicationRule(
                producer_step_id=rule.producer_step_id,
                consumer_step_id=rule.consumer_step_id,
                allowed_fields=tuple(rule.allowed_fields),
                channel=rule.channel,
                max_tokens=rule.max_tokens,
            ) for rule in spec.rules),
            run_budget=spec.run_budget,
            step_budgets=spec.step_budgets,
            channel_budgets=spec.channel_budgets,
        )


__all__ = ["ACGGraphCompiler", "IncompleteACGCompilationError", "UnsupportedCommunicationModeError"]
