"""把 Planner 的语义任务树登记为 AgentOS TaskNode，不参与 ACG 设计或执行。"""

from __future__ import annotations

from collections.abc import Sequence

from contracts.identity import UserTaskId
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
        """Apply Planner output only against the immutable prior plan snapshot."""
        current = self.lifecycle_service.repositories.task_plans.latest(patch.task_id)
        if current is None:
            raise IdentityConflictError("TaskPlanPatch requires a persisted base TaskPlan")
        return self.record_task_plan(apply_task_plan_patch(current, patch))


__all__ = ["PlannerIdentityBridge", "TaskPlanNode"]
