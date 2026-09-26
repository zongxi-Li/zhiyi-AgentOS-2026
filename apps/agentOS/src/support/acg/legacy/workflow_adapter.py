"""Translate legacy WorkflowDefinition input into the canonical ACG boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..planning import AgentBindingSpec, CommunicationSpec, EvidenceSpec, MemoryAccessSpec
from ..schema import ACGBlueprint, ACGEdge, ComplexityLevel, EdgeType, StepNode

if TYPE_CHECKING:
    from typing import Any as WorkflowDefinition


def _complexity_from_step_count(count: int) -> ComplexityLevel:
    if count <= 3:
        return ComplexityLevel.SIMPLE
    if count <= 7:
        return ComplexityLevel.MEDIUM
    if count <= 15:
        return ComplexityLevel.COMPLEX
    return ComplexityLevel.EXTREME


_MEMORY_KEYWORDS = (
    "risk", "\u98ce\u9669", "suggest", "revision", "\u5efa\u8bae", "report",
    "\u62a5\u544a", "analysis", "\u5206\u6790", "summary", "\u7ed3\u8bba",
)
_EVIDENCE_KEYWORDS = (
    "evidence", "\u8bc1\u636e", "\u4f9d\u636e", "statute", "\u6cd5\u6761", "citation",
)


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(keyword in low for keyword in keywords)


def promote_workflow_to_acg(
    workflow: "WorkflowDefinition",
    *,
    mission_id: str | None = None,
    enrich: bool = True,
    infer_dependencies: bool = True,
) -> ACGBlueprint:
    """Translate a legacy workflow into a pure-kernel blueprint plus typed plans.

    ``infer_dependencies`` is retained only for the workflow-only legacy ingress.
    Canonical TaskPlan callers disable it so semantic ordering remains Planner-owned.
    """
    steps = list(workflow.steps)
    blueprint = ACGBlueprint(
        missionId=mission_id,
        objective=workflow.description or workflow.name,
        complexityLevel=_complexity_from_step_count(len(steps)),
        metadata={
            "sourceWorkflowId": workflow.workflow_id,
            "sourceWorkflowVersion": workflow.version,
            "promotedFromLinear": True,
            "enriched": enrich,
            "runtimeEngine": workflow.effective_runtime_engine,
        },
    )

    for definition in steps:
        blueprint.nodes.append(StepNode(
            nodeId=definition.step_id,
            name=definition.name,
            stepType="agent",
            goal=definition.name,
            capability=definition.capability,
            inputSpec=dict(definition.input),
            outputSpec=dict(definition.output_spec),
            reviewRequired=definition.review_required,
            retryLimit=definition.max_retries,
            timeout=definition.timeout,
            priority=definition.priority,
        ))

    step_ids = {definition.step_id for definition in steps}
    if infer_dependencies:
        for index, definition in enumerate(steps):
            target_id = definition.next_step_id
            if target_id in ("", "done", "completed", None):
                target_id = None
            if target_id is None and index + 1 < len(steps):
                target_id = steps[index + 1].step_id
            if target_id and target_id in step_ids:
                blueprint.edges.append(ACGEdge(
                    sourceId=definition.step_id,
                    targetId=target_id,
                    edgeType=EdgeType.DEPENDENCY,
                ))

    # input.from is a communication contract. It becomes a dependency only on
    # the workflow-only legacy path where dependency inference is explicitly enabled.
    for definition in steps:
        from_map = definition.input.get("from") if isinstance(definition.input, dict) else None
        if not isinstance(from_map, dict):
            continue
        for source_id, fields in from_map.items():
            if source_id not in step_ids or source_id == definition.step_id:
                continue
            data_fields = [str(field) for field in fields] if isinstance(fields, list) else []
            blueprint.resource_plan.communication += (CommunicationSpec(
                producerStepId=source_id,
                consumerStepId=definition.step_id,
                allowedFields=tuple(data_fields),
                channel=f"{source_id}:{definition.step_id}",
            ),)
            if infer_dependencies and not any(
                edge.edge_type == EdgeType.DEPENDENCY
                and edge.source_id == source_id
                and edge.target_id == definition.step_id
                for edge in blueprint.edges
            ):
                blueprint.edges.append(ACGEdge(
                    sourceId=source_id,
                    targetId=definition.step_id,
                    edgeType=EdgeType.DEPENDENCY,
                    metadata={"derivedFrom": "input.from"},
                ))

    _inject_agent_bindings(blueprint, steps)
    if enrich:
        _inject_context_specs(blueprint, steps)

    blueprint.touch()
    return blueprint


def _inject_agent_bindings(blueprint: ACGBlueprint, steps) -> None:
    """Lower legacy assignments to planner-owned logical binding specs."""
    for definition in steps:
        agent_name = definition.agent_name or definition.step_id
        capability = definition.capability or ""
        blueprint.resource_plan.bindings += (AgentBindingSpec(
            stepId=definition.step_id,
            plannedAgentId=agent_name,
            role=capability or agent_name,
            requiredCapabilities=((capability,) if capability else ()),
        ),)


def _inject_context_specs(blueprint: ACGBlueprint, steps) -> None:
    """Lower optional legacy memory and evidence hints into typed specs."""
    memory_ids: dict[str, str] = {}
    evidence_ids: dict[str, str] = {}

    for definition in steps:
        step_id = definition.step_id
        signature = f"{definition.capability or ''} {step_id}"
        output_properties = (
            definition.output_spec.get("properties", {})
            if isinstance(definition.output_spec, dict)
            else {}
        )
        declares_evidence_output = any(
            field in output_properties for field in ("evidence_refs", "evidenceRefs")
        )
        if declares_evidence_output or _matches(signature, _EVIDENCE_KEYWORDS):
            evidence_id = f"evidence::{step_id}"
            blueprint.resource_plan.evidence += (EvidenceSpec(
                evidenceId=evidence_id,
                evidenceType="retrieved",
                producerStepId=step_id,
                source="workflow",
            ),)
            evidence_ids[step_id] = evidence_id

        memory_policy = (
            definition.input.get("memoryPolicy", {})
            if isinstance(definition.input, dict)
            else {}
        )
        declares_memory_write = (
            isinstance(memory_policy, dict) and memory_policy.get("write") is True
        )
        if declares_memory_write or _matches(signature, _MEMORY_KEYWORDS):
            memory_type = (
                str(memory_policy.get("writeType") or "episodic")
                if declares_memory_write
                else "episodic"
            )
            memory_id = f"memory::{step_id}"
            blueprint.resource_plan.memory += (MemoryAccessSpec(
                stepId=step_id,
                memoryId=memory_id,
                access="write",
                memoryType=memory_type,
            ),)
            memory_ids[step_id] = memory_id

    for definition in steps:
        from_map = definition.input.get("from") if isinstance(definition.input, dict) else None
        if not isinstance(from_map, dict):
            continue
        for source_id in from_map:
            if source_id in memory_ids:
                blueprint.resource_plan.memory += (MemoryAccessSpec(
                    stepId=definition.step_id,
                    memoryId=memory_ids[source_id],
                    access="read",
                ),)
            if source_id in evidence_ids:
                for index, spec in enumerate(blueprint.resource_plan.evidence):
                    if spec.evidence_id == evidence_ids[source_id]:
                        blueprint.resource_plan.evidence = (
                            *blueprint.resource_plan.evidence[:index],
                            spec.model_copy(update={
                                "consumer_step_ids": tuple(dict.fromkeys(
                                    (*spec.consumer_step_ids, definition.step_id)
                                ))
                            }),
                            *blueprint.resource_plan.evidence[index + 1:],
                        )
                        break


__all__ = ["promote_workflow_to_acg"]
