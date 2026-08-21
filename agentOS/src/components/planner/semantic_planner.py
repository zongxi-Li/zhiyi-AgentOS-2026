"""Planner-owned production of execution-agnostic TaskPlan contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from contracts.planning import (
    TaskNodeRelationType,
    TaskPlan,
    TaskPlanNode,
    TaskPlanRelation,
)
from support.acg.models import CapabilityCatalog


class SemanticPlanningError(ValueError):
    pass


class SemanticPlanner:
    def __init__(self, capability_catalog: CapabilityCatalog) -> None:
        self.capability_catalog = capability_catalog

    def plan_capabilities(
        self,
        *,
        task_id: str,
        capabilities: Sequence[str],
        strategy: str,
        plan_version: int = 1,
    ) -> TaskPlan:
        ordered = list(dict.fromkeys(capabilities))
        if not ordered:
            raise SemanticPlanningError("Planner produced no semantic capabilities")
        selected = set(ordered)
        nodes: list[TaskPlanNode] = []
        for capability in ordered:
            descriptor = self.capability_catalog.get(capability)
            dependencies = [item for item in descriptor.depends_on if item in selected]
            nodes.append(TaskPlanNode(
                key=f"capability:{descriptor.capability_id}",
                title=descriptor.display_name,
                objective=descriptor.description or f"Complete {descriptor.display_name}",
                constraints=[
                    {"type": "required_capability", "value": descriptor.capability_id},
                    *(
                        [{"type": "depends_on", "values": dependencies}]
                        if dependencies else []
                    ),
                ],
                capabilityRequirements=(descriptor.capability_id,),
                metadata={"plannerStrategy": strategy},
            ))
        relations = tuple(
            TaskPlanRelation(
                sourceKey=f"capability:{dependency}",
                targetKey=f"capability:{capability}",
                relationType=TaskNodeRelationType.DEPENDS_ON,
            )
            for capability in ordered
            for dependency in self.capability_catalog.get(capability).depends_on
            if dependency in selected
        )
        return TaskPlan(
            taskId=task_id,
            planVersion=plan_version,
            nodes=tuple(nodes),
            relations=relations,
            metadata={"strategy": strategy},
        )

    def plan_template(
        self,
        *,
        task_id: str,
        workflow: Any,
        strategy: str,
        plan_version: int = 1,
    ) -> TaskPlan:
        declared_nodes = tuple(getattr(workflow, "planning_nodes", ()) or ())
        if not declared_nodes:
            raise SemanticPlanningError(
                f"workflow template {workflow.workflow_id} has no Planner semantic declaration"
            )
        nodes = tuple(
            node.model_copy(update={
                "metadata": {**node.metadata, "plannerStrategy": strategy},
            })
            for node in declared_nodes
        )
        return TaskPlan(
            taskId=task_id,
            planVersion=plan_version,
            nodes=nodes,
            relations=tuple(getattr(workflow, "planning_relations", ()) or ()),
            metadata={"strategy": strategy},
        )


__all__ = ["SemanticPlanner", "SemanticPlanningError"]
