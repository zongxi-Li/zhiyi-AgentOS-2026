"""把 WKN ACG 内核事件投影到 AgentOS V2 身份与生命周期。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from components.executor import ACGGraphCompiler
from contracts.identity import (
    AttemptId,
    BlueprintId,
    RunId,
    TaskNodeId,
    new_run_id,
    new_user_task_id,
)
from contracts.resource import ExecutionBinding as WknExecutionBinding
from domain.identity_graph import (
    BlueprintNodeBinding,
    BlueprintRelationType,
    ExecutionBinding,
    IdentityRelation,
    ProvenanceLink,
    TaskNodeBinding,
)
from domain.models import (
    AcgBlueprint,
    RunStatus,
    StepExecution,
    StepExecutionStatus,
)
from domain.repository import EntityNotFoundError, IdentityConflictError, RepositorySet
from support.acg.models import EdgeType, WknBlueprintSpec, validate_blueprint

from .context import ExecutionContext
from .runner import AcgIdentityLifecycleService


_EDGE_RELATIONS = {
    EdgeType.DEPENDENCY: BlueprintRelationType.DEPENDENCY,
    EdgeType.COMMUNICATION: BlueprintRelationType.COMMUNICATION,
    EdgeType.CONTROL_FLOW: BlueprintRelationType.CONTROL,
    EdgeType.EXECUTION: BlueprintRelationType.CONTROL,
}


class WknIdentityLifecycleAdapter:
    """只包装现有 WKN ACG；不实现第二套 Planner、Compiler、Scheduler 或 Executor。"""

    def __init__(
        self,
        lifecycle_service: AcgIdentityLifecycleService,
        repositories: RepositorySet,
    ) -> None:
        self.lifecycle_service = lifecycle_service
        self.repositories = repositories

    @property
    def runtime(self) -> AcgIdentityLifecycleService:
        """兼容 Phase 3 初版属性名；新代码使用 ``lifecycle_service``。"""
        return self.lifecycle_service

    def new_task_id(self) -> str:
        """由 AgentOS 身份合同为 WKN 新任务分配唯一 taskId。"""
        return new_user_task_id()

    def on_task_created(self, task: Any) -> None:
        """使用 WKN 已持久化任务的同一个 taskId 建立 UserTask。"""
        existing = self.repositories.user_tasks.get(task.task_id)
        if existing is not None:
            if existing.goal != self._task_goal(task):
                raise IdentityConflictError("taskId already belongs to another UserTask goal")
            return
        owner = str(task.input.get("authenticatedUserId") or "system:agentos")
        self.lifecycle_service.create_task(
            task_id=task.task_id,
            user_id=owner,
            goal=self._task_goal(task),
            description=str(task.input.get("description") or ""),
            metadata={
                "identityGeneration": "v2",
                "wknDomain": task.domain,
                "wknIntent": task.intent,
                "principalSource": (
                    "authenticatedUserId"
                    if task.input.get("authenticatedUserId")
                    else "system"
                ),
            },
        )

    def new_run_id(self, task_id: str) -> str:
        """为新执行分配随后由 WKN 全链路复用的 runId。"""
        if self.repositories.user_tasks.get(task_id) is None:
            raise EntityNotFoundError(f"UserTask not found: {task_id}")
        return new_run_id()

    def on_run_prepared(self, task: Any, run: Any, blueprint: WknBlueprintSpec) -> None:
        """登记真实 WKN Blueprint，并用同一 runId 建立 OS 运行身份。"""
        existing_run = self.repositories.runs.get(run.run_id)
        if existing_run is not None:
            if existing_run.task_id != task.task_id:
                raise IdentityConflictError("runId already belongs to another UserTask")
            return
        domain_blueprint = self._ensure_blueprint(task.task_id, blueprint)
        self.lifecycle_service.create_run(
            task_id=task.task_id,
            blueprint_id=domain_blueprint.blueprint_id,
            run_id=run.run_id,
            metadata={
                "identityGeneration": "v2",
                "wknWorkflowId": run.workflow_id,
                "wknGraphId": blueprint.graph_id,
            },
        )

    def on_blueprint_revised(self, run: Any, blueprint: WknBlueprintSpec) -> None:
        """把 WKN 审核屏障产生的图修订登记为新 Blueprint 版本。"""
        domain_run = self._run(run.run_id)
        if domain_run.task_id != run.task_id:
            raise IdentityConflictError("revised Blueprint does not belong to Run task")
        revised = self._ensure_blueprint(run.task_id, blueprint)
        if domain_run.blueprint_id == revised.blueprint_id:
            return
        self.repositories.runs.update_blueprint(
            run.run_id,
            revised.blueprint_id,
            revised.version,
        )

    def ensure_attempt(self, run: Any, step_id: str, attempt_number: int) -> str:
        """幂等创建 ACGNode 对应的 Attempt，并把其 ID 交回 WKN Scheduler。"""
        domain_run = self.repositories.runs.get(run.run_id)
        if domain_run is None:
            raise EntityNotFoundError(f"WorkflowRunV2 not found: {run.run_id}")
        node = self._resolve_task_node(domain_run.blueprint_id, step_id)
        existing = next(
            (
                item
                for item in self.repositories.attempts.list_for_run(run.run_id)
                if item.node_id == node.node_id and item.attempt_number == attempt_number
            ),
            None,
        )
        if existing is not None:
            return existing.attempt_id
        prior = [
            item
            for item in self.repositories.attempts.list_for_run(run.run_id)
            if item.node_id == node.node_id
        ]
        if attempt_number != len(prior) + 1:
            raise IdentityConflictError("WKN attempt number is not contiguous")
        return self.lifecycle_service.create_attempt(
            run_id=run.run_id,
            node_id=node.node_id,
        ).attempt_id

    def on_resource_bound(
        self,
        *,
        attempt_id: str,
        binding: WknExecutionBinding,
        agent_id: str,
        model_id: str,
    ) -> None:
        self.record_scheduling_binding(
            attempt_id=attempt_id,
            wkn_binding=binding,
            agent_id=agent_id,
            model_id=model_id,
        )

    def on_step_started(self, *, run_id: str, attempt_id: str, step_id: str) -> str:
        attempt = self.repositories.attempts.get(attempt_id)
        if attempt is None or attempt.run_id != run_id:
            raise IdentityConflictError("Step start does not belong to Attempt run")
        node = self._resolve_task_node(
            self._run(run_id).blueprint_id,
            step_id,
        )
        if node.node_id != attempt.node_id:
            raise IdentityConflictError("Step start does not match Attempt TaskNode")
        existing = self.repositories.step_executions.list_for_attempt(attempt_id)
        if existing:
            if len(existing) != 1:
                raise IdentityConflictError("Attempt has multiple StepExecutions")
            return existing[0].step_execution_id
        context = self.lifecycle_service.create_context(run_id)
        return self.lifecycle_service.start_step_execution(
            context,
            attempt_id=attempt_id,
            input={"wknStepId": step_id},
        ).step_execution_id

    def on_step_succeeded(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        result: dict[str, Any],
    ) -> None:
        execution = self._execution(step_execution_id, run_id, attempt_id)
        if execution.status is StepExecutionStatus.SUCCEEDED:
            return
        if execution.status is not StepExecutionStatus.RUNNING:
            raise IdentityConflictError("terminal StepExecution cannot become succeeded")
        safe_output = {
            key: result[key]
            for key in (
                "commitId",
                "outputRef",
                "outputSummary",
                "contextRef",
                "memoryRef",
                "traceRef",
                "auditDecisionRef",
            )
            if result.get(key) is not None
        }
        context = self.lifecycle_service.create_context(run_id)
        finished = self.lifecycle_service.complete_step_execution(
            context,
            step_execution_id,
            output=safe_output,
        )
        evidence_ids = self._provenance_event_ids(result)
        memory_ref = result.get("memoryRef")
        memory_ids = (
            [str(memory_ref)]
            if isinstance(memory_ref, str) and memory_ref and memory_ref != "memory:none"
            else []
        )
        self._record_provenance(finished, evidence_ids, memory_ids)

    def on_step_failed(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        reason: str,
    ) -> None:
        execution = self._execution(step_execution_id, run_id, attempt_id)
        if execution.status is StepExecutionStatus.FAILED:
            return
        if execution.status is not StepExecutionStatus.RUNNING:
            raise IdentityConflictError("terminal StepExecution cannot become failed")
        self.lifecycle_service.fail_step_execution(
            self.lifecycle_service.create_context(run_id),
            step_execution_id,
            failure_reason=reason,
        )

    def on_step_cancelled(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        reason: str,
    ) -> None:
        execution = self._execution(step_execution_id, run_id, attempt_id)
        if execution.status is StepExecutionStatus.CANCELLED:
            return
        if execution.status is not StepExecutionStatus.RUNNING:
            raise IdentityConflictError("terminal StepExecution cannot become cancelled")
        self.lifecycle_service.cancel_step_execution(
            self.lifecycle_service.create_context(run_id),
            step_execution_id,
            reason=reason,
        )

    def on_run_finished(self, run_id: str, status: str) -> None:
        target = {
            "succeeded": RunStatus.SUCCEEDED,
            "failed": RunStatus.FAILED,
            "cancelled": RunStatus.CANCELLED,
        }.get(status)
        if target is None:
            raise ValueError(f"unsupported terminal run status: {status}")
        run = self._run(run_id)
        if run.status is target:
            return
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise IdentityConflictError("terminal WorkflowRunV2 status cannot be rewritten")
        self.lifecycle_service.finish_run(run_id, target)

    def register_blueprint(
        self,
        *,
        task_id: str,
        version: int,
        wkn_blueprint: WknBlueprintSpec,
        task_node_bindings: Mapping[TaskNodeId, str],
        metadata: dict[str, Any] | None = None,
    ) -> AcgBlueprint:
        """登记 WKN 权威蓝图，并显式记录 TaskNode 到其 nodeId 的实现关系。"""
        if wkn_blueprint.task_id is not None and wkn_blueprint.task_id != task_id:
            raise IdentityConflictError("WKN Blueprint taskId does not match UserTask")
        validate_blueprint(wkn_blueprint)
        wkn_node_ids = {node.node_id for node in wkn_blueprint.nodes}
        if not task_node_bindings:
            raise ValueError("WKN Blueprint requires at least one TaskNode binding")
        for task_node_id, acg_node_id in task_node_bindings.items():
            if task_node_id == acg_node_id:
                raise IdentityConflictError("TaskNode identity must remain distinct from WKN ACG nodeId")
            if acg_node_id not in wkn_node_ids:
                raise IdentityConflictError(f"WKN ACG node does not exist: {acg_node_id}")
            node = self.repositories.task_nodes.get(task_node_id)
            if node is None:
                raise EntityNotFoundError(f"TaskNode not found: {task_node_id}")
            if node.task_id != task_id:
                raise IdentityConflictError("TaskNode does not belong to UserTask")

        graph = wkn_blueprint.model_dump(by_alias=True, mode="json")
        blueprint = self.lifecycle_service.create_blueprint(
            task_id=task_id,
            version=version,
            graph_id=wkn_blueprint.graph_id,
            graph=graph,
            metadata={**(metadata or {}), "kernel": "wkn-acg"},
        )
        for task_node_id, acg_node_id in task_node_bindings.items():
            self.repositories.task_node_bindings.add(TaskNodeBinding(
                taskNodeId=task_node_id,
                blueprintId=blueprint.blueprint_id,
                acgNodeId=acg_node_id,
            ))
        for edge in wkn_blueprint.edges:
            relation = _EDGE_RELATIONS.get(edge.edge_type)
            if relation is None:
                continue
            self.repositories.blueprint_node_bindings.add(BlueprintNodeBinding(
                blueprintId=blueprint.blueprint_id,
                sourceNodeId=edge.source_id,
                targetNodeId=edge.target_id,
                relationType=relation,
            ))
        return blueprint

    def compile(self, blueprint_id: BlueprintId, *, run_id: RunId):
        """直接委托 WKN ``ACGGraphCompiler``，返回其原生执行图。"""
        blueprint = self.repositories.blueprints.get(blueprint_id)
        if blueprint is None:
            raise EntityNotFoundError(f"AcgBlueprint not found: {blueprint_id}")
        run = self.repositories.runs.get(run_id)
        if run is None:
            raise EntityNotFoundError(f"WorkflowRunV2 not found: {run_id}")
        if run.blueprint_id != blueprint_id or run.task_id != blueprint.task_id:
            raise IdentityConflictError("WKN compilation identities do not belong to the Run")
        wkn_blueprint = WknBlueprintSpec.model_validate(blueprint.graph)
        return ACGGraphCompiler().compile(wkn_blueprint, run_id=run_id)

    def record_scheduling_binding(
        self,
        *,
        attempt_id: AttemptId,
        wkn_binding: WknExecutionBinding,
        agent_id: str,
        model_id: str,
    ) -> ExecutionBinding:
        """把 WKN Scheduler 的真实资源选择登记为 OS 级执行绑定。"""
        attempt = self.repositories.attempts.get(attempt_id)
        if attempt is None:
            raise EntityNotFoundError(f"Attempt not found: {attempt_id}")
        if wkn_binding.attempt_id != attempt_id or wkn_binding.run_id != attempt.run_id:
            raise IdentityConflictError("WKN scheduling binding does not match Attempt identity")
        existing = self.repositories.execution_bindings.get_for_attempt(attempt_id)
        if existing is not None:
            if (
                existing.acg_node_id != wkn_binding.step_id
                or existing.resource_id != wkn_binding.resource_id
                or existing.agent_id != agent_id
                or existing.model_id != model_id
            ):
                raise IdentityConflictError("Attempt already has another ExecutionBinding")
            return existing
        binding = ExecutionBinding(
            attemptId=attempt_id,
            acgNodeId=wkn_binding.step_id,
            resourceId=wkn_binding.resource_id,
            agentId=agent_id,
            modelId=model_id,
            metadata={
                "wknBindingId": wkn_binding.binding_id,
                "resourceType": wkn_binding.resource_type.value,
                "snapshotVersion": wkn_binding.snapshot_version,
                **wkn_binding.metadata,
            },
        )
        self.repositories.execution_bindings.add(binding)
        return binding

    def start_execution(
        self,
        context: ExecutionContext,
        *,
        input: dict[str, Any],
    ) -> StepExecution:
        """在 WKN NodeRunner 开始工作时创建生命周期投影。"""
        return self.lifecycle_service.start_step_execution(context, input=input)

    def finish_execution(
        self,
        context: ExecutionContext,
        step_execution_id: str,
        *,
        output: dict[str, Any],
        evidence_ids: Sequence[str] = (),
        memory_ids: Sequence[str] = (),
    ) -> StepExecution:
        """在 WKN NodeRunner 完成后结束投影并登记产物血缘。"""
        execution = self.lifecycle_service.complete_step_execution(
            context,
            step_execution_id,
            output=output,
        )
        self._record_provenance(execution, evidence_ids, memory_ids)
        return execution

    def fail_execution(
        self,
        context: ExecutionContext,
        step_execution_id: str,
        *,
        failure_reason: str,
        output: dict[str, Any] | None = None,
    ) -> StepExecution:
        """在 WKN NodeRunner 失败时记录相同 Attempt 的失败生命周期。"""
        return self.lifecycle_service.fail_step_execution(
            context,
            step_execution_id,
            failure_reason=failure_reason,
            output=output,
        )

    def _record_provenance(
        self,
        execution: StepExecution,
        evidence_ids: Sequence[str],
        memory_ids: Sequence[str],
    ) -> None:
        for evidence_id in evidence_ids:
            self._add_provenance(ProvenanceLink(
                sourceId=execution.step_execution_id,
                targetId=evidence_id,
                relationType=IdentityRelation.PRODUCES,
            ))
        for memory_id in memory_ids:
            self._add_provenance(ProvenanceLink(
                sourceId=execution.step_execution_id,
                targetId=memory_id,
                relationType=IdentityRelation.WRITES,
            ))

    def _ensure_blueprint(
        self,
        task_id: str,
        wkn_blueprint: WknBlueprintSpec,
    ) -> AcgBlueprint:
        graph = wkn_blueprint.model_dump(by_alias=True, mode="json")
        existing_blueprints = self.repositories.blueprints.list_for_task(task_id)
        for blueprint in existing_blueprints:
            if blueprint.graph == graph:
                return blueprint
        existing_nodes = self.repositories.task_nodes.list_for_task(task_id)
        by_semantic_key = {
            str(node.metadata.get("wknSemanticKey")): node
            for node in existing_nodes
            if node.metadata.get("wknSemanticKey")
        }
        bindings: dict[str, str] = {}
        for step in wkn_blueprint.step_nodes():
            node = by_semantic_key.get(step.node_id)
            if node is None:
                node = self.lifecycle_service.create_task_node(
                    task_id=task_id,
                    title=step.name or step.node_id,
                    objective=step.goal or step.description or step.name or step.node_id,
                    metadata={
                        "wknSemanticKey": step.node_id,
                        **({"capability": step.capability} if step.capability else {}),
                    },
                )
            bindings[node.node_id] = step.node_id
        version = max((item.version for item in existing_blueprints), default=0) + 1
        return self.register_blueprint(
            task_id=task_id,
            version=version,
            wkn_blueprint=wkn_blueprint,
            task_node_bindings=bindings,
            metadata={"wknSourceGraphVersion": wkn_blueprint.version},
        )

    def _resolve_task_node(self, blueprint_id: BlueprintId, step_id: str):
        bindings = self.repositories.task_node_bindings.find_for_acg_node(
            step_id, blueprint_id
        )
        if len(bindings) != 1:
            raise IdentityConflictError("WKN ACG node must have exactly one TaskNode binding")
        node = self.repositories.task_nodes.get(bindings[0].task_node_id)
        if node is None:
            raise EntityNotFoundError(f"TaskNode not found: {bindings[0].task_node_id}")
        return node

    def _run(self, run_id: str):
        run = self.repositories.runs.get(run_id)
        if run is None:
            raise EntityNotFoundError(f"WorkflowRunV2 not found: {run_id}")
        return run

    def _execution(self, step_execution_id: str, run_id: str, attempt_id: str):
        execution = self.repositories.step_executions.get(step_execution_id)
        if execution is None:
            raise EntityNotFoundError(f"StepExecution not found: {step_execution_id}")
        if execution.run_id != run_id or execution.attempt_id != attempt_id:
            raise IdentityConflictError("StepExecution does not belong to WKN execution identity")
        return execution

    def _add_provenance(self, link: ProvenanceLink) -> None:
        if any(
            item.target_id == link.target_id and item.relation_type is link.relation_type
            for item in self.repositories.provenance_links.list_from(link.source_id)
        ):
            return
        self.repositories.provenance_links.add(link)

    @staticmethod
    def _task_goal(task: Any) -> str:
        return str(
            task.input.get("taskGoal")
            or task.input.get("userIntent")
            or task.title
        ).strip()

    @staticmethod
    def _provenance_event_ids(result: dict[str, Any]) -> list[str]:
        event_ids: list[str] = []
        for event in result.get("provenanceEvents") or []:
            payload = event.get("payload") if isinstance(event, dict) else None
            event_id = payload.get("eventId") if isinstance(payload, dict) else None
            if isinstance(event_id, str) and event_id:
                event_ids.append(event_id)
        return list(dict.fromkeys(event_ids))


# 兼容 Phase 3 初版名称；新代码使用 Adapter 明确其不是新的执行桥内核。
WknAcgIdentityBridge = WknIdentityLifecycleAdapter


__all__ = ["WknAcgIdentityBridge", "WknIdentityLifecycleAdapter"]
