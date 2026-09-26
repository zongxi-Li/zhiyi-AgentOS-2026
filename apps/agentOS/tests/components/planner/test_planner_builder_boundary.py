"""Planner and ACG Builder ownership boundary regression tests."""

from __future__ import annotations

import pytest

from components.planner.acg_builder import ACGBuilder
from components.planner.semantic_planner import SemanticPlanner, SemanticPlanningError
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from support.acg.models import (
    AgentNode, CapabilityCatalog, EdgeType, PlanningCapabilityDescriptor,
    build_default_capability_catalog,
)


def _workflow(*, planning_nodes=()) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflowId="semantic-template",
        name="Semantic template",
        domain="general",
        runtimeEngine="acg",
        planningNodes=list(planning_nodes),
        steps=[WorkflowStepDefinition(
            stepId="execute",
            name="Execution detail",
            agentName="agent",
            capability="analysis",
        )],
    )


def test_template_planning_requires_an_explicit_semantic_declaration() -> None:
    planner = SemanticPlanner(build_default_capability_catalog())

    with pytest.raises(SemanticPlanningError, match="no Planner semantic declaration"):
        planner.plan_template(
            mission_id="mission_0123456789ab",
            workflow=_workflow(),
            strategy="static_template",
        )


def test_template_planner_does_not_derive_semantics_from_workflow_steps() -> None:
    planner = SemanticPlanner(CapabilityCatalog([
        PlanningCapabilityDescriptor(capabilityId="analysis", displayName="Analysis"),
    ]))
    workflow = _workflow(planning_nodes=[PlannedTask(
        key="semantic-outcome",
        title="Semantic outcome",
        objective="Satisfy the user-visible outcome",
        capabilityRequirements=("analysis",),
    )])

    task_plan = planner.plan_template(
        mission_id="mission_0123456789ab",
        workflow=workflow,
        strategy="static_template",
    )
    built = ACGBuilder().build_template(workflow=workflow, task_plan=task_plan)

    assert [node.key for node in task_plan.nodes] == ["semantic-outcome"]
    assert built.bindings[0].plan_node_key == "semantic-outcome"
    assert built.bindings[0].acg_node_id == "execute"


def _two_step_template(*, input_from: bool = False, next_step: bool = False) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflowId="two-step-template",
        name="Two step template",
        domain="general",
        runtimeEngine="acg",
        steps=[
            WorkflowStepDefinition(
                stepId="a", name="A", agentName="agent", capability="analysis",
                nextStepId="b" if next_step else None,
            ),
            WorkflowStepDefinition(
                stepId="b", name="B", agentName="agent", capability="analysis",
                input={"from": {"a": ["result"]}} if input_from else {},
            ),
        ],
    )


def _two_task_plan(*, dependency: bool = False) -> TaskPlan:
    return TaskPlan(
        missionId="mission_0123456789ab",
        nodes=(
            PlannedTask(key="step:a", title="A", objective="Do A", capabilityRequirements=("analysis",)),
            PlannedTask(key="step:b", title="B", objective="Do B", capabilityRequirements=("analysis",)),
        ),
        relations=(TaskPlanRelation(
            sourceKey="step:a", targetKey="step:b", relationType="depends_on",
        ),) if dependency else (),
    )


def test_template_order_does_not_create_undeclared_semantic_dependency() -> None:
    built = ACGBuilder().build_template(
        workflow=_two_step_template(), task_plan=_two_task_plan(),
    )

    assert built.blueprint.edges_of_type(EdgeType.DEPENDENCY) == []


def test_template_input_from_without_task_plan_dependency_fails_closed() -> None:
    with pytest.raises(ValueError, match="input.from requires a TaskPlan semantic dependency"):
        ACGBuilder().build_template(
            workflow=_two_step_template(input_from=True), task_plan=_two_task_plan(),
        )


def test_template_explicit_next_step_without_task_plan_dependency_fails_closed() -> None:
    with pytest.raises(ValueError, match="nextStepId requires a TaskPlan semantic dependency"):
        ACGBuilder().build_template(
            workflow=_two_step_template(next_step=True), task_plan=_two_task_plan(),
        )


def test_template_lowers_authorized_task_plan_dependency() -> None:
    built = ACGBuilder().build_template(
        workflow=_two_step_template(input_from=True),
        task_plan=_two_task_plan(dependency=True),
    )

    assert [(edge.source_id, edge.target_id) for edge in built.blueprint.edges_of_type(
        EdgeType.DEPENDENCY
    )] == [("a", "b")]

    agent_bindings = [
        edge for edge in built.blueprint.edges_of_type(EdgeType.EXECUTION)
        if isinstance(built.blueprint.get_node(edge.source_id), AgentNode)
    ]
    assert {(edge.source_id, edge.target_id) for edge in agent_bindings} == {
        ("agent::agent", "a"), ("agent::agent", "b"),
    }
    assert all(
        not ({"agentName", "assignedAgentId", "skillIds", "memoryIds", "evidenceIds"}
             & node.model_dump(by_alias=True).keys())
        for node in built.blueprint.step_nodes()
    )
