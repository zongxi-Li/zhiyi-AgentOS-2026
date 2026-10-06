"""Confirmed operator intents routed through existing Runtime authorities."""

from copy import deepcopy
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.runtime_planning import RuntimePlanningState, RuntimeUserInput, successor_planning_state
from contracts.workflow import WorkflowStatus, utc_now
from runtime.review import ReviewConflictError
from runtime.dependencies import stable_revision
from runtime.state_persistence import acg_execution_state_from_run


class TaskOperationIntent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    kind: Literal["rerun", "rerun_node", "recover", "user_input"]
    step_id: str | None = Field(default=None, alias="stepId", min_length=1, max_length=200)

    @model_validator(mode="after")
    def target(self):
        if self.kind == "rerun_node" and not self.step_id:
            raise ValueError("node rerun requires an exact stepId")
        if self.kind in {"rerun", "user_input"} and self.step_id:
            raise ValueError("this operation cannot select a step")
        return self


class TaskOperationPreviewRequest(TaskOperationIntent):
    operation_id: str = Field(alias="operationId", min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=4000)
    permission: Literal["read_only", "task_collaboration"]


class TaskOperationApplyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    proposal_id: str = Field(alias="proposalId", min_length=1, max_length=128)
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    permission: Literal["read_only", "task_collaboration"]


class RuntimeTaskOperations:
    def __init__(self, runtime):
        self.runtime = runtime

    def check_permission(self, run, permission="task_collaboration"):
        if permission == "task_collaboration" and self.runtime.workflow_store.get_task_copilot_permission(run.mission_id) != "task_collaboration":
            raise ReviewConflictError("当前任务为仅对话权限，请先修改任务权限")

    def rerun_scope(self, run):
        """A full replay reuses no results and freezes today's authorized environment."""
        from support.acg.schema import RuntimeBlueprintSpec

        runtime = self.runtime
        resolver = runtime.plugin_scope_resolver
        enabled = resolver.resolve_enabled_plugin_ids(list(run.enabled_plugin_ids),
            workflow_id=run.workflow_id, domain=run.domain, intent="")
        scope = resolver.build_scope(enabled)
        workflow = runtime.workflow_registry.get(run.workflow_id, allowed_workflow_ids=scope.workflow_ids)
        blueprint = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)
        missing = {s.capability for s in blueprint.step_nodes() if s.capability} - set(scope.capability_ids)
        if missing:
            raise ValueError("原计划能力已不可用，需要重新规划：" + ", ".join(sorted(missing)))
        runtime.runtime_binding_service.validate_blueprint_agents(blueprint, domain=workflow.domain or run.domain, scope=scope)
        return scope

    def preview(self, run, intent, content):
        if not content.strip():
            raise ValueError("operator request must not be blank")
        runtime = self.runtime
        self.check_permission(run)
        if run.runtime_engine != "acg" or not run.execution_state.get("taskPlan"):
            raise ValueError("task operations require a persisted ACG TaskPlan")
        step_id = intent.step_id
        if intent.kind == "user_input":
            if run.status not in {WorkflowStatus.RUNNING, WorkflowStatus.RETRYING, WorkflowStatus.WAITING_REVIEW}:
                raise ValueError("补充要求需要一个正在执行或暂停的任务")
            loop = RuntimePlanningState.model_validate(run.execution_state.get("planningLoop") or {})
            if run.status == WorkflowStatus.WAITING_REVIEW:
                review = run.execution_state.get("reviewPayload") or {}
                if review.get("subjectType") != "planner" or not loop.current or not loop.current.decision:
                    raise ValueError("节点或控制审核必须通过原有审核入口处理")
                if loop.current.decision.question:
                    raise ValueError("请先使用回答问题入口补充当前 Planner 提问")
                runtime.runtime_planning_wait_service.restore_barrier(run, loop.current.observation_id)
            input_ids = {(i.source_run_id, i.operation_id) for i in loop.user_inputs}
            input_ids.update((i["sourceRunId"], i["operationId"]) for i in runtime.workflow_store.list_planning_inputs(run.run_id))
            if len(input_ids) >= 32:
                raise ValueError("operator input budget exhausted")
            execute, reuse = [], []
        elif intent.kind == "rerun":
            if run.status not in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}:
                raise ValueError("原样重跑需要一个已结束且未被替换的任务")
            execute, reuse = [s.step_id for s in run.steps], []
            scope = self.rerun_scope(run)
        else:
            runtime._workflow_for_run(run)
            if intent.kind == "recover" and run.status != WorkflowStatus.FAILED:
                raise ValueError("失败恢复需要已结束的失败任务；暂停中的任务请回答问题或提交补充要求")
            if intent.kind == "recover" and not step_id:
                failed = [s.step_id for s in run.steps if s.status.value == "failed"]
                if len(failed) != 1:
                    raise ValueError("请明确选择一个失败节点")
                step_id = failed[0]
            runtime.runtime_recovery_coordinator.prepare_single_step_retry(
                run.run_id, step_id, validate_only=True,
                restart_from_step=intent.kind == "rerun_node",
            )
            state = acg_execution_state_from_run(run)
            # Validate commit/audit lineage before reusing anything, including
            # outputs inherited from earlier successor Runs.
            observation = runtime.runtime_planning_coordinator.observe(run, state, "resume")
            if intent.kind == "rerun_node":
                from components.executor import ACGGraphCompiler
                from contracts.compiled_acg import load_compiled_acg_package
                from support.acg.schema import RuntimeBlueprintSpec
                package = load_compiled_acg_package(run.execution_state["compiledACGPackage"])
                graph = ACGGraphCompiler().compile(RuntimeBlueprintSpec.model_validate(run.acg_blueprint),
                    run_id=run.run_id, package=package)
                cut = runtime.runtime_recovery_coordinator.node_rerun_cut(graph, package, step_id)
                execute = [s.step_id for s in run.steps if s.step_id in cut or s.step_id not in state.completed_step_ids]
                reuse = [s.step_id for s in run.steps if s.step_id in state.completed_step_ids and s.step_id not in cut]
            else:
                reuse = list(state.completed_step_ids)
                execute = [s.step_id for s in run.steps if s.step_id not in {*reuse, *state.skipped_step_ids}]
            if any(f"review_unresolved:{s}" in observation.completion_blockers for s in reuse):
                raise ValueError("不能复用尚未批准的节点结果")
        return {"kind": intent.kind, "stepId": step_id, "expectedRevision": run.runtime_revision,
                **({"capabilityCatalogRevision": scope.capability_catalog_revision,
                    "executionScopeRevision": stable_revision(scope.model_dump(by_alias=True, mode="json")),
                    "executionEnvironmentChanged": scope != run.execution_scope} if intent.kind == "rerun" else {}),
                "executeStepIds": execute, "reusedStepIds": reuse, "content": content}

    async def apply(self, run_id, request):
        runtime, store = self.runtime, self.runtime.workflow_store
        if request.permission != "task_collaboration":
            raise ValueError("仅对话权限不能执行任务操作")
        async with runtime.run_lock_manager.lock_for(run_id):
            self.check_permission(store.get_run(run_id))
            proposal = store.get_copilot_exchange(run_id, request.proposal_id)
            if not proposal or not proposal.get("action") or proposal.get("permission") != "task_collaboration":
                raise ReviewConflictError("没有可确认的任务操作方案")
            action = proposal["action"]
            if request.expected_revision != action["expectedRevision"]:
                raise ReviewConflictError("确认版本与方案不一致")
            digest = hashlib.sha256(f"{run_id}:{request.proposal_id}".encode()).hexdigest()
            key = f"copilot-action:{digest}"
            receipt_id = f"receipt:{digest}"
            receipt = store.get_copilot_exchange(run_id, receipt_id)
            if receipt:
                return receipt
            existing = store.find_run_by_idempotency_key(key)
            run = store.get_run(run_id)
            if existing is None:
                # Pending operator input already saved before a lost response is
                # an accepted operation even if the Run has since progressed.
                submitted = next((i for i in store.list_planning_inputs(run_id) if i["operationId"] == key), None)
                if submitted is None:
                    if run.runtime_revision != request.expected_revision:
                        raise ReviewConflictError("任务状态已变化，请刷新操作方案")
                    current = self.preview(run, TaskOperationIntent(kind=action["kind"], stepId=action["stepId"]), action["content"])
                    if current != action:
                        raise ReviewConflictError("操作影响范围已变化，请刷新方案")
                if action["kind"] == "user_input":
                    store.save_planning_input(run_id, key, RuntimeUserInput(sourceRunId=run_id, operationId=key,
                        content=action["content"], submittedAt=utc_now()).model_dump(by_alias=True, mode="json"))
                    # The inbox is independent of the running snapshot. No
                    # concurrent node result can overwrite this accepted input.
                    runtime.runtime_planning_wait_service.prepare(run)
                    target = run
                elif action["kind"] == "rerun":
                    scope = self.rerun_scope(run)
                    if stable_revision(scope.model_dump(by_alias=True, mode="json")) != action.get("executionScopeRevision"):
                        raise ReviewConflictError("执行环境已变化，请重新准备重跑方案")
                    task_input = deepcopy(run.input)
                    task_input.update(acgBlueprint=deepcopy(run.acg_blueprint), taskPlan=deepcopy(run.execution_state["taskPlan"]),
                        taskBindings=deepcopy(run.execution_state["taskBindings"]))
                    _, target = runtime.prepare_run(run.mission_id, workflow_id=run.workflow_id, review_mode=run.review_mode,
                        idempotency_key=key, idempotency_fingerprint=digest, parent_run_id=run_id, rerun_reason="copilot_rerun",
                        enabled_plugin_ids=list(run.enabled_plugin_ids), input_override=task_input,
                        execution_scope_override=scope, persist_run=False)
                    target.execution_state["planningLoop"] = successor_planning_state(run.execution_state.get("planningLoop") or {}, store.list_planning_inputs(run_id))
                    store.save_run(target)
                    runtime._flush_identity_outbox(raise_on_failure=False)
                else:
                    target = runtime.runtime_recovery_coordinator.prepare_single_step_retry(run_id, action["stepId"],
                        expected_runtime_revision=request.expected_revision, idempotency_key=key, idempotency_fingerprint=digest,
                        restart_from_step=action["kind"] == "rerun_node", reason="confirmed_operator_request")
            else:
                if existing.idempotency_fingerprint != digest:
                    raise ReviewConflictError("operation idempotency conflict")
                target = existing
            receipt = {"operationId": receipt_id, "user": "", "assistant": "补充要求已保存，将由 Planner 在执行边界重新决策。" if action["kind"] == "user_input"
                else "已创建新的运行，原运行记录已保留。", "createdAt": utc_now().isoformat(),
                "observedRevision": target.runtime_revision, "permission": request.permission,
                "receipt": {"proposalId": request.proposal_id, "runId": target.run_id, "kind": action["kind"],
                    "status": "queued", "executeStepIds": action["executeStepIds"], "reusedStepIds": action["reusedStepIds"]}}
            store.save_copilot_exchange(run_id, receipt_id, receipt)
            return receipt
