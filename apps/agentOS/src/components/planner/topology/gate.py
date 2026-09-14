from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation, VerificationLoopPolicy
from support.acg.models import CapabilityCatalog

from .compiler import TaskPlanTopologyCompiler
from .audit import failed_topology_audit, successful_topology_audit
from .errors import TopologyCompileError
from .model import EdgeOrigin


def validate_task_plan_for_execution(
    *,
    capability_catalog: CapabilityCatalog,
    mission_id: str,
    nodes: Sequence[PlannedTask],
    relations: Sequence[TaskPlanRelation] = (),
    control_policies: Sequence[VerificationLoopPolicy] = (),
    expected_artifacts: Sequence[str] = (),
    relation_origin: EdgeOrigin,
    plan_version: int = 1,
    metadata: Mapping[str, Any] | None = None,
    producer_kind: str | None = None,
    catalog_source: str = "injected",
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
) -> TaskPlan:
    """The shared semantic gate for every already-materialized plan producer."""
    kind = producer_kind or relation_origin.value
    try:
        result = TaskPlanTopologyCompiler(capability_catalog).validate_existing_plan(
            nodes=list(nodes), raw_relations=list(relations),
            control_policies=tuple(control_policies), relation_origin=relation_origin,
        )
    except TopologyCompileError as exc:
        audit = failed_topology_audit(
            error=exc, nodes=nodes, relations=relations, control_policies=control_policies,
            catalog=capability_catalog, producer_kind=kind, catalog_source=catalog_source,
            capability_coverage_mode="declared_producers_only",
        )
        exc.audit = audit
        if audit_sink is not None:
            audit_sink(audit)
        raise
    audit = successful_topology_audit(
        result=result, nodes=nodes, catalog=capability_catalog, producer_kind=kind,
        catalog_source=catalog_source, capability_coverage_mode="declared_producers_only",
    )
    if audit_sink is not None:
        audit_sink(audit)
    return TaskPlan(
        missionId=mission_id,
        planVersion=plan_version,
        nodes=tuple(nodes),
        relations=result.task_plan_relations,
        controlPolicies=result.control_policies,
        expectedArtifacts=tuple(expected_artifacts),
        metadata=dict(metadata or {}),
    )


__all__ = ["validate_task_plan_for_execution"]
