"""Validated, immutable ACG graph revision patching."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from contracts.recovery import GraphPatch
from support.acg.models import ACGBlueprint, ACGEdge, parse_node, validate_blueprint


class GraphPatchConflictError(ValueError):
    """The patch targets stale or conflicting graph state."""


@dataclass(frozen=True)
class AppliedGraphPatch:
    blueprint: ACGBlueprint
    checksum: str
    idempotent_replay: bool = False


class GraphPatchService:
    """Apply additive/re-wiring patches without mutating the source blueprint."""

    def apply(
        self,
        blueprint: ACGBlueprint,
        patch: GraphPatch,
        *,
        completed_step_ids: set[str] | None = None,
        active_step_ids: set[str] | None = None,
    ) -> AppliedGraphPatch:
        checksum = patch.checksum()
        applied = list(blueprint.metadata.get("appliedGraphPatches") or [])
        previous = next(
            (item for item in applied if isinstance(item, dict) and item.get("patchId") == patch.patch_id),
            None,
        )
        if previous is not None:
            if previous.get("checksum") != checksum:
                raise GraphPatchConflictError(
                    f"graph patch id already exists with different content: {patch.patch_id}"
                )
            return AppliedGraphPatch(
                blueprint=blueprint.model_copy(deep=True),
                checksum=checksum,
                idempotent_replay=True,
            )

        if patch.graph_id != blueprint.graph_id:
            raise GraphPatchConflictError("graph patch graphId does not match blueprint")
        if patch.base_graph_version != blueprint.version:
            raise GraphPatchConflictError(
                f"graph patch version {patch.base_graph_version} does not match current version {blueprint.version}"
            )
        if not patch.add_nodes and not patch.add_edges and not patch.remove_edge_ids:
            raise ValueError("graph patch must contain at least one operation")

        completed = set(completed_step_ids or ())
        active = set(active_step_ids or ())
        if active:
            raise GraphPatchConflictError("graph patch cannot be applied while nodes are active")

        result = blueprint.model_copy(deep=True)
        existing_node_ids = {node.node_id for node in result.nodes}
        additions = [parse_node(item) for item in deepcopy(patch.add_nodes)]
        duplicate_nodes = sorted(node.node_id for node in additions if node.node_id in existing_node_ids)
        if duplicate_nodes:
            raise GraphPatchConflictError(
                "graph patch cannot replace existing nodes: " + ", ".join(duplicate_nodes)
            )

        edge_by_id = {edge.edge_id: edge for edge in result.edges}
        missing_edges = sorted(set(patch.remove_edge_ids) - edge_by_id.keys())
        if missing_edges:
            raise GraphPatchConflictError(
                "graph patch removes unknown edges: " + ", ".join(missing_edges)
            )
        for edge_id in patch.remove_edge_ids:
            edge = edge_by_id[edge_id]
            if edge.target_id in completed:
                raise GraphPatchConflictError(
                    f"graph patch cannot rewire completed target step: {edge.target_id}"
                )

        result.nodes.extend(additions)
        result.edges = [edge for edge in result.edges if edge.edge_id not in set(patch.remove_edge_ids)]
        new_edges = [ACGEdge.model_validate(item) for item in deepcopy(patch.add_edges)]
        existing_edge_ids = {edge.edge_id for edge in result.edges}
        duplicates = sorted(edge.edge_id for edge in new_edges if edge.edge_id in existing_edge_ids)
        if duplicates:
            raise GraphPatchConflictError(
                "graph patch contains duplicate edge ids: " + ", ".join(duplicates)
            )
        result.edges.extend(new_edges)
        result.version = blueprint.version + 1
        result.metadata = deepcopy(result.metadata)
        result.metadata["appliedGraphPatches"] = [
            *applied,
            {
                "patchId": patch.patch_id,
                "idempotencyKey": patch.idempotency_key,
                "checksum": checksum,
                "baseGraphVersion": patch.base_graph_version,
                "graphVersion": result.version,
                "reason": patch.reason,
            },
        ]
        result.touch()
        validate_blueprint(result)
        return AppliedGraphPatch(blueprint=result, checksum=checksum)


__all__ = ["AppliedGraphPatch", "GraphPatchConflictError", "GraphPatchService"]
