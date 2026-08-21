"""把 WKN ACG 内核事件投影到 AgentOS V2 身份与生命周期。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
import hashlib
import json
from types import SimpleNamespace
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
from contracts.planning import (
    TaskNodeBindingPatch,
    TaskNodeImplementationBinding,
    TaskPlan,
    TaskPlanPatch,
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
from domain.lifecycle_projection import LifecycleProjectionEvent
from domain.repository import EntityNotFoundError, IdentityConflictError, RepositorySet
from support.acg.models import EdgeType, WknBlueprintSpec, validate_blueprint
from components.planner.service import apply_task_plan_patch

from .context import ExecutionContext
from .planner_bridge import PlannerIdentityBridge
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
        payload = {
            "taskId": task.task_id,
            "goal": self._task_goal(task),
            "description": str(task.input.get("description") or ""),
            "domain": task.domain,
            "intent": task.intent,
            "userId": str(task.input.get("authenticatedUserId") or "system:agentos"),
            "tenantId": str(task.input.get("authenticatedTenantId") or ""),
        }
        with self._projection(
            f"task.created:{task.task_id}",
            "task.created",
            task.task_id,
            payload,
        ):
            self._on_task_created(task)

    def _on_task_created(self, task: Any) -> None:
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
                **(
                    {"tenantId": str(task.input["authenticatedTenantId"])}
                    if task.input.get("authenticatedTenantId")
                    else {}
                ),
            },
        )

    def new_run_id(self, task_id: str) -> str:
        """为新执行分配随后由 WKN 全链路复用的 runId。"""
        if self.repositories.user_tasks.get(task_id) is None:
            raise EntityNotFoundError(f"UserTask not found: {task_id}")
        return new_run_id()

    def on_run_prepared(
        self,
        task: Any,
        run: Any,
        blueprint: WknBlueprintSpec,
        task_plan: TaskPlan,
        task_node_bindings: Sequence[TaskNodeImplementationBinding],
    ) -> None:
        """登记真实 WKN Blueprint，并用同一 runId 建立 OS 运行身份。"""
        payload = {
            "taskId": task.task_id,
            "runId": run.run_id,
            "workflowId": run.workflow_id,
            "blueprint": blueprint.model_dump(by_alias=True, mode="json"),
            "taskPlan": task_plan.model_dump(by_alias=True, mode="json"),
            "taskNodeBindings": [
                item.model_dump(by_alias=True, mode="json")
                for item in task_node_bindings
            ],
            "runProjection": self._safe_run_projection(run),
        }
        with self._projection(
            f"run.prepared:{run.run_id}",
            "run.prepared",
            run.run_id,
            payload,
        ):
            self._on_run_prepared(
                task,
                run,
                blueprint,
                task_plan,
                task_node_bindings,
            )

    def _on_run_prepared(
        self,
        task: Any,
        run: Any,
        blueprint: WknBlueprintSpec,
        task_plan: TaskPlan,
        task_node_bindings: Sequence[TaskNodeImplementationBinding],
    ) -> None:
        with self.repositories.storage.transaction():
            self._on_run_prepared_atomic(
                task,
                run,
                blueprint,
                task_plan,
                task_node_bindings,
            )

    def _on_run_prepared_atomic(
        self,
        task: Any,
        run: Any,
        blueprint: WknBlueprintSpec,
        task_plan: TaskPlan,
        task_node_bindings: Sequence[TaskNodeImplementationBinding],
    ) -> None:
        existing_run = self.repositories.runs.get(run.run_id)
        if existing_run is not None:
            if existing_run.task_id != task.task_id:
                raise IdentityConflictError("runId already belongs to another UserTask")
            existing_blueprint = self.repositories.blueprints.get(
                existing_run.blueprint_id
            )
            if (
                existing_blueprint is None
                or existing_blueprint.graph
                != blueprint.model_dump(by_alias=True, mode="json")
            ):
                raise IdentityConflictError(
                    "runId already identifies another Blueprint version"
                )
        if task_plan.task_id != task.task_id:
            raise IdentityConflictError("TaskPlan does not belong to WKN AgentTask")
        bindings_by_key = {
            binding.plan_node_key: binding.acg_node_id
            for binding in task_node_bindings
        }
        if len(bindings_by_key) != len(task_node_bindings):
            raise IdentityConflictError("Blueprint contains duplicate TaskNode bindings")
        if len(set(bindings_by_key.values())) != len(task_node_bindings):
            raise IdentityConflictError(
                "Each TaskPlan node requires a distinct executable Blueprint node"
            )
        plan_node_keys = {node.key for node in task_plan.nodes}
        if set(bindings_by_key) != plan_node_keys:
            raise IdentityConflictError("Blueprint bindings must cover the complete TaskPlan")
        executable_node_ids = {node.node_id for node in blueprint.step_nodes()}
        if set(bindings_by_key.values()) != executable_node_ids:
            raise IdentityConflictError(
                "Every executable Blueprint node requires an explicit TaskNode binding"
            )

        # 先完成纯校验，再写入 TaskNode，避免非法绑定留下部分身份数据。
        planned_nodes = PlannerIdentityBridge(self.lifecycle_service).record_task_plan(
            task_plan
        )
        explicit_bindings = {
            planned_nodes[key].node_id: acg_node_id
            for key, acg_node_id in bindings_by_key.items()
        }
        domain_blueprint = self._ensure_blueprint(
            task.task_id,
            blueprint,
            explicit_bindings,
            plan_version=task_plan.plan_version,
        )
        if existing_run is not None:
            if (
                existing_run.blueprint_id != domain_blueprint.blueprint_id
                or existing_run.graph_version != domain_blueprint.version
            ):
                raise IdentityConflictError(
                    "runId already identifies another execution definition"
                )
            return
        execution_state = getattr(run, "execution_state", {})
        lineage = {
            key: execution_state[key]
            for key in ("parentRunId", "supersedesRunId", "sourcePatchId")
            if isinstance(execution_state, dict) and execution_state.get(key)
        }
        self.lifecycle_service.create_run(
            task_id=task.task_id,
            blueprint_id=domain_blueprint.blueprint_id,
            run_id=run.run_id,
            metadata={
                "identityGeneration": "v2",
                "wknWorkflowId": run.workflow_id,
                "wknGraphId": blueprint.graph_id,
                **self._identity_run_metadata(run),
                **lineage,
            },
        )

    def on_run_snapshot(self, run_id: str, projection: dict[str, Any]) -> None:
        """Refresh reference-only operational state without reading WKN."""
        payload = {"runId": run_id, "projection": dict(projection)}
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self._projection(
            f"run.snapshot:{run_id}:{digest}",
            "run.snapshot",
            run_id,
            payload,
        ):
            self._on_run_snapshot(run_id, projection)

    def _on_run_snapshot(self, run_id: str, projection: dict[str, Any]) -> None:
        self._run(run_id)
        self.repositories.runs.merge_metadata(
            run_id,
            self._identity_run_metadata(
                SimpleNamespace(execution_state=dict(projection or {}))
            ),
        )

    def on_blueprint_revised(
        self,
        run: Any,
        blueprint: WknBlueprintSpec,
        task_plan_patch: TaskPlanPatch | None = None,
        task_node_binding_patch: TaskNodeBindingPatch | None = None,
    ) -> str:
        """把 WKN 审核屏障产生的图修订登记为新 Blueprint 版本。"""
        payload = {
            "taskId": run.task_id,
            "runId": run.run_id,
            "blueprint": blueprint.model_dump(by_alias=True, mode="json"),
            "taskPlanPatch": (
                task_plan_patch.model_dump(by_alias=True, mode="json")
                if task_plan_patch is not None
                else None
            ),
            "taskNodeBindingPatch": (
                task_node_binding_patch.model_dump(by_alias=True, mode="json")
                if task_node_binding_patch is not None else None
            ),
        }
        with self._projection(
            f"blueprint.revised:{run.run_id}:{blueprint.version}",
            "blueprint.revised",
            run.run_id,
            payload,
        ):
            return self._on_blueprint_revised_as_new_run(
                run,
                blueprint,
                task_plan_patch,
                task_node_binding_patch,
            )

    def on_graph_patch_prepared(
        self,
        task: Any,
        old_run: Any,
        new_run: Any,
        blueprint: WknBlueprintSpec,
        task_plan: TaskPlan,
        task_node_bindings: Sequence[TaskNodeImplementationBinding],
        patch_id: str,
    ) -> None:
        """Atomically create the replacement identity Run and supersede its parent."""
        payload = {
            "taskId": task.task_id,
            "oldRunId": old_run.run_id,
            "newRunId": new_run.run_id,
            "workflowId": new_run.workflow_id,
            "patchId": patch_id,
            "blueprint": blueprint.model_dump(by_alias=True, mode="json"),
            "taskPlan": task_plan.model_dump(by_alias=True, mode="json"),
            "taskNodeBindings": [
                item.model_dump(by_alias=True, mode="json")
                for item in task_node_bindings
            ],
            "executionState": dict(getattr(new_run, "execution_state", {}) or {}),
        }
        with self._projection(
            f"graph.patch.prepared:{old_run.run_id}:{patch_id}",
            "graph.patch.prepared",
            old_run.run_id,
            payload,
        ):
            with self.repositories.storage.transaction():
                self._on_run_prepared_atomic(
                    task,
                    new_run,
                    blueprint,
                    task_plan,
                    task_node_bindings,
                )
                self._on_run_superseded(old_run.run_id)

    def _on_blueprint_revised_as_new_run(
        self,
        run: Any,
        blueprint: WknBlueprintSpec,
        task_plan_patch: TaskPlanPatch | None,
        task_node_binding_patch: TaskNodeBindingPatch | None,
    ) -> str:
        domain_run = self._run(run.run_id)
        if domain_run.task_id != run.task_id:
            raise IdentityConflictError("revised Blueprint does not belong to Run task")
        prior_graph = WknBlueprintSpec.model_validate(
            self.repositories.blueprints.get(domain_run.blueprint_id).graph
        )
        prior_step_ids = {node.node_id for node in prior_graph.step_nodes()}
        revised_step_ids = {node.node_id for node in blueprint.step_nodes()}
        if prior_step_ids - revised_step_ids:
            raise IdentityConflictError("Blueprint revision cannot remove executable nodes")
        current_plan = self.repositories.task_plans.latest(run.task_id)
        if current_plan is None:
            raise EntityNotFoundError("TaskPlan is missing for Blueprint revision")
        next_plan = current_plan
        if revised_step_ids - prior_step_ids:
            if task_plan_patch is None or task_node_binding_patch is None:
                raise IdentityConflictError("new executable nodes require TaskPlanPatch and TaskNodeBindingPatch")
            next_plan = apply_task_plan_patch(current_plan, task_plan_patch)
            binding_patch = task_node_binding_patch.bindings
        else:
            if task_plan_patch is not None or task_node_binding_patch is not None:
                raise IdentityConflictError("patch data is only valid when executable nodes are added")
            binding_patch = ()
        by_key = {
            str(node.metadata.get("plannerSemanticKey")): node
            for node in self.repositories.task_nodes.list_for_task(run.task_id)
            if node.metadata.get("plannerSemanticKey")
        }
        binding_items: list[TaskNodeImplementationBinding] = []
        for node in next_plan.nodes:
            task_node = by_key.get(node.key)
            if task_node is None:
                continue
            existing = self.repositories.task_node_bindings.find_for_task_node(
                task_node.node_id,
                domain_run.blueprint_id,
            )
            if existing:
                binding_items.append(TaskNodeImplementationBinding(
                    planNodeKey=node.key,
                    acgNodeId=existing[0].acg_node_id,
                ))
        binding_items.extend(binding_patch)
        new_run_id = self.new_run_id(run.task_id)
        new_run = SimpleNamespace(
            run_id=new_run_id,
            task_id=run.task_id,
            workflow_id=run.workflow_id,
        )
        task = SimpleNamespace(task_id=run.task_id)
        self.on_run_prepared(task, new_run, blueprint, next_plan, tuple(binding_items))
        self.on_run_superseded(run.run_id, new_run_id, str(getattr(run, "run_id", "blueprint-revision")))
        return new_run_id

    def _on_blueprint_revised(
        self,
        run: Any,
        blueprint: WknBlueprintSpec,
        task_plan_patch: TaskPlanPatch | None,
        task_node_binding_patch: TaskNodeBindingPatch | None,
    ) -> None:
        domain_run = self._run(run.run_id)
        if domain_run.task_id != run.task_id:
            raise IdentityConflictError("revised Blueprint does not belong to Run task")
        prior_blueprint = self.repositories.blueprints.get(domain_run.blueprint_id)
        if prior_blueprint is None:
            raise EntityNotFoundError(
                f"AcgBlueprint not found: {domain_run.blueprint_id}"
            )
        if prior_blueprint.graph == blueprint.model_dump(by_alias=True, mode="json"):
            return
        prior_graph = WknBlueprintSpec.model_validate(prior_blueprint.graph)
        prior_step_ids = {node.node_id for node in prior_graph.step_nodes()}
        revised_step_ids = {node.node_id for node in blueprint.step_nodes()}
        added_step_ids = revised_step_ids - prior_step_ids
        if prior_step_ids - revised_step_ids:
            raise IdentityConflictError(
                "Blueprint revision cannot remove executable nodes from the identity graph"
            )
        prior_bindings: dict[str, str] = {}
        for node in self.repositories.task_nodes.list_for_task(run.task_id):
            matches = self.repositories.task_node_bindings.find_for_task_node(
                node.node_id,
                domain_run.blueprint_id,
            )
            for binding in matches:
                prior_bindings[node.node_id] = binding.acg_node_id
        prior_plan_version = int(prior_blueprint.metadata.get("plannerPlanVersion") or 1)
        next_plan_version = prior_plan_version
        if added_step_ids:
            if task_plan_patch is None:
                raise IdentityConflictError(
                    "new executable Blueprint nodes require a TaskPlanPatch"
                )
            if task_plan_patch.task_id != run.task_id:
                raise IdentityConflictError("TaskPlanPatch does not belong to Run task")
            if task_plan_patch.base_plan_version != prior_plan_version:
                raise IdentityConflictError(
                    "TaskPlanPatch basePlanVersion does not match active Blueprint plan"
                )
            if task_node_binding_patch is None:
                raise IdentityConflictError("new executable Blueprint nodes require TaskNodeBindingPatch")
            patch_binding_ids = {item.acg_node_id for item in task_node_binding_patch.bindings}
            if patch_binding_ids != added_step_ids:
                raise IdentityConflictError(
                    "TaskPlanPatch bindings must cover exactly the added executable nodes"
                )
            planned_nodes = PlannerIdentityBridge(
                self.lifecycle_service
            ).record_task_plan_patch(task_plan_patch)
            for binding in task_node_binding_patch.bindings:
                prior_bindings[
                    planned_nodes[binding.plan_node_key].node_id
                ] = binding.acg_node_id
            next_plan_version = task_plan_patch.plan_version
        elif task_plan_patch is not None:
            raise IdentityConflictError(
                "TaskPlanPatch is only valid when executable Blueprint nodes are added"
            )
        revised = self._ensure_blueprint(
            run.task_id,
            blueprint,
            prior_bindings,
            plan_version=next_plan_version,
        )
        if domain_run.blueprint_id == revised.blueprint_id:
            return
        self.repositories.runs.update_blueprint(
            run.run_id,
            revised.blueprint_id,
            revised.version,
        )

    def ensure_attempt(self, run: Any, step_id: str, attempt_number: int) -> str:
        """幂等创建 ACGNode 对应的 Attempt，并把其 ID 交回 WKN Scheduler。"""
        payload = {
            "runId": run.run_id,
            "taskId": run.task_id,
            "stepId": step_id,
            "attemptNumber": attempt_number,
        }
        with self._projection(
            f"attempt.ensured:{run.run_id}:{step_id}:{attempt_number}",
            "attempt.ensured",
            run.run_id,
            payload,
        ):
            return self._ensure_attempt(run, step_id, attempt_number)

    def _ensure_attempt(self, run: Any, step_id: str, attempt_number: int, attempt_id: str | None = None) -> str:
        domain_run = self.repositories.runs.get(run.run_id)
        if domain_run is None:
            raise EntityNotFoundError(f"WorkflowRunV2 not found: {run.run_id}")
        node = self._resolve_task_node(domain_run.blueprint_id, step_id)
        return self.lifecycle_service.create_attempt(
            run_id=run.run_id,
            node_id=node.node_id,
            attempt_number=attempt_number,
            attempt_id=attempt_id,
        ).attempt_id

    def on_resource_bound(
        self,
        *,
        attempt_id: str,
        binding: WknExecutionBinding,
        agent_id: str,
        model_id: str,
    ) -> None:
        payload = {
            "attemptId": attempt_id,
            "binding": binding.model_dump(by_alias=True, mode="json"),
            "agentId": agent_id,
            "modelId": model_id,
        }
        with self._projection(
            f"resource.bound:{attempt_id}",
            "resource.bound",
            attempt_id,
            payload,
        ):
            self.record_scheduling_binding(
                attempt_id=attempt_id,
                wkn_binding=binding,
                agent_id=agent_id,
                model_id=model_id,
            )

    def on_step_started(self, *, run_id: str, attempt_id: str, step_id: str) -> str:
        payload = {"runId": run_id, "attemptId": attempt_id, "stepId": step_id}
        with self._projection(
            f"step.started:{attempt_id}",
            "step.started",
            attempt_id,
            payload,
        ):
            return self._on_step_started(
                run_id=run_id,
                attempt_id=attempt_id,
                step_id=step_id,
            )

    def _on_step_started(self, *, run_id: str, attempt_id: str, step_id: str, step_execution_id: str | None = None) -> str:
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
            step_execution_id=step_execution_id,
        ).step_execution_id

    def on_step_succeeded(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        result: dict[str, Any],
    ) -> None:
        payload = {
            "runId": run_id,
            "attemptId": attempt_id,
            "stepExecutionId": step_execution_id,
            "result": self._safe_projection_result(result),
        }
        with self._projection(
            f"step.succeeded:{step_execution_id}",
            "step.succeeded",
            step_execution_id,
            payload,
        ):
            self._on_step_succeeded(
                run_id=run_id,
                attempt_id=attempt_id,
                step_execution_id=step_execution_id,
                result=result,
            )

    def _on_step_succeeded(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        result: dict[str, Any],
    ) -> None:
        execution = self._execution(step_execution_id, run_id, attempt_id)
        evidence_ids = self._provenance_event_ids(result)
        memory_ref = result.get("memoryRef")
        memory_ids = (
            [str(memory_ref)]
            if isinstance(memory_ref, str) and memory_ref and memory_ref != "memory:none"
            else []
        )
        if execution.status is StepExecutionStatus.SUCCEEDED:
            self._record_provenance(execution, evidence_ids, memory_ids)
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
                "nodeExecution",
                "communicationRefs",
                "evidenceRefs",
            )
            if result.get(key) is not None
        }
        context = self.lifecycle_service.create_context(run_id)
        finished = self.lifecycle_service.complete_step_execution(
            context,
            step_execution_id,
            output=safe_output,
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
        payload = {
            "runId": run_id,
            "attemptId": attempt_id,
            "stepExecutionId": step_execution_id,
            "reason": reason,
        }
        with self._projection(
            f"step.failed:{step_execution_id}",
            "step.failed",
            step_execution_id,
            payload,
        ):
            self._on_step_failed(
                run_id=run_id,
                attempt_id=attempt_id,
                step_execution_id=step_execution_id,
                reason=reason,
            )

    def _on_step_failed(
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
        payload = {
            "runId": run_id,
            "attemptId": attempt_id,
            "stepExecutionId": step_execution_id,
            "reason": reason,
        }
        with self._projection(
            f"step.cancelled:{step_execution_id}",
            "step.cancelled",
            step_execution_id,
            payload,
        ):
            self._on_step_cancelled(
                run_id=run_id,
                attempt_id=attempt_id,
                step_execution_id=step_execution_id,
                reason=reason,
            )

    def _on_step_cancelled(
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
        payload = {"runId": run_id, "status": status}
        with self._projection(
            f"run.finished:{run_id}:{status}",
            "run.finished",
            run_id,
            payload,
        ):
            self._on_run_finished(run_id, status)

    def on_run_superseded(
        self,
        run_id: str,
        new_run_id: str,
        patch_id: str,
    ) -> None:
        payload = {
            "runId": run_id,
            "newRunId": new_run_id,
            "patchId": patch_id,
        }
        with self._projection(
            f"run.superseded:{run_id}:{patch_id}",
            "run.superseded",
            run_id,
            payload,
        ):
            self._on_run_superseded(run_id)

    def _on_run_superseded(self, run_id: str) -> None:
        run = self._run(run_id)
        if run.status is RunStatus.SUPERSEDED:
            return
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise IdentityConflictError("terminal WorkflowRunV2 cannot be superseded")
        self.lifecycle_service.finish_run(run_id, RunStatus.SUPERSEDED)

    def _on_run_finished(self, run_id: str, status: str) -> None:
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
        self._ensure_blueprint_relations(
            blueprint,
            wkn_blueprint,
            task_node_bindings,
        )
        return blueprint

    def _ensure_blueprint_relations(
        self,
        blueprint: AcgBlueprint,
        wkn_blueprint: WknBlueprintSpec,
        task_node_bindings: Mapping[TaskNodeId, str],
    ) -> None:
        """幂等补齐 Blueprint 关系，供中断后的投影日志重放。"""
        for task_node_id, acg_node_id in task_node_bindings.items():
            existing = self.repositories.task_node_bindings.find_for_acg_node(
                acg_node_id,
                blueprint.blueprint_id,
            )
            if existing:
                if len(existing) != 1 or existing[0].task_node_id != task_node_id:
                    raise IdentityConflictError(
                        "Blueprint ACG node already has another primary TaskNode binding"
                    )
                continue
            self.repositories.task_node_bindings.add(TaskNodeBinding(
                taskNodeId=task_node_id,
                blueprintId=blueprint.blueprint_id,
                acgNodeId=acg_node_id,
            ))
        existing_edges = {
            (
                item.source_node_id,
                item.target_node_id,
                item.relation_type,
            )
            for item in self.repositories.blueprint_node_bindings.list_for_blueprint(
                blueprint.blueprint_id
            )
        }
        for edge in wkn_blueprint.edges:
            relation = _EDGE_RELATIONS.get(edge.edge_type)
            if relation is None:
                continue
            if (edge.source_id, edge.target_id, relation) in existing_edges:
                continue
            self.repositories.blueprint_node_bindings.add(BlueprintNodeBinding(
                blueprintId=blueprint.blueprint_id,
                sourceNodeId=edge.source_id,
                targetNodeId=edge.target_id,
                relationType=relation,
            ))

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
        task_node_bindings: Mapping[TaskNodeId, str],
        *,
        plan_version: int,
    ) -> AcgBlueprint:
        step_ids = {step.node_id for step in wkn_blueprint.step_nodes()}
        if set(task_node_bindings.values()) != step_ids:
            raise IdentityConflictError(
                "WKN Blueprint requires explicit TaskNode binding for every executable node"
            )
        graph = wkn_blueprint.model_dump(by_alias=True, mode="json")
        existing_blueprints = self.repositories.blueprints.list_for_task(task_id)
        for blueprint in existing_blueprints:
            if blueprint.graph == graph:
                self._ensure_blueprint_relations(
                    blueprint,
                    wkn_blueprint,
                    task_node_bindings,
                )
                return blueprint
        version = max((item.version for item in existing_blueprints), default=0) + 1
        return self.register_blueprint(
            task_id=task_id,
            version=version,
            wkn_blueprint=wkn_blueprint,
            task_node_bindings=task_node_bindings,
            metadata={
                "plannerPlanVersion": plan_version,
                "wknSourceGraphVersion": wkn_blueprint.version,
            },
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

    @contextmanager
    def _projection(
        self,
        event_id: str,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ):
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        event = LifecycleProjectionEvent(
            eventId=event_id,
            eventType=event_type,
            aggregateId=aggregate_id,
            payload=payload,
            payloadHash=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )
        self.repositories.projection_events.begin(event)
        try:
            yield
        except Exception as exc:
            self.repositories.projection_events.mark_failed(event_id, str(exc))
            raise
        else:
            self.repositories.projection_events.mark_applied(event_id)

    def replay_unapplied(self, *, limit: int = 200) -> dict[str, int]:
        """按持久化安全载荷重放失败或中断的身份投影。"""
        events = self.repositories.projection_events.list_unapplied(limit=limit)
        applied = 0
        failed = 0
        for event in events:
            try:
                self._replay_event(event.event_type, event.payload)
            except Exception:
                failed += 1
            else:
                applied += 1
        return {"examined": len(events), "applied": applied, "failed": failed}

    def apply_lifecycle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Apply one event already admitted by the Identity Inbox."""
        self._replay_event(event_type, payload)

    def _replay_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "task.created":
            task = SimpleNamespace(
                task_id=payload["taskId"],
                title=payload["goal"],
                domain=payload["domain"],
                intent=payload["intent"],
                input={
                    "taskGoal": payload["goal"],
                    "description": payload.get("description", ""),
                    "authenticatedUserId": payload["userId"],
                    **(
                        {"authenticatedTenantId": payload["tenantId"]}
                        if payload.get("tenantId")
                        else {}
                    ),
                },
            )
            self.on_task_created(task)
            return
        if event_type == "run.prepared":
            task = SimpleNamespace(task_id=payload["taskId"])
            run = SimpleNamespace(
                run_id=payload["runId"],
                workflow_id=payload["workflowId"],
                execution_state=payload.get("runProjection") or {},
            )
            self.on_run_prepared(
                task,
                run,
                WknBlueprintSpec.model_validate(payload["blueprint"]),
                TaskPlan.model_validate(payload["taskPlan"]),
                tuple(
                    TaskNodeImplementationBinding.model_validate(item)
                    for item in payload["taskNodeBindings"]
                ),
            )
            return
        if event_type == "run.snapshot":
            self.on_run_snapshot(
                payload["runId"],
                payload.get("projection") or payload.get("executionState") or {},
            )
            return
        if event_type == "graph.patch.prepared":
            task = SimpleNamespace(task_id=payload["taskId"])
            old_run = SimpleNamespace(run_id=payload["oldRunId"])
            new_run = SimpleNamespace(
                run_id=payload["newRunId"],
                workflow_id=payload["workflowId"],
                execution_state=payload.get("executionState") or {},
            )
            self.on_graph_patch_prepared(
                task,
                old_run,
                new_run,
                WknBlueprintSpec.model_validate(payload["blueprint"]),
                TaskPlan.model_validate(payload["taskPlan"]),
                tuple(
                    TaskNodeImplementationBinding.model_validate(item)
                    for item in payload["taskNodeBindings"]
                ),
                payload["patchId"],
            )
            return
        if event_type == "blueprint.revised":
            self.on_blueprint_revised(
                SimpleNamespace(
                    run_id=payload["runId"],
                    task_id=payload["taskId"],
                ),
                WknBlueprintSpec.model_validate(payload["blueprint"]),
                (
                    TaskPlanPatch.model_validate(payload["taskPlanPatch"])
                    if payload.get("taskPlanPatch") is not None
                    else None
                ),
                (
                    TaskNodeBindingPatch.model_validate(payload["taskNodeBindingPatch"])
                    if payload.get("taskNodeBindingPatch") is not None
                    else None
                ),
            )
            return
        if event_type == "attempt.ensured":
            run = SimpleNamespace(run_id=payload["runId"], task_id=payload["taskId"])
            self._ensure_attempt(
                run, payload["stepId"], int(payload["attemptNumber"]), payload.get("attemptId")
            )
            return
        if event_type == "resource.bound":
            self.on_resource_bound(
                attempt_id=payload["attemptId"],
                binding=WknExecutionBinding.model_validate(payload["binding"]),
                agent_id=payload["agentId"],
                model_id=payload["modelId"],
            )
            return
        if event_type == "step.started":
            self._on_step_started(
                run_id=payload["runId"],
                attempt_id=payload["attemptId"],
                step_id=payload["stepId"],
                step_execution_id=payload.get("stepExecutionId"),
            )
            return
        if event_type == "step.succeeded":
            self.on_step_succeeded(
                run_id=payload["runId"],
                attempt_id=payload["attemptId"],
                step_execution_id=payload["stepExecutionId"],
                result=payload["result"],
            )
            return
        if event_type in {"step.failed", "step.cancelled"}:
            handler = (
                self.on_step_failed
                if event_type == "step.failed"
                else self.on_step_cancelled
            )
            handler(
                run_id=payload["runId"],
                attempt_id=payload["attemptId"],
                step_execution_id=payload["stepExecutionId"],
                reason=payload["reason"],
            )
            return
        if event_type == "run.finished":
            self.on_run_finished(payload["runId"], payload["status"])
            return
        if event_type == "run.superseded":
            self.on_run_superseded(
                payload["runId"],
                payload["newRunId"],
                payload["patchId"],
            )
            return
        raise ValueError(f"unsupported lifecycle projection event: {event_type}")

    @staticmethod
    def _safe_projection_result(result: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            key: result[key]
            for key in (
                "commitId",
                "outputRef",
                "outputSummary",
                "contextRef",
                "memoryRef",
                "traceRef",
                "auditDecisionRef",
                "provenanceEvents",
                "nodeExecution",
                "communicationRefs",
                "evidenceRefs",
            )
            if result.get(key) is not None
        }
        return allowed

    @staticmethod
    def _safe_run_projection(run: Any) -> dict[str, Any]:
        state = dict(getattr(run, "execution_state", {}) or {})
        allowed = {
            "activeStepIds",
            "blackboardSnapshots",
            "checkpointId",
            "communicationUsage",
            "compiledPackageBlueprintHash",
            "compiledPackageChecksum",
            "compiledPackageId",
            "compiledPackageVersion",
            "consensusResults",
            "contextRefs",
            "controlFrames",
            "debateSessions",
            "graphPatchRefs",
            "loopIterations",
            "loopPaths",
            "memoryRefs",
            "outputRefs",
            "parentRunId",
            "provenanceRefs",
            "recoveryOutcome",
            "schedulingDecisions",
            "sourcePatchId",
            "supersedesRunId",
            "supersededByRunId",
            "traceRefs",
        }
        return {key: state[key] for key in allowed if state.get(key) is not None}

    @classmethod
    def _identity_run_metadata(cls, run: Any) -> dict[str, Any]:
        projection = cls._safe_run_projection(run)
        immutable = {
            key: projection.pop(key)
            for key in (
                "compiledPackageId",
                "compiledPackageChecksum",
                "compiledPackageVersion",
                "compiledPackageBlueprintHash",
                "parentRunId",
                "supersedesRunId",
                "sourcePatchId",
            )
            if key in projection
        }
        return {
            **immutable,
            **({"executionProjection": projection} if projection else {}),
        }

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
