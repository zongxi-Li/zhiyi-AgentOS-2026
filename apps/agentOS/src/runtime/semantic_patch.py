"""TaskPlan-first semantic revision and derived graph-diff support."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

from components.planner.acg_lowerer import ACGLowerer
from components.planner.semantic_patch_planning import (
    build_semantic_patch_lowering_input,
)
from components.planner.service import apply_task_plan_patch
from contracts.planning import TaskImplementationBinding, TaskPlan
from contracts.recovery import GraphPatch, SemanticPatchRequest
from support.acg.capabilities import CapabilityCatalog
from support.acg.native_capabilities import build_default_capability_catalog
from support.acg.schema import ACGBlueprint


@dataclass(frozen=True)
class SemanticPatchResult:
    blueprint: ACGBlueprint
    next_plan: TaskPlan
    next_bindings: tuple[TaskImplementationBinding, ...]
    topology_audits: tuple[dict[str, Any], ...]


class SemanticGraphPatchService:
    """Revalidate a TaskPlan revision and deterministically lower a new ACG."""

    def apply(
        self,
        *,
        blueprint: ACGBlueprint,
        request: SemanticPatchRequest,
        current_plan: TaskPlan,
        base_bindings: tuple[TaskImplementationBinding, ...],
        agent_registry,
        domain: str,
        capability_catalog: CapabilityCatalog | None = None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> SemanticPatchResult:
        catalog = capability_catalog or build_default_capability_catalog()
        topology_audits: list[dict[str, Any]] = []

        def record_audit(item: dict[str, Any]) -> None:
            topology_audits.append(item)
            if audit_sink is not None:
                audit_sink(item)

        next_plan = apply_task_plan_patch(
            current_plan,
            request.task_plan_patch,
            catalog,
            audit_sink=record_audit,
        )
        changed_keys = {
            *request.task_plan_patch.replace_keys,
            *(task.key for task in request.task_plan_patch.add_nodes),
        }
        lowering_input = build_semantic_patch_lowering_input(
            blueprint=blueprint,
            current_plan=current_plan,
            next_plan=next_plan,
            base_bindings=base_bindings,
            changed_keys=changed_keys,
            capability_catalog=catalog,
            agent_registry=agent_registry,
            domain=domain,
        )
        bindings = lowering_input.implementation_bindings
        revised = ACGLowerer().lower(lowering_input)
        revised.graph_id = blueprint.graph_id
        revised.version = blueprint.version + 1
        return SemanticPatchResult(
            blueprint=revised,
            next_plan=next_plan,
            next_bindings=bindings,
            topology_audits=tuple(topology_audits),
        )

def derive_graph_patch(
    old: ACGBlueprint,
    new: ACGBlueprint,
    *,
    patch_id: str,
    reason: str = "",
) -> GraphPatch:
    """Describe the difference between two canonical graphs without mutating either."""

    if old.graph_id != new.graph_id:
        raise ValueError("cannot derive GraphPatch across different graph identities")
    old_nodes = {node.node_id: node for node in old.nodes}
    new_nodes = {node.node_id: node for node in new.nodes}

    def node_payload(node) -> dict[str, Any]:
        return node.model_dump(by_alias=True, mode="json")

    def payload_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    updated_nodes = []
    for node_id in sorted(old_nodes.keys() & new_nodes.keys()):
        before = node_payload(old_nodes[node_id])
        after = node_payload(new_nodes[node_id])
        if before == after:
            continue
        updated_nodes.append({
            "nodeId": node_id,
            "before": before,
            "after": after,
            "beforeHash": payload_hash(before),
            "afterHash": payload_hash(after),
        })

    def edge_projection(edge) -> tuple[str, str, str]:
        return edge.source_id, edge.target_id, edge.edge_type.value

    old_edges = {edge_projection(edge) for edge in old.edges}
    new_edges = {edge_projection(edge) for edge in new.edges}

    def edge_payload(edge: tuple[str, str, str]) -> dict[str, str]:
        source, target, edge_type = edge
        return {"sourceId": source, "targetId": target, "edgeType": edge_type}
    return GraphPatch(
        patchId=patch_id,
        graphId=old.graph_id,
        baseGraphVersion=old.version,
        graphVersion=new.version,
        addedNodes=tuple(
            node_payload(new_nodes[node_id])
            for node_id in sorted(new_nodes.keys() - old_nodes.keys())
        ),
        updatedNodes=tuple(updated_nodes),
        removedNodeIds=tuple(sorted(old_nodes.keys() - new_nodes.keys())),
        addedEdges=tuple(edge_payload(edge) for edge in sorted(new_edges - old_edges)),
        removedEdges=tuple(edge_payload(edge) for edge in sorted(old_edges - new_edges)),
        reason=reason,
    )


__all__ = ["SemanticGraphPatchService", "SemanticPatchResult", "derive_graph_patch"]
