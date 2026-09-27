"""Planner-owned implementation decisions for a semantic TaskPlan revision."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from contracts.planning import (
    SemanticTaskRelationType,
    TaskImplementationBinding,
    TaskPlan,
)
from support.acg.capabilities import CapabilityCatalog
from support.acg.planning import (
    ACGResourcePlan,
    AgentBindingSpec,
    CommunicationSpec,
    EvidenceSpec,
    MemoryAccessSpec,
)
from support.acg.schema import ACGBlueprint

from .acg_lowerer import ACGLoweringInput, ACGLoweringStep
from .cognitive_router import CognitiveRouter
from .lowering_input import lowering_step_from_task, output_fields


def build_semantic_patch_lowering_input(
    *,
    blueprint: ACGBlueprint,
    current_plan: TaskPlan,
    next_plan: TaskPlan,
    base_bindings: tuple[TaskImplementationBinding, ...],
    changed_keys: set[str],
    capability_catalog: CapabilityCatalog,
    agent_registry,
    domain: str,
) -> ACGLoweringInput:
    """Freeze server-owned implementation decisions for a revised TaskPlan.

    Unchanged tasks retain their already-frozen implementation decisions.
    Added or replaced tasks are routed by the planning layer from their declared
    capability. The semantic patch request never supplies executable node or
    logical-agent assignments.
    """

    current_keys = {task.key for task in current_plan.nodes}
    next_tasks = {task.key: task for task in next_plan.nodes}
    retained_keys = set(next_tasks) - changed_keys
    old_steps_by_key, old_bindings_by_key = _frozen_steps_by_key(
        blueprint, base_bindings
    )
    missing = retained_keys - set(old_steps_by_key)
    if missing:
        raise ValueError(
            "semantic patch cannot reuse missing implementation decisions: "
            f"{sorted(missing)}"
        )

    bindings_by_key = {
        key: old_bindings_by_key[key]
        for key in retained_keys
    }
    steps_by_key = {
        key: old_steps_by_key[key]
        for key in retained_keys
    }
    used_node_ids = {binding.acg_node_id for binding in bindings_by_key.values()}
    historical_node_ids = {
        binding.acg_node_id for binding in old_bindings_by_key.values()
    }
    routed = {}
    descriptors = {}
    router = CognitiveRouter(agent_registry, capability_catalog)

    for key in sorted(changed_keys):
        task = next_tasks[key]
        if len(task.capability_requirements) != 1:
            raise ValueError(
                "added or replaced TaskPlan tasks must select exactly one capability: "
                f"{key}"
            )
        descriptor = capability_catalog.resolve(task.capability_requirements[0])
        candidates = router.candidates_for(descriptor, domain=domain)
        if not candidates:
            raise ValueError(
                "semantic patch planning found no logical Agent for capability: "
                f"{descriptor.capability_id}"
            )
        selected = candidates[0]
        previous = old_bindings_by_key.get(key) if key in current_keys else None
        node_id = (
            previous.acg_node_id
            if previous is not None
            else _next_step_id(key, used_node_ids | historical_node_ids)
        )
        if node_id in used_node_ids:
            raise ValueError(f"semantic patch produced duplicate executable node id: {node_id}")
        used_node_ids.add(node_id)
        bindings_by_key[key] = TaskImplementationBinding(
            planNodeKey=key,
            acgNodeId=node_id,
        )
        routed[key] = selected
        descriptors[key] = descriptor

    node_id_by_task = {
        key: binding.acg_node_id for key, binding in bindings_by_key.items()
    }
    dependencies = {key: [] for key in next_tasks}
    for relation in next_plan.relations:
        if relation.relation_type is SemanticTaskRelationType.DEPENDS_ON:
            dependencies[relation.target_key].append(relation.source_key)

    output_contracts = {
        key: deepcopy(step.output_spec) for key, step in steps_by_key.items()
    }
    for key, descriptor in descriptors.items():
        output_contracts[key] = deepcopy(descriptor.output_contract)

    for key in sorted(changed_keys):
        descriptor = descriptors[key]
        steps_by_key[key] = lowering_step_from_task(
            task=next_tasks[key],
            descriptor=descriptor,
            node_id=node_id_by_task[key],
            dependencies=dependencies[key],
            node_id_by_task=node_id_by_task,
            descriptors=descriptors,
            expected_artifacts=next_plan.expected_artifacts,
            router_score=routed[key].score,
            dependency_output_contracts=output_contracts,
        )

    resource_plan = _rebuild_resource_plan(
        current=blueprint.resource_plan,
        retained_step_ids={node_id_by_task[key] for key in retained_keys},
        changed_keys=changed_keys,
        node_id_by_task=node_id_by_task,
        dependencies=dependencies,
        descriptors=descriptors,
        routed=routed,
        output_contracts=output_contracts,
    )
    ordered_keys = [task.key for task in next_plan.nodes]
    return ACGLoweringInput(
        mission_id=next_plan.mission_id,
        objective=blueprint.objective,
        complexity_level=blueprint.complexity_level,
        task_plan=next_plan,
        steps=tuple(steps_by_key[key] for key in ordered_keys),
        implementation_bindings=tuple(bindings_by_key[key] for key in ordered_keys),
        resource_plan=resource_plan,
        metadata=deepcopy(blueprint.metadata),
    )


def _frozen_steps_by_key(
    blueprint: ACGBlueprint,
    bindings: tuple[TaskImplementationBinding, ...],
) -> tuple[dict[str, ACGLoweringStep], dict[str, TaskImplementationBinding]]:
    binding_by_node_id = {binding.acg_node_id: binding for binding in bindings}
    steps: dict[str, ACGLoweringStep] = {}
    bindings_by_key: dict[str, TaskImplementationBinding] = {}
    for node in blueprint.step_nodes():
        binding = binding_by_node_id.get(node.node_id)
        if binding is None:
            continue
        steps[binding.plan_node_key] = ACGLoweringStep(
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
        )
        bindings_by_key[binding.plan_node_key] = binding
    return steps, bindings_by_key


def _rebuild_resource_plan(
    *,
    current: ACGResourcePlan,
    retained_step_ids: set[str],
    changed_keys: set[str],
    node_id_by_task: dict[str, str],
    dependencies: dict[str, list[str]],
    descriptors: dict[str, Any],
    routed: dict[str, Any],
    output_contracts: dict[str, dict],
) -> ACGResourcePlan:
    bindings = [
        item for item in current.bindings if item.step_id in retained_step_ids
    ]
    bindings.extend(
        AgentBindingSpec(
            stepId=node_id_by_task[key],
            plannedAgentId=routed[key].logical_agent_id,
            role=descriptors[key].display_name,
            requiredCapabilities=(descriptors[key].capability_id,),
            ephemeral=routed[key].ephemeral,
        )
        for key in sorted(changed_keys)
    )
    skills = tuple(
        item for item in current.skills if item.step_id in retained_step_ids
    )
    memory_writes = [
        item
        for item in current.memory
        if item.step_id in retained_step_ids and item.access == "write"
    ]
    evidence = [
        item.model_copy(update={"consumer_step_ids": ()})
        for item in current.evidence
        if item.producer_step_id is None or item.producer_step_id in retained_step_ids
    ]
    for key in sorted(changed_keys):
        descriptor = descriptors[key]
        step_id = node_id_by_task[key]
        if descriptor.writes_memory:
            memory_writes.append(MemoryAccessSpec(
                stepId=step_id,
                memoryId=f"memory::{step_id}",
                access="write",
                memoryType="episodic",
                storageType="inline",
                retentionPolicy="task",
                schema={"capabilityId": descriptor.capability_id},
            ))
        if descriptor.requires_evidence:
            evidence.append(EvidenceSpec(
                evidenceId=f"evidence::{step_id}",
                evidenceType="retrieved",
                producerStepId=step_id,
                source="planner",
                schema={"capabilityId": descriptor.capability_id},
            ))

    evidence_by_producer = {
        item.producer_step_id: item.evidence_id
        for item in evidence
        if item.producer_step_id is not None
    }
    evidence_consumers = {item.evidence_id: [] for item in evidence}
    memory_by_producer = {
        item.step_id: item.memory_id for item in memory_writes
    }
    memory = list(memory_writes)
    communication: list[CommunicationSpec] = []
    for target_key, source_keys in dependencies.items():
        target_id = node_id_by_task[target_key]
        for source_key in source_keys:
            source_id = node_id_by_task[source_key]
            communication.append(CommunicationSpec(
                producerStepId=source_id,
                consumerStepId=target_id,
                allowedFields=tuple(output_fields(output_contracts[source_key])),
                channel=f"{source_id}:{target_id}",
                mode="STRICT_CONTRACT",
            ))
            evidence_id = evidence_by_producer.get(source_id)
            if evidence_id is not None:
                evidence_consumers[evidence_id].append(target_id)
            memory_id = memory_by_producer.get(source_id)
            if memory_id is not None:
                memory.append(MemoryAccessSpec(
                    stepId=target_id,
                    memoryId=memory_id,
                    access="read",
                ))

    return ACGResourcePlan(
        bindings=tuple(bindings),
        skills=skills,
        memory=tuple(memory),
        evidence=tuple(
            item.model_copy(update={
                "consumer_step_ids": tuple(evidence_consumers[item.evidence_id])
            })
            for item in evidence
        ),
        communication=tuple(communication),
    )


def _next_step_id(task_key: str, used_ids: set[str]) -> str:
    raw = task_key.rsplit(":", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_.-") or "step"
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


__all__ = ["build_semantic_patch_lowering_input"]
