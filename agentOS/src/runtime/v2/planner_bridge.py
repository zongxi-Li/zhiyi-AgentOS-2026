"""把 Planner 的语义任务树登记为 AgentOS TaskNode，不参与 ACG 设计或执行。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.identity import TaskNodeId, UserTaskId
from domain.models import TaskNode
from domain.repository import IdentityConflictError

from .runner import AcgIdentityLifecycleService


_EXECUTION_IDENTITY_KEYS = {
    "acgNodeId",
    "agentId",
    "agentName",
    "modelId",
    "resourceId",
}


class TaskPlanNode(BaseModel):
    """Planner 输出的纯语义节点；``key`` 只在本次树登记期间使用。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    parent_key: str | None = Field(default=None, alias="parentKey")
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlannerIdentityBridge:
    """持久化 Planner 语义输出；不选择 Agent、模型、资源或 WKN ACG 节点。"""

    def __init__(self, lifecycle_service: AcgIdentityLifecycleService) -> None:
        self.lifecycle_service = lifecycle_service

    def record_task_tree(
        self,
        task_id: UserTaskId,
        nodes: Sequence[TaskPlanNode],
    ) -> list[TaskNode]:
        if not nodes:
            raise ValueError("Planner task tree cannot be empty")
        keys = [node.key for node in nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("Planner task tree contains duplicate keys")
        known_keys = set(keys)
        for node in nodes:
            if node.parent_key == node.key:
                raise ValueError("Planner task node cannot be its own parent")
            if node.parent_key is not None and node.parent_key not in known_keys:
                raise ValueError(f"Planner task node has unknown parent: {node.parent_key}")
            self._reject_execution_identity(node.model_dump(by_alias=True))

        remaining = list(nodes)
        persisted: list[TaskNode] = []
        identities: dict[str, TaskNodeId] = {}
        while remaining:
            ready = [
                node for node in remaining
                if node.parent_key is None or node.parent_key in identities
            ]
            if not ready:
                raise ValueError("Planner task tree contains a parent cycle")
            for node in ready:
                persisted_node = self.lifecycle_service.create_task_node(
                    task_id=task_id,
                    parent_node_id=(identities.get(node.parent_key) if node.parent_key else None),
                    title=node.title,
                    objective=node.objective,
                    constraints=node.constraints,
                    metadata=node.metadata,
                )
                identities[node.key] = persisted_node.node_id
                persisted.append(persisted_node)
                remaining.remove(node)
        return persisted

    @classmethod
    def _reject_execution_identity(cls, value: Any) -> None:
        if isinstance(value, dict):
            forbidden = _EXECUTION_IDENTITY_KEYS.intersection(value)
            if forbidden:
                raise IdentityConflictError(
                    "Planner cannot select execution identities: " + ", ".join(sorted(forbidden))
                )
            for nested in value.values():
                cls._reject_execution_identity(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._reject_execution_identity(nested)


__all__ = ["PlannerIdentityBridge", "TaskPlanNode"]
