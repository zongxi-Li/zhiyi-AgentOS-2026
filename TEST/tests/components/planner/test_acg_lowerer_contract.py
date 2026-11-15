from __future__ import annotations

import ast
import inspect
from dataclasses import replace

import pytest

import components.planner.acg_lowerer as lowerer_module
from components.planner.acg_lowerer import (
    ACGLoweringInput,
    ACGLoweringStep,
    ACGLowerer,
)
from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan, TaskPlanRelation
from support.acg.planning import ACGResourcePlan, AgentBindingSpec
from support.acg.schema import ComplexityLevel, EdgeType


def _input(*relations: tuple[str, str]) -> ACGLoweringInput:
    keys = tuple(dict.fromkeys(item for pair in relations for item in pair)) or ("A", "B")
    plan = TaskPlan(
        missionId="mission_0123456789ab",
        nodes=tuple(
            PlannedTask(
                key=key,
                title=key,
                objective=f"Execute {key}",
                capabilityRequirements=(f"cap-{key.lower()}",),
            )
            for key in keys
        ),
        relations=tuple(
            TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")
            for source, target in relations
        ),
    )
    steps = tuple(
        ACGLoweringStep(
            task_key=key,
            node_id=f"step-{key.lower()}",
            name=key,
            goal=f"Execute {key}",
            capability=f"cap-{key.lower()}",
            metadata={"taskPlanKey": key},
        )
        for key in keys
    )
    bindings = tuple(
        TaskImplementationBinding(planNodeKey=key, acgNodeId=f"step-{key.lower()}")
        for key in keys
    )
    resource_plan = ACGResourcePlan(bindings=tuple(
        AgentBindingSpec(
            stepId=f"step-{key.lower()}",
            plannedAgentId="logical-agent",
            requiredCapabilities=(f"cap-{key.lower()}",),
        )
        for key in keys
    ))
    return ACGLoweringInput(
        mission_id=plan.mission_id,
        objective="Test lowering",
        complexity_level=ComplexityLevel.SIMPLE,
        task_plan=plan,
        steps=steps,
        implementation_bindings=bindings,
        resource_plan=resource_plan,
        metadata={"stable": True},
    )


def _structural_projection(blueprint) -> dict:
    return {
        "nodes": [
            node.model_dump(
                by_alias=True,
                exclude={"created_at", "updated_at"},
            )
            for node in blueprint.nodes
        ],
        "edges": [
            edge.model_dump(by_alias=True, exclude={"edge_id"})
            for edge in blueprint.edges
        ],
        "resourcePlan": blueprint.resource_plan.model_dump(by_alias=True),
        "metadata": blueprint.metadata,
    }


def test_lowering_is_deterministic_for_identical_frozen_input() -> None:
    lowering_input = _input(("A", "B"))
    first = ACGLowerer().lower(lowering_input)
    second = ACGLowerer().lower(lowering_input)

    assert _structural_projection(first) == _structural_projection(second)


def test_lowerer_preserves_frozen_capability_without_catalog_reselection() -> None:
    lowering_input = _input()

    blueprint = ACGLowerer().lower(lowering_input)

    assert [step.capability for step in blueprint.step_nodes()] == [
        "cap-a", "cap-b"
    ]
    assert [binding.planned_agent_id for binding in blueprint.resource_plan.bindings] == [
        "logical-agent", "logical-agent"
    ]


def test_missing_implementation_binding_fails_closed() -> None:
    lowering_input = _input()
    incomplete = replace(lowering_input, implementation_bindings=())

    with pytest.raises(ValueError, match="implementation bindings"):
        ACGLowerer().lower(incomplete)


def test_task_plan_diamond_is_lowered_without_added_ordering() -> None:
    lowering_input = _input(("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))
    blueprint = ACGLowerer().lower(lowering_input)
    dependencies = {
        (edge.source_id, edge.target_id)
        for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY)
    }

    assert dependencies == {
        ("step-a", "step-b"),
        ("step-a", "step-c"),
        ("step-b", "step-d"),
        ("step-c", "step-d"),
    }


def test_lowerer_module_has_no_planning_or_runtime_selection_imports() -> None:
    tree = ast.parse(inspect.getsource(lowerer_module))
    forbidden = {
        "CapabilityCatalog",
        "CognitiveRouter",
        "PlanningEngine",
        "IntentParser",
        "Provider",
        "LLM",
    }
    imported_names = {
        alias.name.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    imported_names.update(
        alias.name.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not imported_names & forbidden
