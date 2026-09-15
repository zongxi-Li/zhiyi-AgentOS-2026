from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from contracts.planning import PlannedTask, TaskPlanRelation, VerificationLoopPolicy
from support.acg.models import CapabilityCatalog

from .errors import TopologyCompileError
from .model import TopologyCompileResult


TOPOLOGY_COMPILER_VERSION = "task-plan-topology-v5b"


def catalog_fingerprint(catalog: CapabilityCatalog) -> str:
    payload = [
        {
            "capabilityId": item.capability_id,
            "dependsOn": sorted(item.depends_on),
            "optionalDependencies": sorted(item.optional_dependencies),
        }
        for item in catalog.available()
    ]
    return _fingerprint(payload)


def successful_topology_audit(
    *,
    result: TopologyCompileResult,
    nodes: Sequence[PlannedTask],
    catalog: CapabilityCatalog,
    producer_kind: str,
    catalog_source: str,
    capability_coverage_mode: str,
    repair_attempts: int = 0,
    repair_operation_types: Sequence[str] = (),
) -> dict[str, Any]:
    catalog_hash = catalog_fingerprint(catalog)
    topology_payload = {
        "compilerVersion": TOPOLOGY_COMPILER_VERSION,
        "catalogFingerprint": catalog_hash,
        "tasks": sorted(node.key for node in nodes),
        "relations": sorted(
            (edge.source_key, edge.target_key, edge.relation_type)
            for edge in result.candidate.edges
        ),
        "controlPolicies": sorted(
            json.dumps(item.model_dump(by_alias=True, mode="json"), sort_keys=True)
            for item in result.control_policies
        ),
        "selectedBindings": sorted(
            (edge.requirement_id, edge.source_key, edge.target_key)
            for edge in result.candidate.selected_bindings
        ),
    }
    binding = result.audit.binding_audit
    return {
        "compilerVersion": TOPOLOGY_COMPILER_VERSION,
        "producerKind": producer_kind,
        "catalogSource": catalog_source,
        "catalogFingerprint": catalog_hash,
        "capabilityCoverageMode": capability_coverage_mode,
        "taskCount": len(nodes),
        "semanticEdgeCount": len(result.task_plan_relations),
        "topologyFingerprint": _fingerprint(topology_payload),
        "capabilityRequirements": [
            {
                "requirementId": item.requirement_id,
                "producerCapability": item.producer_capability,
                "consumerCapability": item.consumer_capability,
                "consumerTaskKey": item.consumer_task_key,
            }
            for item in result.audit.capability_requirements
        ],
        "selectedBindings": [
            {
                "requirementId": edge.requirement_id,
                "producerTaskKey": edge.source_key,
                "consumerTaskKey": edge.target_key,
            }
            for edge in binding.selected_bindings
        ],
        "bindingSearch": {
            "statesExplored": binding.search_states_explored,
            "backtracks": binding.backtrack_count,
        },
        "repair": {
            "attempts": repair_attempts,
            "operationTypes": sorted(set(repair_operation_types)),
        },
        "conflict": None,
        "status": "validated",
    }


def failed_topology_audit(
    *,
    error: TopologyCompileError,
    nodes: Sequence[PlannedTask],
    relations: Sequence[TaskPlanRelation],
    control_policies: Sequence[VerificationLoopPolicy],
    catalog: CapabilityCatalog,
    producer_kind: str,
    catalog_source: str,
    capability_coverage_mode: str,
    repair_attempts: int = 0,
) -> dict[str, Any]:
    conflict = error.conflict
    catalog_hash = catalog_fingerprint(catalog)
    topology_payload = {
        "compilerVersion": TOPOLOGY_COMPILER_VERSION,
        "catalogFingerprint": catalog_hash,
        "tasks": sorted(node.key for node in nodes),
        "relations": sorted(
            (item.source_key, item.target_key, item.relation_type.value) for item in relations
        ),
        "controlPolicies": sorted(
            json.dumps(item.model_dump(by_alias=True, mode="json"), sort_keys=True)
            for item in control_policies
        ),
    }
    return {
        "compilerVersion": TOPOLOGY_COMPILER_VERSION,
        "producerKind": producer_kind,
        "catalogSource": catalog_source,
        "catalogFingerprint": catalog_hash,
        "capabilityCoverageMode": capability_coverage_mode,
        "taskCount": len(nodes),
        "semanticEdgeCount": len(relations),
        "topologyFingerprint": _fingerprint(topology_payload),
        "capabilityRequirements": [
            {
                "requirementId": item.requirement_id,
                "producerCapability": item.producer_capability,
                "consumerCapability": item.consumer_capability,
                "consumerTaskKey": item.consumer_task_key,
            }
            for item in conflict.capability_requirements
        ],
        "selectedBindings": [],
        "bindingSearch": {"statesExplored": conflict.search_states_explored, "backtracks": 0},
        "repair": {"attempts": repair_attempts, "operationTypes": []},
        "conflict": {
            "code": conflict.code.value,
            "phase": conflict.phase,
            "cycleNodes": list(conflict.cycle_nodes),
            "cycleEdges": [
                {
                    "sourceKey": edge.source_key, "targetKey": edge.target_key,
                    "origin": edge.origin.value, "mutationPolicy": edge.mutation_policy.value,
                }
                for edge in conflict.cycle_edges
            ],
            "requirementIds": [item.requirement_id for item in conflict.capability_requirements],
            "bindingRejections": [
                {
                    "requirementId": item.requirement_id,
                    "producerTaskKey": item.producer_task_key,
                    "reason": item.reason,
                    "path": list(item.path),
                }
                for item in conflict.binding_rejections
            ],
        },
        "status": "rejected",
    }


def _fingerprint(value: Mapping[str, Any] | Sequence[Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "TOPOLOGY_COMPILER_VERSION", "catalog_fingerprint",
    "failed_topology_audit", "successful_topology_audit",
]
