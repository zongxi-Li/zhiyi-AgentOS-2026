"""把 Planner 的语义任务树登记为 AgentOS TaskNode，不参与 ACG 设计或执行。"""

from __future__ import annotations

from collections.abc import Sequence

from contracts.identity import TaskNodeId, UserTaskId
from contracts.planning import TaskPlan, TaskPlanNode, TaskPlanPatch
from domain.models import TaskNode
from domain.repository import IdentityConflictError
from components.planner.service import apply_task_plan_patch

from .runner import AcgIdentityLifecycleService


class PlannerIdentityBridge:
    """持久化 Planner 语义输出；不选择 Agent、模型、资源或 WKN ACG 节点。"""

    def __init__(self, lifecycle_service: AcgIdentityLifecycleService) -> None:
        self.lifecycle_service = lifecycle_service

    def record_task_tree(
        self,
        task_id: UserTaskId,
        nodes: Sequence[TaskPlanNode],
    ) -> list[TaskNode]:
        return list(self.record_task_plan(TaskPlan(taskId=task_id, nodes=tuple(nodes))).values())

    def record_task_plan(self, plan: TaskPlan) -> dict[str, TaskNode]:
        """按稳定语义键幂等登记计划；语义发生漂移时拒绝覆盖历史节点。"""
        persisted = self.lifecycle_service.repositories.persist_task_plan(plan)
        if set(persisted) != {node.key for node in plan.nodes}:
            raise IdentityConflictError("TaskPlan persistence did not cover every semantic node")
        return persisted

    def record_task_plan_patch(self, patch: TaskPlanPatch) -> dict[str, TaskNode]:
        """把计划增量与既有稳定节点合成新版本后幂等登记。"""
        existing = self.lifecycle_service.repositories.task_nodes.list_for_task(
            patch.task_id
        )
        by_id = {node.node_id: node for node in existing}
        by_key = {
            str(node.metadata.get("plannerSemanticKey")): node
            for node in existing
            if node.metadata.get("plannerSemanticKey")
        }
        active_existing = [
            node for node in existing
            if node.status.value not in {"retired", "superseded"}
        ]
        if len(by_key) < len(active_existing):
            raise IdentityConflictError(
                "TaskPlanPatch requires stable semantic keys on every existing TaskNode"
            )
        current_nodes: list[TaskPlanNode] = []
        for key, node in by_key.items():
            if node.status.value in {"retired", "superseded"}:
                continue
            parent_key: str | None = None
            if node.parent_node_id is not None:
                parent = by_id.get(node.parent_node_id)
                if parent is None or not parent.metadata.get("plannerSemanticKey"):
                    raise IdentityConflictError(
                        "TaskPlanPatch found an unresolved existing parent identity"
                    )
                parent_key = str(parent.metadata["plannerSemanticKey"])
            current_nodes.append(TaskPlanNode(
                key=key,
                parentKey=parent_key,
                title=node.title,
                objective=node.objective,
                constraints=node.constraints,
                metadata={
                    key: value
                    for key, value in node.metadata.items()
                    if key not in {"plannerSemanticKey", "plannerPlanVersion"}
                },
            ))
        plan = TaskPlan(
            taskId=patch.task_id,
            planVersion=patch.plan_version,
            nodes=tuple(current_nodes),
            metadata={"source": "graph_patch", **patch.metadata},
        )
        return self.record_task_plan(apply_task_plan_patch(plan, patch))


__all__ = ["PlannerIdentityBridge", "TaskPlanNode"]
