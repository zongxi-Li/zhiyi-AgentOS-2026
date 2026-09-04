"""Planner and ACG Builder ownership boundary regression tests."""

from __future__ import annotations

import pytest

from components.planner.acg_builder import ACGBuilder
from components.planner.semantic_planner import SemanticPlanner, SemanticPlanningError
from contracts.planning import PlannedTask
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from support.acg.models import build_default_capability_catalog


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
    planner = SemanticPlanner(build_default_capability_catalog())
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
