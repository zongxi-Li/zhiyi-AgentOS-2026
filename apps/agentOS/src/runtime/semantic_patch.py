"""TaskPlan-first semantic revision and derived graph-diff support."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from components.planner.acg_lowerer import ACGLowerer, ACGLoweringInput, ACGLoweringStep
from components.planner.service import apply_task_plan_patch
from contracts.planning import TaskImplementationBinding, TaskPlan
from contracts.recovery import GraphPatch, SemanticPatchRequest
from support.acg.capabilities import CapabilityCatalog
from support.acg.native_capabilities import build_default_capability_catalog
from support.acg.planning import ACGResourcePlan
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
        retained_keys = {task.key for task in next_plan.nodes} - changed_keys
        kept_steps, kept_bindings = _retained_lowering_steps(
            blueprint, base_bindings, retained_keys
        )
        new_steps, new_bindings = _new_lowering_steps(
            request=request, next_plan=next_plan, catalog=catalog
        )
        bindings = (*kept_bindings, *new_bindings)
        active_step_ids = {binding.acg_node_id for binding in bindings}
        resource_plan = _revised_resource_plan(
            blueprint.resource_plan,
            request.resource_plan_patch,
            active_step_ids,
            {binding.acg_node_id for binding in new_bindings},
        )
        lowering_input = ACGLoweringInput(
            mission_id=next_plan.mission_id,
            objective=blueprint.objective,
            complexity_level=blueprint.complexity_level,
            task_plan=next_plan,
            steps=(*kept_steps, *new_steps),
            implementation_bindings=bindings,
            resource_plan=resource_plan,
            metadata=deepcopy(blueprint.metadata),
        )
        revised = ACGLowerer().lower(lowering_input)
        revised.graph_id = blueprint.graph_id
        revised.version = blueprint.version + 1
        return SemanticPatchResult(
            blueprint=revised,
            next_plan=next_plan,
            next_bindings=bindings,
            topology_audits=tuple(topology_audits),
        )


def _retained_lowering_steps(
    blueprint: ACGBlueprint,
    base_bindings: tuple[TaskImplementationBinding, ...],
    retained_keys: set[str],
) -> tuple[tuple[ACGLoweringStep, ...], tuple[TaskImplementationBinding, ...]]:
    """Reuse frozen implementation decisions only for unchanged semantic tasks."""

    binding_by_node_id = {item.acg_node_id: item for item in base_bindings}
    steps: list[ACGLoweringStep] = []
    bindings: list[TaskImplementationBinding] = []
    for node in blueprint.step_nodes():
        binding = binding_by_node_id.get(node.node_id)
        if binding is None or binding.plan_node_key not in retained_keys:
            continue
        steps.append(ACGLoweringStep(
            task_key=binding.plan_node_key,
            node_id=node.node_id,
            name=node.name,
            goal=node.goal,
            acceptance_criteria=tuple(node.acceptance_criteria),
            source_refs=tuple(node.source_refs),
            logical_role=node.logical_role,
            capability=node.capability,
            input_spec=deepcopy(node.input_spec),
            output_spec=deepcopy(node.output_spec),
            step_type=node.step_type,
            timeout=node.timeout,
            retry_limit=node.retry_limit,
            priority=node.priority,
            status=node.status,
            review_required=node.review_required,
            metadata=deepcopy(node.metadata),
        ))
        bindings.append(binding)
    retained = {item.plan_node_key for item in bindings}
    if retained != retained_keys:
        raise ValueError(
            "semantic patch cannot reuse missing implementation decisions: "
            f"{sorted(retained_keys - retained)}"
        )
    return tuple(steps), tuple(bindings)


def _new_lowering_steps(
    *,
    request: SemanticPatchRequest,
    next_plan: TaskPlan,
    catalog: CapabilityCatalog,
) -> tuple[tuple[ACGLoweringStep, ...], tuple[TaskImplementationBinding, ...]]:
    changed = {
        *request.task_plan_patch.replace_keys,
        *(task.key for task in request.task_plan_patch.add_nodes),
    }
    if not changed:
        if request.task_binding_patch is not None or request.resource_plan_patch is not None:
            raise ValueError("implementation planning data requires changed TaskPlan tasks")
        return (), ()
    if request.task_binding_patch is None:
        raise ValueError("changed TaskPlan tasks require TaskBindingPatch")
    bindings = tuple(request.task_binding_patch.bindings)
    if {item.plan_node_key for item in bindings} != changed:
        raise ValueError("TaskBindingPatch must cover exactly the added or replaced tasks")
    binding_by_key = {item.plan_node_key: item for item in bindings}
    task_by_key = {task.key: task for task in next_plan.nodes}
    steps: list[ACGLoweringStep] = []
    for key in sorted(changed):
        task = task_by_key[key]
        descriptor = (
            catalog.resolve(task.capability_requirements[0])
            if task.capability_requirements else None
        )
        steps.append(ACGLoweringStep(
            task_key=key,
            node_id=binding_by_key[key].acg_node_id,
            name=task.title,
            goal=task.objective,
            acceptance_criteria=tuple(task.acceptance_criteria),
            source_refs=tuple(task.source_refs),
            logical_role=task.logical_role,
            capability=descriptor.capability_id if descriptor else None,
            input_spec=deepcopy(descriptor.input_contract) if descriptor else {},
            output_spec=deepcopy(descriptor.output_contract) if descriptor else {},
            review_required=bool(descriptor and descriptor.requires_review),
            metadata={
                "taskPlanKey": key,
                **({
                    "capabilityId": descriptor.capability_id,
                    "planningStage": descriptor.planning_stage,
                } if descriptor else {}),
            },
        ))
    return tuple(steps), bindings


def _revised_resource_plan(
    current: ACGResourcePlan,
    delta: ACGResourcePlan | None,
    active_step_ids: set[str],
    new_step_ids: set[str],
) -> ACGResourcePlan:
    additions = delta or ACGResourcePlan()
    new_binding_ids = {item.step_id for item in additions.bindings}
    if new_step_ids and new_binding_ids != new_step_ids:
        raise ValueError("resourcePlanPatch bindings must cover every added or replaced task")
    if new_binding_ids - active_step_ids:
        raise ValueError("resourcePlanPatch references unknown executable steps")
    retained_ids = active_step_ids - new_step_ids
    evidence = tuple(
        item.model_copy(update={
            "consumer_step_ids": tuple(
                step_id for step_id in item.consumer_step_ids if step_id in active_step_ids
            )
        })
        for item in current.evidence
        if item.producer_step_id is None or item.producer_step_id in retained_ids
    )
    return ACGResourcePlan(
        bindings=(
            *(item for item in current.bindings if item.step_id in retained_ids),
            *additions.bindings,
        ),
        skills=(
            *(item for item in current.skills if item.step_id in retained_ids),
            *additions.skills,
        ),
        memory=(
            *(item for item in current.memory if item.step_id in retained_ids),
            *additions.memory,
        ),
        evidence=(*evidence, *additions.evidence),
        communication=(
            *(item for item in current.communication
              if item.producer_step_id in retained_ids and item.consumer_step_id in retained_ids),
            *additions.communication,
        ),
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
            new_nodes[node_id].model_dump(by_alias=True, mode="json")
            for node_id in sorted(new_nodes.keys() - old_nodes.keys())
        ),
        removedNodeIds=tuple(sorted(old_nodes.keys() - new_nodes.keys())),
        addedEdges=tuple(edge_payload(edge) for edge in sorted(new_edges - old_edges)),
        removedEdges=tuple(edge_payload(edge) for edge in sorted(old_edges - new_edges)),
        reason=reason,
    )


__all__ = ["SemanticGraphPatchService", "SemanticPatchResult", "derive_graph_patch"]
