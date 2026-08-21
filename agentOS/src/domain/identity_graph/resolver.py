"""沿持久化 Identity Graph 解析任务、执行和血缘来源。"""

from __future__ import annotations

from contracts.identity import BlueprintId, StepExecutionId, TaskNodeId
from domain.models import TaskNode
from domain.repository.contracts import RepositorySet
from domain.repository.errors import EntityNotFoundError, IdentityConflictError

from .bindings import ProvenanceLink
from .contracts import ExecutionOrigin


class IdentityResolver:
    def __init__(self, repositories: RepositorySet) -> None:
        self.repositories = repositories

    def resolve_task_node(
        self,
        *,
        blueprint_id: BlueprintId,
        acg_node_id: str,
    ) -> TaskNode:
        bindings = self.repositories.task_node_bindings.find_for_acg_node(
            acg_node_id, blueprint_id
        )
        if not bindings:
            raise EntityNotFoundError(f"TaskNodeBinding not found for ACGNode: {acg_node_id}")
        primary = [item for item in bindings if item.binding_type.value == "primary"]
        selected = primary[0] if len(primary) == 1 else bindings[0]
        if len(primary) > 1:
            raise IdentityConflictError("ACGNode has multiple primary TaskNode bindings")
        node = self.repositories.task_nodes.get(selected.task_node_id)
        if node is None:
            raise EntityNotFoundError(f"TaskNode not found: {selected.task_node_id}")
        return node

    def resolve_acg_node(
        self,
        *,
        task_node_id: TaskNodeId,
        blueprint_id: BlueprintId,
    ) -> list[str]:
        return [
            binding.acg_node_id
            for binding in self.repositories.task_node_bindings.find_for_task_node(
                task_node_id, blueprint_id
            )
        ]

    def resolve_execution_origin(
        self,
        step_execution_id: StepExecutionId,
    ) -> ExecutionOrigin:
        execution = self.repositories.step_executions.get(step_execution_id)
        if execution is None:
            raise EntityNotFoundError(f"StepExecution not found: {step_execution_id}")
        attempt = self.repositories.attempts.get(execution.attempt_id)
        if attempt is None:
            raise EntityNotFoundError(f"Attempt not found: {execution.attempt_id}")
        run = self.repositories.runs.get(execution.run_id)
        if run is None:
            raise EntityNotFoundError(f"WorkflowRunV2 not found: {execution.run_id}")
        binding = self.repositories.execution_bindings.get_for_attempt(attempt.attempt_id)
        if binding is None:
            raise EntityNotFoundError(
                f"ExecutionBinding not found for Attempt: {attempt.attempt_id}"
            )
        task_bindings = self.repositories.task_node_bindings.find_for_acg_node(
            binding.acg_node_id, run.blueprint_id
        )
        task_binding = next(
            (item for item in task_bindings if item.task_node_id == attempt.node_id),
            None,
        )
        if task_binding is None:
            raise IdentityConflictError("ExecutionBinding is detached from its TaskNode")
        task_node = self.repositories.task_nodes.get(attempt.node_id)
        blueprint = self.repositories.blueprints.get(run.blueprint_id)
        user_task = self.repositories.user_tasks.get(run.task_id)
        if task_node is None or blueprint is None or user_task is None:
            raise EntityNotFoundError("execution origin contains a missing identity")
        return ExecutionOrigin(
            userTask=user_task,
            taskNode=task_node,
            blueprint=blueprint,
            run=run,
            attempt=attempt,
            stepExecution=execution,
            taskNodeBinding=task_binding,
            executionBinding=binding,
        )

    def resolve_provenance(
        self,
        identity: str,
        *,
        direction: str = "outgoing",
    ) -> list[ProvenanceLink]:
        if direction == "outgoing":
            return self.repositories.provenance_links.list_from(identity)
        if direction == "incoming":
            return self.repositories.provenance_links.list_to(identity)
        raise ValueError("provenance direction must be outgoing or incoming")


__all__ = ["IdentityResolver"]
