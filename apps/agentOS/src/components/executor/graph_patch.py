"""Validated, immutable ACG graph revision patching."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from contracts.recovery import GraphPatch
from support.acg.schema import ACGBlueprint, ACGEdge, parse_node
from support.acg.validation import validate_blueprint


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
        if not any((patch.add_nodes, patch.add_edges, patch.remove_edge_ids, patch.retire_node_ids, patch.replace_nodes)):
            raise ValueError("graph patch must contain at least one operation")

        completed = set(completed_step_ids or ())
        active = set(active_step_ids or ())
        if active:
            raise GraphPatchConflictError("graph patch cannot be applied while nodes are active")

        result = blueprint.model_copy(deep=True)
        existing_node_ids = {node.node_id for node in result.nodes}
        unknown_retired = sorted(set(patch.retire_node_ids) - existing_node_ids)
        unknown_replaced = sorted(set(patch.replace_nodes) - existing_node_ids)
        if unknown_retired or unknown_replaced:
            raise GraphPatchConflictError(
                f"graph patch references unknown nodes: {unknown_retired + unknown_replaced}"
            )
        if completed & (set(patch.retire_node_ids) | set(patch.replace_nodes)):
            raise GraphPatchConflictError("graph patch cannot retire or replace completed nodes")
        replacement_map: dict[str, str] = {}
        replacement_nodes = []
        for old_id, raw_node in patch.replace_nodes.items():
            replacement = parse_node(deepcopy(raw_node))
            if replacement.node_id in existing_node_ids:
                raise GraphPatchConflictError("replacement node must use a new nodeId")
            replacement.metadata = deepcopy(replacement.metadata)
            replacement.metadata["supersedesAcgNodeId"] = old_id
            replacement_nodes.append(replacement)
            replacement_map[old_id] = replacement.node_id
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

        retired = set(patch.retire_node_ids) | set(patch.replace_nodes)
        for node in result.nodes:
            if node.node_id in retired:
                node.metadata = deepcopy(node.metadata)
                node.metadata["lifecycleStatus"] = "retired"
        result.nodes.extend([*replacement_nodes, *additions])
        result.edges = [edge for edge in result.edges if edge.edge_id not in set(patch.remove_edge_ids)]
        for edge in result.edges:
            if edge.source_id in replacement_map:
                edge.source_id = replacement_map[edge.source_id]
            if edge.target_id in replacement_map:
                edge.target_id = replacement_map[edge.target_id]
        new_edges = [ACGEdge.model_validate(item) for item in deepcopy(patch.add_edges)]
        existing_edge_ids = {edge.edge_id for edge in result.edges}
        duplicates = sorted(edge.edge_id for edge in new_edges if edge.edge_id in existing_edge_ids)
        if duplicates:
            raise GraphPatchConflictError(
                "graph patch contains duplicate edge ids: " + ", ".join(duplicates)
            )
        result.edges.extend(new_edges)
        retired_executable_ids = {
            node.node_id
            for node in result.step_nodes()
            if str(node.metadata.get("lifecycleStatus", "active")).lower() == "retired"
        }
        connected_retired = sorted({
            node_id
            for edge in result.edges
            for node_id in (edge.source_id, edge.target_id)
            if node_id in retired_executable_ids
        })
        if connected_retired:
            raise GraphPatchConflictError(
                "retired executable nodes must have all edges removed or reconnected: "
                + ", ".join(connected_retired)
            )
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
