from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from .errors import TopologyConflict


REPAIR_PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": [
                        "remove_relation", "add_relation", "replace_relation",
                        "add_verification_loop", "remove_invalid_feedback_relation",
                    ]},
                    "relationIndex": {"type": "integer", "minimum": 0},
                    "sourceKey": {"type": "string"}, "targetKey": {"type": "string"},
                    "relationType": {"type": "string", "enum": ["depends_on", "parent"]},
                    "bodyEntryKey": {"type": "string"}, "bodyExitKey": {"type": "string"},
                    "conditionSourceKey": {"type": "string"},
                },
                "required": ["op"],
            },
        }
    },
    "required": ["operations"],
}


def conflict_context(conflict: TopologyConflict) -> dict[str, Any]:
    return {
        "code": conflict.code.value, "phase": conflict.phase,
        "cycleNodes": list(conflict.cycle_nodes),
        "cycleEdges": [_edge_dict(edge) for edge in conflict.cycle_edges],
        "capabilityRequirements": [asdict(item) for item in conflict.capability_requirements],
        "bindingRejections": [asdict(item) for item in conflict.binding_rejections],
        "searchStatesExplored": conflict.search_states_explored,
    }


def apply_repair_patch(*, relations: list[dict[str, Any]], control_policies: list[dict[str, Any]],
                       patch: dict[str, Any], task_keys: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relation_slots: list[dict[str, Any] | None] = deepcopy(relations)
    additions: list[dict[str, Any]] = []
    next_policies = deepcopy(control_policies)
    for operation in patch.get("operations", []):
        op = operation.get("op")
        if op in {"remove_relation", "remove_invalid_feedback_relation"}:
            index = operation.get("relationIndex")
            if not isinstance(index, int) or not 0 <= index < len(relation_slots):
                raise ValueError("repair patch relationIndex is invalid")
            relation_slots[index] = None
        elif op in {"add_relation", "replace_relation"}:
            relation = _relation(operation, task_keys)
            if op == "replace_relation":
                index = operation.get("relationIndex")
                if not isinstance(index, int) or not 0 <= index < len(relation_slots):
                    raise ValueError("repair patch relationIndex is invalid")
                relation_slots[index] = relation
            else:
                additions.append(relation)
        elif op == "add_verification_loop":
            keys = {operation.get(name) for name in ("bodyEntryKey", "bodyExitKey", "conditionSourceKey")}
            if None in keys or not keys <= task_keys:
                raise ValueError("repair patch verification loop references unknown tasks")
            next_policies.append({
                "type": "verification_loop", "bodyEntryKey": operation["bodyEntryKey"],
                "bodyExitKey": operation["bodyExitKey"],
                "conditionSourceKey": operation["conditionSourceKey"], "maxRevisions": 2,
            })
        else:
            raise ValueError(f"unsupported topology repair operation: {op}")
    return [item for item in relation_slots if item is not None] + additions, next_policies


def _relation(operation, task_keys):
    source, target = operation.get("sourceKey"), operation.get("targetKey")
    if source not in task_keys or target not in task_keys:
        raise ValueError("repair patch relation references unknown tasks")
    return {"sourceKey": source, "targetKey": target,
            "relationType": operation.get("relationType", "depends_on")}


def _edge_dict(edge):
    return {
        "sourceKey": edge.source_key, "targetKey": edge.target_key,
        "relationType": edge.relation_type, "origin": edge.origin.value,
        "mutationPolicy": edge.mutation_policy.value, "reason": edge.reason,
        "requirementId": edge.requirement_id, "originalRelationIndex": edge.original_relation_index,
    }
