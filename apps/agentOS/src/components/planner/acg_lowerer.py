"""Deterministic lowering from frozen planning decisions to an ACG blueprint."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from contracts.planning import (
    SemanticTaskRelationType,
    TaskImplementationBinding,
    TaskPlan,
)
from support.acg.planning import ACGResourcePlan
from support.acg.schema import (
    ACGBlueprint,
    ACGEdge,
    BlueprintStatus,
    ComplexityLevel,
    ConditionOperator,
    ConditionSpec,
    ControlNode,
    ControlType,
    EdgeType,
    LoopSpec,
    StepNode,
)
from support.acg.validation import validate_blueprint
from .acg_semantic_validator import (
    validate_acg_semantic_preservation,
    validate_bound_acg_semantics,
)


@dataclass(frozen=True)
class ACGLoweringStep:
    """A frozen Step decision prepared by the planning layer."""

    task_key: str
    node_id: str
    name: str
    goal: str
    acceptance_criteria: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    logical_role: str = "task"
    capability: str | None = None
    input_spec: Mapping[str, Any] = field(default_factory=dict)
    output_spec: Mapping[str, Any] = field(default_factory=dict)
    step_type: str = "agent"
    timeout: int = 0
    retry_limit: int = 0
    priority: int = 0
    status: BlueprintStatus = BlueprintStatus.DRAFT
    review_required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ACGLoweringInput:
    """Frozen, already-decided input consumed by :class:`ACGLowerer`.

    This contract deliberately contains no catalog, router, planner, provider, or
    runtime-resource lookup. The planning layer resolves those decisions before
    constructing this object.
    """

    mission_id: str
    objective: str
    complexity_level: ComplexityLevel
    task_plan: TaskPlan
    steps: tuple[ACGLoweringStep, ...]
    implementation_bindings: tuple[TaskImplementationBinding, ...]
    resource_plan: ACGResourcePlan = field(default_factory=ACGResourcePlan)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    control_nodes: tuple[ControlNode, ...] = ()
    control_edges: tuple[ACGEdge, ...] = ()


class ACGLowerer:
    """Translate frozen planning decisions into the canonical ACG blueprint."""

    def lower(self, lowering_input: ACGLoweringInput) -> ACGBlueprint:
        task_plan = lowering_input.task_plan
        if lowering_input.mission_id != task_plan.mission_id:
            raise ValueError("ACGLoweringInput missionId does not match TaskPlan")

        self._validate_steps(lowering_input)
        bindings_by_key = {
            binding.plan_node_key: binding
            for binding in lowering_input.implementation_bindings
        }
        node_ids = {binding.acg_node_id for binding in bindings_by_key.values()}

        blueprint = ACGBlueprint(
            missionId=lowering_input.mission_id,
            objective=lowering_input.objective,
            complexityLevel=lowering_input.complexity_level,
            metadata=deepcopy(dict(lowering_input.metadata)),
        )
        blueprint.resource_plan = lowering_input.resource_plan.model_copy(deep=True)

        for step in lowering_input.steps:
            blueprint.nodes.append(self._step_node(step))
        for control in lowering_input.control_nodes:
            if control.node_id in node_ids or blueprint.has_node(control.node_id):
                raise ValueError(f"duplicate ACG control node id: {control.node_id}")
            blueprint.nodes.append(control.model_copy(deep=True))
        for edge in lowering_input.control_edges:
            if edge.edge_type is not EdgeType.DEPENDENCY:
                raise ValueError("ACGLoweringInput control edges must be DEPENDENCY edges")
            blueprint.edges.append(edge.model_copy(deep=True))

        for relation in task_plan.relations:
            if relation.relation_type is not SemanticTaskRelationType.DEPENDS_ON:
                continue
            source = bindings_by_key.get(relation.source_key)
            target = bindings_by_key.get(relation.target_key)
            if source is None or target is None:
                raise ValueError(
                    "TaskPlan dependency references a missing lowering binding: "
                    f"{relation.source_key} -> {relation.target_key}"
                )
            self._add_dependency(blueprint, source.acg_node_id, target.acg_node_id)

        self._lower_control_policies(blueprint, task_plan, bindings_by_key)
        blueprint.touch()
        validate_blueprint(blueprint)
        validate_acg_semantic_preservation(task_plan, blueprint)
        validate_bound_acg_semantics(
            task_plan,
            blueprint,
            lowering_input.implementation_bindings,
            require_exact=True,
        )
        return blueprint

    @staticmethod
    def _validate_steps(lowering_input: ACGLoweringInput) -> None:
        expected = {node.key for node in lowering_input.task_plan.nodes}
        steps_by_key: dict[str, ACGLoweringStep] = {}
        for step in lowering_input.steps:
            if step.task_key in steps_by_key:
                raise ValueError(f"duplicate lowering step task key: {step.task_key}")
            steps_by_key[step.task_key] = step
        if set(steps_by_key) != expected:
            missing = sorted(expected - set(steps_by_key))
            extra = sorted(set(steps_by_key) - expected)
            raise ValueError(
                f"lowering steps do not cover TaskPlan: missing={missing}, extra={extra}"
            )

        binding_keys = [item.plan_node_key for item in lowering_input.implementation_bindings]
        if len(binding_keys) != len(set(binding_keys)) or set(binding_keys) != expected:
            raise ValueError("implementation bindings must cover each TaskPlan node exactly once")
        if any(not item.acg_node_id.strip() for item in lowering_input.implementation_bindings):
            raise ValueError("implementation binding acgNodeId is required")
        if len({item.acg_node_id for item in lowering_input.implementation_bindings}) != len(binding_keys):
            raise ValueError("implementation bindings must use unique ACG node ids")
        for key, binding in {
            item.plan_node_key: item for item in lowering_input.implementation_bindings
        }.items():
            if steps_by_key[key].node_id != binding.acg_node_id:
                raise ValueError(
                    f"lowering step node id does not match implementation binding: {key}"
                )

    @staticmethod
    def _step_node(step: ACGLoweringStep) -> StepNode:
        return StepNode(
            nodeId=step.node_id,
            name=step.name,
            goal=step.goal,
            acceptanceCriteria=list(step.acceptance_criteria),
            sourceRefs=list(step.source_refs),
            logicalRole=step.logical_role,
            capability=step.capability,
            inputSpec=deepcopy(dict(step.input_spec)),
            outputSpec=deepcopy(dict(step.output_spec)),
            stepType=step.step_type,
            timeout=step.timeout,
            retryLimit=step.retry_limit,
            priority=step.priority,
            status=step.status,
            reviewRequired=step.review_required,
            metadata=deepcopy(dict(step.metadata)),
        )

    def _lower_control_policies(
        self,
        blueprint: ACGBlueprint,
        task_plan: TaskPlan,
        bindings_by_key: Mapping[str, TaskImplementationBinding],
    ) -> None:
        for index, policy in enumerate(task_plan.control_policies, start=1):
            try:
                entry = bindings_by_key[policy.body_entry_key].acg_node_id
                exit_id = bindings_by_key[policy.body_exit_key].acg_node_id
                source = bindings_by_key[policy.condition_source_key].acg_node_id
            except KeyError as exc:
                raise ValueError(
                    f"control policy references a missing lowering binding: {exc.args[0]}"
                ) from exc
            control_id = f"ctrl_verification_loop_{index}"
            if blueprint.has_node(control_id):
                raise ValueError(f"duplicate generated control node id: {control_id}")
            edge = ACGEdge(
                sourceId=control_id,
                targetId=entry,
                edgeType=EdgeType.DEPENDENCY,
            )
            cases = {value: edge.edge_id for value in policy.repeat_values}
            blueprint.nodes.append(
                ControlNode(
                    nodeId=control_id,
                    name="VERIFICATION_LOOP",
                    controlType=ControlType.LOOP,
                    loopSpec=LoopSpec(
                        bodyEntryId=entry,
                        bodyExitId=exit_id,
                        condition=ConditionSpec(
                            sourceNodeId=source,
                            jsonPointer=policy.status_pointer,
                            operator=ConditionOperator.IN,
                            cases=cases,
                        ),
                        maxIterations=policy.max_revisions + 1,
                        onLimit=(
                            "review"
                            if policy.on_exhausted == "human_review"
                            else "fail"
                        ),
                    ),
                    metadata={
                        "taskPlanPolicy": "verification_loop",
                        "maxRevisions": policy.max_revisions,
                    },
                )
            )
            blueprint.edges.append(edge)

    @staticmethod
    def _add_dependency(
        blueprint: ACGBlueprint,
        source_id: str,
        target_id: str,
    ) -> None:
        if source_id == target_id:
            raise ValueError(f"self dependency is not allowed: {source_id}")
        if any(
            edge.source_id == source_id and edge.target_id == target_id
            for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY)
        ):
            return
        blueprint.edges.append(
            ACGEdge(
                sourceId=source_id,
                targetId=target_id,
                edgeType=EdgeType.DEPENDENCY,
            )
        )


__all__ = ["ACGLoweringInput", "ACGLoweringStep", "ACGLowerer"]
