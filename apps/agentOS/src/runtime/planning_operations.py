"""Confirmed operator intents routed through existing Runtime authorities."""

from copy import deepcopy
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.runtime_planning import RuntimePlanningState, RuntimeUserInput, successor_planning_state
from contracts.workflow import MissionRecordState, RunRecordState, WorkflowStatus, utc_now
from runtime.review import ReviewConflictError
from runtime.dependencies import stable_revision
from runtime.state_persistence import acg_execution_state_from_run
from support.run_execution_fence import acquire_run_fence


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

    def _assert_current_run_admission(self, run):
        """An operator can recover only its already admitted formal execution."""
        runtime = self.runtime
        authority = runtime.execution_permit_authority
        dispatch = getattr(runtime, "execution_dispatch_store", None)
        semantic = runtime.mission_semantic_service
        principal = runtime.semantic_principal_provider() if runtime.semantic_principal_provider else None
        if (not run.execution_state.get("executionPermitId") or authority is None or dispatch is None
                or semantic is None or principal is None):
            raise ValueError("current-run recovery requires formal Permit and accepted Dispatch authority")
        if (authority.runtime is not runtime or dispatch.db_path != runtime.workflow_store.db_path.resolve()
                or authority.store.db_path != runtime.workflow_store.db_path.resolve()):
            raise ValueError("recovery authorities are detached from the current execution ledger")
        mission = runtime.workflow_store.get_mission(run.mission_id)
        if (run.record_state != RunRecordState.ACTIVE or mission.record_state != MissionRecordState.ACTIVE
                or run.status == WorkflowStatus.SUPERSEDED or run.execution_state.get("supersededByRunId")):
            raise ValueError("superseded or deleted Run cannot be recovered")
        semantic.require_write_access(principal, run.mission_id)
        with dispatch.connection() as conn:
            dispatch.assert_admitted(conn, run, principal)
        return authority

    def assert_current_run_recovery(self, run, step_id=None):
        """Read-only validation shared by previews, offers and recovery commands."""
        from runtime.permit_recovery import interrupted_step_ids, operator_recovery_authorization
        interrupted = interrupted_step_ids(run)
        selected = step_id or (interrupted[0] if interrupted else None)
        authorization = operator_recovery_authorization(self.runtime, run, selected,
            "recovery-preview", str(run.runtime_revision)) if selected else None
        self._assert_current_run_admission(run).assert_recoverable(run, operator_recovery=authorization)
        return authorization

    def prepare_current_run_recovery(self, run_id, step_id, **kwargs):
        with self.runtime.run_lock_manager.lock_for(run_id):
            return self._prepare_current_run_recovery(run_id, step_id, **kwargs)

    def _prepare_current_run_recovery(self, run_id, step_id, *, expected_runtime_revision,
                                      idempotency_key, idempotency_fingerprint, reason):
        """The caller holds the Run lock; retain the OS fence through preparation."""
        runtime = self.runtime
        authority = runtime.execution_permit_authority
        if authority is None:
            raise ValueError("current-run recovery requires formal Permit authority")
        with acquire_run_fence(authority.store.db_path, run_id):
            run = runtime.workflow_store.get_run(run_id)
            self._assert_current_run_admission(run)
            requests = run.execution_state.get("inPlaceRetryRequests") or {}
            if idempotency_key in requests:
                if requests[idempotency_key] != idempotency_fingerprint:
                    raise ValueError("idempotency key conflicts with the in-place retry request")
                return run
            if expected_runtime_revision is None:
                raise ValueError("current-run recovery requires expectedRuntimeRevision")
            # Policy revocation and the new retry checkpoint share a synchronous
            # admission boundary; no network call or await occurs under this lock.
            with runtime.workflow_store.task_operator_policy_lock(run.mission_id):
                from runtime.permit_recovery import operator_recovery_authorization
                authorization = operator_recovery_authorization(runtime, run, step_id,
                    idempotency_key, idempotency_fingerprint)
                authority.assert_recoverable(run, operator_recovery=authorization)
                return runtime.runtime_recovery_coordinator.prepare_single_step_retry(
                    run_id, step_id, reason=reason, expected_runtime_revision=expected_runtime_revision,
                    idempotency_key=idempotency_key, idempotency_fingerprint=idempotency_fingerprint,
                    reuse_source_run=True, operator_recovery=authorization,
                )

    def _rerun_replans(self) -> bool:
        return (self.runtime.mission_semantic_service is not None
                or self.runtime.planning_commit_authority is not None)

    def rerun_scope(self, run):
        """A full replay reuses no results and freezes today's authorized environment."""
        from support.acg.schema import RuntimeBlueprintSpec

        runtime = self.runtime
        resolver = runtime.plugin_scope_resolver
        enabled = resolver.resolve_enabled_plugin_ids(list(run.enabled_plugin_ids),
            workflow_id=run.workflow_id, domain=run.domain, intent="")
        scope = resolver.build_scope(enabled)
        workflow = runtime.workflow_registry.get(run.workflow_id, allowed_workflow_ids=scope.workflow_ids)
        if self._rerun_replans():
            authority = getattr(runtime, "workspace_authority", None)
            if authority is not None and "workspaceBinding" in run.input:
                authority.resolve(run)
            return scope
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
        fresh_rerun = intent.kind == "rerun" and self._rerun_replans()
        if run.runtime_engine != "acg" or (not fresh_rerun and not run.execution_state.get("taskPlan")):
            raise ValueError("task operations require a persisted ACG TaskPlan")
        step_id = intent.step_id
        current_recovery = intent.kind == "recover" and bool(run.execution_state.get("executionPermitId"))
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
            execute, reuse = [], []
        elif intent.kind == "rerun":
            if run.status not in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}:
                raise ValueError("再次运行需要一个已结束且未被替换的任务")
            execute, reuse = ([] if fresh_rerun else [s.step_id for s in run.steps]), []
            scope = self.rerun_scope(run)
        else:
            runtime._workflow_for_run(run)
            from runtime.permit_recovery import is_failed_planner_recovery
            if intent.kind == "recover" and run.status != WorkflowStatus.FAILED and not (current_recovery and is_failed_planner_recovery(run)):
                raise ValueError("失败恢复需要已结束的失败任务；暂停中的任务请回答问题或提交补充要求")
            if intent.kind == "recover" and not step_id:
                from runtime.permit_recovery import interrupted_step_ids
                candidates = (interrupted_step_ids(run) if current_recovery else
                              [s.step_id for s in run.steps if s.status.value == "failed"])
                if not candidates or not current_recovery and len(candidates) != 1:
                    raise ValueError("请明确选择一个失败或中断节点")
                step_id = candidates[0]
            recovery_authorization = self.assert_current_run_recovery(run, step_id) if current_recovery else None
            runtime.runtime_recovery_coordinator.prepare_single_step_retry(
                run.run_id, step_id, validate_only=True,
                reuse_source_run=current_recovery,
                restart_from_step=intent.kind == "rerun_node",
                **({"operator_recovery": recovery_authorization} if current_recovery else {}),
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
                **({"retryMode": "current_run"} if current_recovery else {}),
                **({"planningMode": "fresh"} if fresh_rerun else {}),
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
            run = store.get_run(run_id)
            current_recovery = action["kind"] == "recover" and action.get("retryMode") == "current_run"
            if current_recovery:
                self._assert_current_run_admission(run)
            receipt = store.get_copilot_exchange(run_id, receipt_id)
            if receipt:
                return receipt
            existing = store.find_run_by_idempotency_key(key)
            in_place = (run.execution_state.get("inPlaceRetryRequests") or {}).get(key) if current_recovery else None
            if in_place is not None:
                if in_place != digest:
                    raise ReviewConflictError("operation idempotency conflict")
                target = run
            elif existing is None:
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
                    fresh = action.get("planningMode") == "fresh"
                    if fresh:
                        for field in ("acgBlueprint", "taskPlan", "taskBindings"):
                            task_input.pop(field, None)
                    else:
                        task_input.update(acgBlueprint=deepcopy(run.acg_blueprint),
                            taskPlan=deepcopy(run.execution_state["taskPlan"]),
                            taskBindings=deepcopy(run.execution_state["taskBindings"]))
                    _, target = runtime.prepare_run(run.mission_id, workflow_id=run.workflow_id, review_mode=run.review_mode,
                        idempotency_key=key, idempotency_fingerprint=digest, parent_run_id=run_id, rerun_reason="copilot_rerun",
                        enabled_plugin_ids=list(run.enabled_plugin_ids), input_override=task_input,
                        execution_scope_override=scope, defer_acg_planning=fresh, persist_run=False)
                    if not fresh:
                        target.execution_state["planningLoop"] = successor_planning_state(
                            run.execution_state.get("planningLoop") or {}, store.list_planning_inputs(run_id))
                    store.save_run(target)
                    runtime._flush_identity_outbox(raise_on_failure=False)
                else:
                    if current_recovery:
                        target = self._prepare_current_run_recovery(run_id, action["stepId"],
                            expected_runtime_revision=request.expected_revision, idempotency_key=key,
                            idempotency_fingerprint=digest, reason="confirmed_operator_request")
                    else:
                        target = runtime.runtime_recovery_coordinator.prepare_single_step_retry(run_id, action["stepId"],
                            expected_runtime_revision=request.expected_revision, idempotency_key=key, idempotency_fingerprint=digest,
                            restart_from_step=action["kind"] == "rerun_node", reason="confirmed_operator_request")
            else:
                if existing.idempotency_fingerprint != digest:
                    raise ReviewConflictError("operation idempotency conflict")
                target = existing
            receipt = {"operationId": receipt_id, "user": "", "assistant": "补充要求已保存，将由 Planner 在执行边界重新决策。" if action["kind"] == "user_input"
                else "已在当前运行准备恢复，将保留已提交的节点结果。" if current_recovery
                else "已创建新的运行，原运行记录已保留。", "createdAt": utc_now().isoformat(),
                "observedRevision": target.runtime_revision, "permission": request.permission,
                "receipt": {"proposalId": request.proposal_id, "runId": target.run_id, "kind": action["kind"],
                    "status": "queued", "executeStepIds": action["executeStepIds"], "reusedStepIds": action["reusedStepIds"]}}
            store.save_copilot_exchange(run_id, receipt_id, receipt)
            return receipt
