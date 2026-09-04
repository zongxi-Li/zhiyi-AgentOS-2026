"""把 Planner 的语义任务树登记为 AgentOS SemanticTask，不参与 ACG 设计或执行。"""

from __future__ import annotations

from collections.abc import Sequence

from contracts.identity import MissionId
from contracts.planning import TaskPlan, PlannedTask, TaskPlanPatch
from domain.models import SemanticTask
from domain.repository import IdentityConflictError
from components.planner.service import apply_task_plan_patch

from .runner import AcgIdentityLifecycleService


class PlannerIdentityBridge:
    """持久化 Planner 语义输出；不选择 Agent、模型、资源或 ACG 节点。"""

    def __init__(self, lifecycle_service: AcgIdentityLifecycleService) -> None:
        self.lifecycle_service = lifecycle_service

    def record_task_tree(
        self,
        mission_id: MissionId,
        nodes: Sequence[PlannedTask],
    ) -> list[SemanticTask]:
        return list(self.record_task_plan(TaskPlan(missionId=mission_id, nodes=tuple(nodes))).values())

    def record_task_plan(self, plan: TaskPlan) -> dict[str, SemanticTask]:
        """按稳定逻辑键登记计划；新 Run 的内容变化留在新的 TaskPlan 快照中。"""
        persisted = self.lifecycle_service.repositories.persist_task_plan(plan)
        if set(persisted) != {node.key for node in plan.nodes}:
            raise IdentityConflictError("TaskPlan persistence did not cover every semantic node")
        return persisted

    def record_task_plan_patch(self, patch: TaskPlanPatch) -> dict[str, SemanticTask]:
        """Apply Planner output only against the immutable prior plan snapshot."""
        current = self.lifecycle_service.repositories.task_plans.latest(patch.mission_id)
        if current is None:
            raise IdentityConflictError("TaskPlanPatch requires a persisted base TaskPlan")
        return self.record_task_plan(apply_task_plan_patch(current, patch))


__all__ = ["PlannerIdentityBridge", "PlannedTask"]
