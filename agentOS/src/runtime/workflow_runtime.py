"""AgentOS Core 的正式运行时文件，延续原 core.workflow_runtime 的实现并承载任务、工作流、审核和恢复入口。"""


from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import logging
import os
import secrets
from time import monotonic
from typing import Callable, Mapping, Optional
from uuid import uuid4

from service.agents import AgentRegistry
from support.acg.models import (
    ACGBlueprint,
    promote_workflow_to_acg,
)
from components.auditor.governance.evaluation import WorkflowEvaluator
from components.task_manager.store import WorkflowRegistry
from components.auditor.governance.review import ReviewManager
from components.task_manager.state_machine import StateMachine
from components.task_manager.service import TaskManager
from components.auditor.governance.trace import TraceStore
from components.auditor.decision_store import DecisionStore, SQLiteDecisionStore
from components.communicator import CommunicationBroker, CommunicatorService
from components.communicator.provenance import ProvenanceLedger
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor import (
    ACGExecutionState,
    ACGGraphCompiler,
    ACGNodeRunner,
    ExecutionOrphanCleaner,
    ExecutionValueStore,
    SQLiteExecutionValueStore,
    GraphPatchConflictError,
    GraphPatchService,
)
from components.memory import MemoryService
from components.memory.store import SQLiteMemoryStore
from contracts.memory import MemoryPolicy, MemoryType
from components.resource.directory import ResourceDirectory, ResourceNotFoundError
from components.recovery.checkpoint import (
    ACGCheckpointStore,
    ExecutionInterrupt,
    ExecutionResumeCommand,
)
from adapters.agent_invocation import AgentInvocationAdapter
from adapters.audited_tool_runtime import AuditedToolRuntime
from adapters.guarded_model import GuardedModelRuntime
from adapters.guarded_tool import GuardedToolRuntime
from adapters.model_compatibility import ModelCompatibilityRegistry, ModelProviderAdapter
from adapters.model_runtime import RegisteredModelRuntime
from adapters.tool_adapter import configured_tool_runtime
from contracts.workflow import (
    AgentTask,
    Checkpoint,
    EvaluationRun,
    ReviewDecision,
    ReviewDecisionType,
    ReviewRecord,
    StepStatus,
    TraceEvent,
    TraceEventType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
    RunExecutionScope,
    utc_now,
)
from contracts.execution import WorkflowProgressPhase
from contracts.recovery import GraphPatch, GraphPatchRef, GraphPatchResult
from contracts.workflow import GraphRef
from runtime.compatibility import GLOBAL_RUN_LOCK_MANAGER, RunLockManager
from runtime.execution_migration import ExecutionEngineMigratingError
from support.acg.models import build_default_capability_catalog
from support.acg.models import CapabilityCatalog
from components.planner.algorithms import (
    PLANNER_ALGORITHM_VERSION,
    normalize_planning_diversity,
    normalize_planning_seed,
)
from runtime.dependencies import PluginScopeError, PluginScopeResolver
from support.packs.registry import register_installed_packs
from adapters.model.native import register_native_runtime
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.stores.workflow_store import WorkflowStore


logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
}

_LIFECYCLE_MESSAGES = {
    WorkflowProgressPhase.UNDERSTANDING: "任务已接受，正在准备 ACG 规划",
    WorkflowProgressPhase.PLANNING: "正在规划 ACG 执行路径",
    WorkflowProgressPhase.GRAPH_BUILDING: "正在构建 ACG 拓扑",
    WorkflowProgressPhase.EXECUTING: "正在执行 ACG 节点",
    WorkflowProgressPhase.RECOVERY: "正在恢复 ACG 执行",
    WorkflowProgressPhase.REVIEW: "正在等待人工审核",
    WorkflowProgressPhase.COMPLETED: "ACG 工作流执行完成",
    WorkflowProgressPhase.FAILED: "ACG 工作流执行失败",
    WorkflowProgressPhase.CANCELLED: "ACG 工作流已取消",
}

_ERROR_UNSET = object()
ExecutionAdapterFactory = Callable[..., object]


class ReviewConflictError(ValueError):
    """表示客户端读取审核对象后，运行或步骤已被其他操作更新。"""


class WorkflowRuntime:
    """AgentOS Core 的工作流运行时，串联任务、Trace、审核与恢复流程。"""

    def __init__(
        self,
        *,
        agent_registry: Optional[AgentRegistry] = None,
        workflow_registry: Optional[WorkflowRegistry] = None,
        workflow_store: Optional[WorkflowStore] = None,
        trace_store: Optional[TraceStore] = None,
        checkpoint_store: Optional[object] = None,
        execution_value_store: ExecutionValueStore | None = None,
        memory_store: object | None = None,
        provenance_store: SQLiteProvenanceStore | None = None,
        decision_store: DecisionStore | None = None,
        tool_runtime: object | None = None,
        review_manager: Optional[ReviewManager] = None,
        evaluator: Optional[WorkflowEvaluator] = None,
        task_manager: Optional[TaskManager] = None,
        execution_adapter_factories: Optional[Mapping[str, ExecutionAdapterFactory]] = None,
        run_lock_manager: Optional[RunLockManager] = None,
        recovery_recipe_registry: Optional[object] = None,
        capability_catalog: CapabilityCatalog | None = None,
        resource_directory: ResourceDirectory | None = None,
        model_registry: ModelCompatibilityRegistry | None = None,
        plugin_manifests: tuple = (),
    ):
        self.agent_registry = agent_registry or AgentRegistry()
        self.workflow_registry = workflow_registry or WorkflowRegistry()
        self.capability_catalog = capability_catalog or build_default_capability_catalog()
        self.resource_directory = resource_directory or ResourceDirectory()
        # 注册表只保存应用层已创建的模型适配器；Runtime 不在内部创建网络客户端。
        # 调用方可传入 bootstrap 产生的同一实例，使启动装配与工作流执行共享路由。
        self.model_registry = model_registry or ModelCompatibilityRegistry()
        self.plugin_manifests = tuple(plugin_manifests)
        self.workflow_store = workflow_store or MemoryWorkflowStore()
        self.trace_store = trace_store or TraceStore()
        # 融合 ACG 使用独立 SQLite 检查点与正文引用仓库。检查点只保存 State 引用；
        # 输出和 ContextPack 正文保存在另一文件，进程重启后仍可安全地继续审核流程。
        self.checkpoint_store = checkpoint_store or ACGCheckpointStore()
        self.execution_value_store = execution_value_store or SQLiteExecutionValueStore(
            db_path=os.getenv("AGENTOS_EXECUTION_VALUE_DB", "data/execution_values.sqlite3")
        )
        self.orphan_cleaner = ExecutionOrphanCleaner(value_store=self.execution_value_store)
        self.memory_store = memory_store or SQLiteMemoryStore(
            db_path=os.getenv("AGENTOS_EXECUTION_MEMORY_DB", "data/execution_memory.sqlite3")
        )
        # 血缘账本与 checkpoint、正文仓库分文件保存。每次构建节点运行器前都会先
        # 重建并验证同 run 哈希链；损坏账本不会被静默绕过。
        self.provenance_store = provenance_store or SQLiteProvenanceStore(
            db_path=os.getenv("AGENTOS_PROVENANCE_DB", "data/provenance.sqlite3")
        )
        # 审计决定独立于 Trace、checkpoint 和输出正文保存。恢复时引用必须从这里
        # 重新验证 run/step 归属，不能信任检查点或节点提交中的字符串。
        self.decision_store = decision_store or SQLiteDecisionStore(
            db_path=os.getenv("AGENTOS_AUDIT_DB", "data/audit_decisions.sqlite3")
        )
        # 测试可临时设置该私有钩子，模拟进程在一个已提交边界后消失。它不属于构造
        # 参数、环境变量或公开 contracts，生产运行时始终保持 ``None``。
        self._fault_hook: Callable[[str], None] | None = None
        self.tool_runtime = tool_runtime
        self.review_manager = review_manager or ReviewManager(self.trace_store)
        self.evaluator = evaluator or WorkflowEvaluator()
        self.state_machine = StateMachine()
        self._model_runtime = None
        self.task_manager = task_manager or TaskManager(
            workflow_store=self.workflow_store,
            workflow_registry=self.workflow_registry,
            state_machine=self.state_machine,
            trace_store=self.trace_store,
        )
        self.run_lock_manager = run_lock_manager or GLOBAL_RUN_LOCK_MANAGER
        self.recovery_recipe_registry = recovery_recipe_registry
        self._runtime_adapters: dict[str, object] = {}
        self.execution_adapter_factories: dict[str, ExecutionAdapterFactory] = {
            self._normalize_runtime_engine(engine): factory
            for engine, factory in (execution_adapter_factories or {}).items()
        }
        # 认知规划引擎（懒构造）。app 层可通过 set_intent_llm 注入真实 LLM，
        # 让意图解析走 DeepSeek；未注入时规划器用启发式回退。
        self._planning_engine = None
        self._intent_llm = None

    @property
    def plugin_scope_resolver(self) -> PluginScopeResolver:
        """返回当前依赖注册表构造的插件范围解析器，不修改已冻结运行范围。"""
        return PluginScopeResolver(
            capability_catalog=self.capability_catalog,
            agent_registry=self.agent_registry,
            workflow_registry=self.workflow_registry,
            manifests=self.plugin_manifests,
        )

    def set_intent_llm(self, intent_llm) -> None:
        """注入意图解析 LLM（app 层在装配时调用）。重置已构造的规划引擎。"""
        self._intent_llm = intent_llm
        self._planning_engine = None

    def set_model_runtime(self, model_runtime) -> None:
        """注入结构化模型运行时，并统一置于超时、重试与限流保护边界内。"""
        self._model_runtime = (
            model_runtime
            if isinstance(model_runtime, GuardedModelRuntime)
            else GuardedModelRuntime(delegate=model_runtime, retries=1)
        )

    def register_model_adapter(self, adapter: ModelProviderAdapter) -> None:
        """登记应用层创建的模型适配器，不接收密钥、SDK 或网络配置。"""
        self.model_registry.register(adapter)

    @property
    def planning_engine(self):
        """延迟构造规划引擎并返回缓存实例；注入 LLM 后会由设置方法失效重建。"""
        if self._planning_engine is None:
            from components.planner.service import PlanningEngine

            self._planning_engine = PlanningEngine(
                workflow_registry=self.workflow_registry,
                agent_registry=self.agent_registry,
                capability_catalog=self.capability_catalog,
                intent_llm=self._intent_llm,
            )
        return self._planning_engine

    def register_execution_adapter(self, runtime_engine: str, factory: ExecutionAdapterFactory) -> None:
        """登记非 ACG 运行引擎适配器；空标识或覆盖策略由调用方显式负责。"""
        engine = self._normalize_runtime_engine(runtime_engine)
        if engine == "acg":
            raise ValueError(f"{engine} runtime engine is built into AgentOS Core")
        self.execution_adapter_factories[engine] = factory

    def create_task(
        self,
        title: str,
        domain: str = "general",
        intent: str = "general",
        input: Optional[dict] = None,
        security_level: str = "internal",
        priority: str = "normal",
        *,
        role_type: Optional[str] = None,
        task_type: Optional[str] = None,
        workflow_id: Optional[str] = None,
        enabled_plugin_ids: Optional[list[str]] = None,
    ) -> AgentTask:
        """校验请求、解析插件范围并创建任务；合同或插件异常会向调用方明确传播。"""
        task_domain = (role_type or domain or "general").strip()
        task_intent = (task_type or intent or "general").strip()
        resolved_plugins = self.plugin_scope_resolver.resolve_enabled_plugin_ids(
            enabled_plugin_ids,
            workflow_id=workflow_id,
            domain=task_domain,
            intent=task_intent,
        )
        scope = self.plugin_scope_resolver.build_scope(resolved_plugins)
        return self.task_manager.create_task(
            title=title,
            domain=domain,
            intent=intent,
            input=input,
            security_level=security_level,
            priority=priority,
            role_type=role_type,
            task_type=task_type,
            workflow_id=workflow_id,
            enabled_plugin_ids=enabled_plugin_ids,
            allowed_workflow_ids=scope.workflow_ids,
        )

    async def start(
        self,
        task_id: str,
        workflow_id: Optional[str] = None,
        review_mode: str = "auto",
        enabled_plugin_ids: Optional[list[str]] = None,
    ) -> WorkflowRun:
        """为任务选择工作流并启动运行；持久化和同运行互斥由内部运行锁协调。"""
        _, run = self.prepare_run(
            task_id=task_id,
            workflow_id=workflow_id,
            review_mode=review_mode,
            enabled_plugin_ids=enabled_plugin_ids,
        )
        return await self.execute_prepared_run(run.run_id)

    def prepare_run(
        self,
        task_id: str,
        workflow_id: Optional[str] = None,
        review_mode: str = "auto",
        *,
        idempotency_key: Optional[str] = None,
        idempotency_fingerprint: Optional[str] = None,
        enabled_plugin_ids: Optional[list[str]] = None,
    ) -> tuple[AgentTask, WorkflowRun]:
        """在规划或节点执行前持久化可查询运行；幂等键冲突时抛出 ``ValueError``。"""

        if idempotency_key:
            existing = self.workflow_store.find_run_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.idempotency_fingerprint != idempotency_fingerprint:
                    raise ValueError("idempotency key conflicts with the workflow start request")
                return self.task_manager.get_task(existing.task_id), existing

        task = self.task_manager.get_task(task_id)
        requested_plugins = (
            enabled_plugin_ids
            if enabled_plugin_ids is not None
            else task.enabled_plugin_ids
        )
        resolved_plugins = self.plugin_scope_resolver.resolve_enabled_plugin_ids(
            requested_plugins,
            workflow_id=workflow_id or task.recommended_workflow,
            domain=task.domain,
            intent=task.intent,
        )
        scope = self.plugin_scope_resolver.build_scope(resolved_plugins)
        workflow = self._resolve_workflow(
            task,
            workflow_id,
            allowed_workflow_ids=scope.workflow_ids,
        )
        is_acg = workflow.effective_runtime_engine == "acg"
        planning_diversity = normalize_planning_diversity(
            task.input.get("planningDiversity")
        )
        planning_seed = normalize_planning_seed(task.input.get("planningSeed"))
        if planning_diversity != "stable" and planning_seed is None:
            planning_seed = secrets.randbits(53)
        run_input = dict(task.input)
        run_input["planningDiversity"] = planning_diversity
        if planning_seed is not None:
            run_input["planningSeed"] = planning_seed
        run = WorkflowRun(
            taskId=task.task_id,
            workflowId=workflow.workflow_id,
            domain=workflow.domain,
            runtimeEngine=workflow.effective_runtime_engine,
            implementationId=workflow.effective_implementation_id,
            reviewMode=review_mode,
            input=run_input,
            lifecyclePhase=WorkflowProgressPhase.UNDERSTANDING,
            lifecycleMessage=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.UNDERSTANDING],
            idempotencyKey=idempotency_key,
            idempotencyFingerprint=idempotency_fingerprint,
            currentStepId=None if is_acg else workflow.first_step_id(),
            steps=(
                []
                if is_acg
                else [WorkflowStep.from_definition(step) for step in workflow.steps]
            ),
            enabledPluginIds=list(scope.enabled_plugin_ids),
            resolvedEnabledPluginIds=list(scope.enabled_plugin_ids),
            pluginSnapshot=list(scope.plugin_snapshots),
            capabilityCatalogRevision=scope.capability_catalog_revision,
            planningDiversity=planning_diversity,
            planningSeed=planning_seed,
            plannerAlgorithmVersion=PLANNER_ALGORITHM_VERSION,
            executionScope=scope,
            legacyPluginScope=False,
            executionState={
                **({"engineMigration": "langgraph_pending"} if is_acg else {}),
                "pluginScopeResolution": (
                    "legacy_compatibility" if requested_plugins is None else "explicit"
                ),
                "visibleCapabilityCount": len(scope.capability_ids),
                "scopeExcludedAgentCount": max(
                    0, len(tuple(self.agent_registry.all())) - len(scope.agent_ids)
                ),
                "planningDiversity": planning_diversity,
                "planningSeed": planning_seed,
                "plannerAlgorithmVersion": PLANNER_ALGORITHM_VERSION,
            },
        )
        if is_acg:
            blueprint = self._build_acg_blueprint(task, run, workflow)
            self._validate_blueprint_agents(
                blueprint,
                domain=workflow.domain or task.domain,
                scope=scope,
            )
            self._sync_run_steps_to_acg(run, blueprint)
            self._register_and_freeze_resources(
                run=run,
                workflow=workflow,
                scope=scope,
            )
            run.acg_blueprint = blueprint.model_dump(by_alias=True, mode="json")
            run.execution_state.update(
                {
                    "workflowVersion": workflow.version,
                    "graphId": blueprint.graph_id,
                    "sourceBlueprintVersion": blueprint.version,
                }
            )
        self.trace_store.append(
            run=run,
            event_type=TraceEventType.TASK_STATUS_CHANGED,
            observation="Plugin execution scope resolved",
            payload={
                "resolvedEnabledPluginIds": list(scope.enabled_plugin_ids),
                "pluginSnapshot": [
                    item.model_dump(by_alias=True, mode="json")
                    for item in scope.plugin_snapshots
                ],
                "capabilityCatalogRevision": scope.capability_catalog_revision,
                "visibleCapabilityCount": len(scope.capability_ids),
                "scopeExcludedAgentCount": run.execution_state[
                    "scopeExcludedAgentCount"
                ],
                "resolutionPolicy": run.execution_state[
                    "pluginScopeResolution"
                ],
            },
        )
        self.workflow_store.save_run(run)
        logger.info(
            "run_prepared",
            extra={
                "taskId": task.task_id,
                "runId": run.run_id,
                "workflowId": workflow.workflow_id,
                "phase": run.lifecycle_phase.value,
            },
        )
        return task, run

    async def execute_prepared_run(self, run_id: str) -> WorkflowRun:
        """执行已持久化运行并保持终态不回退；插件范围失效时安全标记失败后继续抛错。"""

        run = self.workflow_store.get_run(run_id)
        if self._normalize_runtime_engine(run.runtime_engine) == "acg":
            if run.status == WorkflowStatus.WAITING_REVIEW:
                return run
            return await self._execute_acg(run)
        if run.status in _TERMINAL_RUN_STATUSES:
            return run

        task = self.task_manager.get_task(run.task_id)
        try:
            workflow = self._workflow_for_run(run)
        except PluginScopeError as exc:
            await self.fail_run_safely(
                run.run_id,
                error_code=exc.code,
                error_message=exc.detail,
            )
            raise
        started = monotonic()
        run = self._set_run_lifecycle(
            run,
            status=WorkflowStatus.RUNNING,
            phase=WorkflowProgressPhase.PLANNING,
            message=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.PLANNING],
            set_started_at=True,
        )
        try:
            self.task_manager.mark_running(task)
            adapter = self._workflow_adapter(workflow)
            return await adapter.start(task=task, run=run, workflow=workflow)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.fail_run_safely(
                run.run_id,
                error_code="workflow_execution_failed",
                error_message=self._safe_error_message(exc),
            )
            logger.exception(
                "run_execution_failed",
                extra={"taskId": run.task_id, "runId": run.run_id, "elapsedMs": int((monotonic() - started) * 1000)},
            )
            raise

    async def _execute_acg(
        self,
        run: WorkflowRun,
        *,
        state: ACGExecutionState | None = None,
        command: ExecutionResumeCommand | None = None,
    ) -> WorkflowRun:
        """执行或续跑融合 ACG，并把图状态投影为既有运行合同。

        图、值仓库和检查点均只传递引用型状态。此方法是 Runtime 唯一的 ACG 接线点：
        通信、记忆、审计、Agent 适配由 ``ACGNodeRunner`` 组合，WorkflowRun 只保存
        生命周期、步骤状态、摘要和引用，绝不写入 Agent 的完整输出正文。
        """
        if run.status in _TERMINAL_RUN_STATUSES:
            return run
        task = self.task_manager.get_task(run.task_id)
        workflow = self._workflow_for_run(run)
        blueprint_data = run.acg_blueprint
        if not isinstance(blueprint_data, dict):
            raise ExecutionEngineMigratingError(run.run_id)
        blueprint = ACGBlueprint.model_validate(blueprint_data)
        graph = ACGGraphCompiler().compile(blueprint, run_id=run.run_id)
        execution_state = state or ACGExecutionState(
            runId=run.run_id,
            graphId=blueprint.graph_id,
            graphVersion=blueprint.version,
        )
        if execution_state.run_id != run.run_id:
            raise ValueError("execution state runId does not match workflow run")
        self._validate_acg_resume_identity(
            run=run,
            workflow=workflow,
            blueprint=blueprint,
            state=execution_state,
        )
        ledger = self.provenance_store.load_ledger(run_id=run.run_id, task_id=task.task_id)
        self._validate_acg_state_references(run=run, state=execution_state, ledger=ledger)
        runner = self._build_acg_runner(
            task=task,
            run=run,
            workflow=workflow,
            graph=graph,
            state=execution_state,
            ledger=ledger,
        )
        run.execution_state["engineMigration"] = "langgraph_fused_v1"
        run.execution_state["graphId"] = blueprint.graph_id
        run = self._set_run_lifecycle(
            run,
            status=WorkflowStatus.RUNNING,
            phase=WorkflowProgressPhase.EXECUTING,
            message=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.EXECUTING],
            set_started_at=True,
        )
        self.task_manager.mark_running(task)
        try:
            stream = (
                graph.astream(execution_state, runner)
                if command is None
                else graph.astream_after_resume(execution_state, command, runner)
            )
            async for event in stream:
                self._project_acg_event(run, execution_state, event)
            self._persist_acg_state(run, execution_state)
            run.output = self._acg_output(execution_state)
            run = self._set_run_lifecycle(
                run,
                status=WorkflowStatus.COMPLETED,
                phase=WorkflowProgressPhase.COMPLETED,
                message=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.COMPLETED],
            )
            self.task_manager.mark_completed(task)
            self.trace_store.append(run, TraceEventType.RUN_COMPLETED, observation="ACG workflow completed")
            self.workflow_store.save_run(run)
            return run
        except ExecutionInterrupt as interrupt:
            self._persist_acg_state(run, execution_state)
            checkpoint_id = self._save_acg_checkpoint(run, execution_state)
            self._persist_acg_state(run, execution_state)
            review_step_id = str(interrupt.payload.get("stepId") or execution_state.current_step_id or "")
            if review_step_id:
                step = run.get_step(review_step_id)
                step.status = StepStatus.WAITING_REVIEW
                run.current_step_id = review_step_id
            self.trace_store.append_execution_event(run, {"type": "interrupted", **interrupt.payload})
            self.trace_store.append_execution_event(run, {"type": "checkpoint_created", "checkpointId": checkpoint_id})
            run = self._set_run_lifecycle(
                run,
                status=WorkflowStatus.WAITING_REVIEW,
                phase=WorkflowProgressPhase.REVIEW,
                message=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.REVIEW],
            )
            self.task_manager.mark_waiting_review(task)
            self.workflow_store.save_run(run)
            return run
        except Exception as exc:
            await self.fail_run_safely(
                run.run_id,
                error_code="acg_execution_failed",
                error_message=self._safe_error_message(exc),
            )
            raise

    @staticmethod
    def _validate_acg_resume_identity(
        *,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
        blueprint: ACGBlueprint,
        state: ACGExecutionState,
    ) -> None:
        """恢复前校验运行、蓝图、工作流和 checkpoint 的版本身份。"""
        expected_graph_id = str(run.execution_state.get("graphId") or blueprint.graph_id)
        if state.graph_id != expected_graph_id:
            raise ValueError(
                f"checkpoint graphId {state.graph_id!r} does not match run graphId {expected_graph_id!r}"
            )
        if int(state.graph_version) != int(blueprint.version):
            raise ValueError(
                f"checkpoint graphVersion {state.graph_version} does not match blueprint version {blueprint.version}"
            )
        source_blueprint_version = run.execution_state.get("sourceBlueprintVersion")
        if source_blueprint_version is not None and int(blueprint.version) != int(source_blueprint_version):
            raise ValueError(
                "checkpoint sourceBlueprintVersion does not match persisted blueprint version"
            )
        workflow_version = run.execution_state.get("workflowVersion")
        if workflow_version is not None and str(workflow.version) != str(workflow_version):
            raise ValueError("checkpoint workflowVersion does not match persisted workflow version")

    def _validate_acg_state_references(
        self,
        *,
        run: WorkflowRun,
        state: ACGExecutionState,
        ledger: ProvenanceLedger | None = None,
    ) -> None:
        """在恢复前重验检查点的引用归属，且不读取任何输出或上下文正文。

        State 字典的键就是产生引用的步骤标识。若键、runId 或引用类别被篡改，必须在
        改变运行生命周期、创建 Agent 或追加血缘事件之前停止，避免恢复路径成为越权入口。
        """
        valid_step_ids = {step.step_id for step in run.steps}
        reference_maps = {
            "output summaries": state.output_summaries,
            "output": state.output_refs,
            "context": state.context_refs,
            "memory": state.memory_refs,
            "trace": state.trace_refs,
            "provenance": state.provenance_refs,
        }
        for reference_name, references in reference_maps.items():
            for step_id in references:
                if step_id not in valid_step_ids:
                    raise ValueError(f"unknown ACG step {step_id} in {reference_name} references")
        for step_id, output_ref in state.output_refs.items():
            self.execution_value_store.assert_reference(
                kind="output", run_id=run.run_id, step_id=step_id, reference=output_ref
            )
        for step_id, context_ref in state.context_refs.items():
            self.execution_value_store.assert_reference(
                kind="context", run_id=run.run_id, step_id=step_id, reference=context_ref
            )
        for patch_ref in state.graph_patch_refs:
            self.execution_value_store.assert_reference(
                kind="graph-patch",
                run_id=run.run_id,
                step_id="__graph__",
                reference=patch_ref,
            )
        for step_id, memory_ref in state.memory_refs.items():
            if memory_ref != "memory:none":
                MemoryService(store=self.memory_store).assert_step_ref(
                    run_id=run.run_id,
                    step_id=step_id,
                    memory_ref=memory_ref,
                )
        for step_id, trace_ref in state.trace_refs.items():
            if trace_ref != f"trace:{step_id}":
                raise ValueError(f"trace reference {trace_ref} does not belong to step {step_id}")
            if not any(
                event.event_type == TraceEventType.STEP_SUCCEEDED and event.step_id == step_id
                for event in run.trace
            ):
                raise ValueError(f"trace reference {trace_ref} has no completed trace for step {step_id}")
        active_ledger = ledger or self.provenance_store.load_ledger(
            run_id=run.run_id,
            task_id=run.task_id,
        )
        for step_id, event_ids in state.provenance_refs.items():
            for event_id in event_ids:
                active_ledger.assert_event_owner(event_id=event_id, step_id=step_id)
        review_payload = state.review_payload
        if isinstance(review_payload, dict):
            decision_ref = review_payload.get("auditDecisionRef")
            outcome = review_payload.get("auditOutcome")
            review_step_id = review_payload.get("stepId")
            if isinstance(decision_ref, str) and isinstance(outcome, str) and isinstance(review_step_id, str):
                self.decision_store.assert_decision(
                    run_id=run.run_id,
                    step_id=review_step_id,
                    decision_ref=decision_ref,
                    outcomes={outcome},
                )

    def _build_acg_runner(
        self,
        *,
        task: AgentTask,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
        graph,
        state: ACGExecutionState,
        ledger: ProvenanceLedger,
    ) -> ACGNodeRunner:
        """按冻结插件范围解析 Agent，并组装本 run 的通信、记忆与适配依赖。"""
        steps = {step.step_id: step for step in run.steps}
        allowed_agent_ids = run.execution_scope.agent_ids if run.execution_scope is not None else None
        bindings = run.execution_state.get("resourceBindings")
        if not isinstance(bindings, dict):
            raise ValueError("ACG run has no frozen resource bindings")
        agents = {
            step_id: self.agent_registry.resolve_by_id(
                str(bindings[step_id]),
                allowed_agent_ids=allowed_agent_ids,
            )
            for step_id in steps
        }
        communication_rules = tuple(
            getattr(graph.communication_manifest, "rules", ())
            if graph.communication_manifest is not None
            else ()
        )
        upstream_step_ids = {
            node_id: tuple(
                dict.fromkeys(
                    [source for source, target in graph.edges if target == node_id]
                    + [
                        rule.producer_step_id
                        for rule in communication_rules
                        if rule.consumer_step_id == node_id
                    ]
                )
            )
            for node_id in steps
        }
        allowed_tools = {
            tool_name
            for agent in agents.values()
            for tool_name in agent.profile.allowed_tools
        }
        delegate = self.tool_runtime or configured_tool_runtime()
        # 工具必须先经过 AgentOS 的授权检查，再进入统一的超时、重试、限流与安全
        # 错误映射边界。对已受保护的运行时不重复包装，避免双重重试放大副作用。
        protected_tools = (
            delegate
            if isinstance(delegate, GuardedToolRuntime)
            else GuardedToolRuntime(delegate=delegate, retries=1)
        ) if delegate is not None else None
        scoped_tools = (
            AuditedToolRuntime(delegate=protected_tools, allowed_tools=allowed_tools)
            if protected_tools is not None
            else None
        )
        # Broker 由单次图执行共享，读取后的预算计数写入引用型 State；从检查点恢复
        # 时，已消费额度会作为构造参数重新载入，不能因重启而回到零。
        communication_broker = (
            CommunicationBroker(
                manifest=graph.communication_manifest,
                value_store=self.execution_value_store,
                usage=state.communication_usage,
            )
            if graph.communication_manifest is not None
            else None
        )
        if communication_broker is not None:
            # 空图或仅根节点的运行同样必须采用统一的零值表示。否则首次执行会在
            # Broker 调用后才写入零计数，而提交重放会保留空对象，造成等价状态生成
            # 不同 checkpoint 摘要并破坏恢复幂等性。
            state.communication_usage = communication_broker.usage_snapshot()
        model_bindings = run.execution_state.get("modelBindings")
        if not isinstance(model_bindings, dict):
            raise ValueError("ACG run has no frozen model bindings")
        step_model_runtimes = {
            step_id: self._model_runtime_from_binding(model_bindings.get(step_id))
            for step_id in steps
        }
        return ACGNodeRunner(
            task=task,
            run=run,
            workflow=workflow,
            steps=steps,
            agents=agents,
            communicator=CommunicatorService(
                run_id=run.run_id,
                task_id=task.task_id,
                ledger=ledger,
            ),
            memory=MemoryService(store=self.memory_store),
            entropy_budget=(int(run.input["entropyBudget"]) if run.input.get("entropyBudget") is not None else None),
            value_store=self.execution_value_store,
            communication_modes={node_id: spec.communication_mode for node_id, spec in graph.node_specs.items() if spec.kind == "step"},
            upstream_step_ids=upstream_step_ids,
            model_runtime=self._model_runtime,
            model_runtimes={
                step_id: runtime
                for step_id, runtime in step_model_runtimes.items()
                if runtime is not None
            },
            capability_descriptors={
                step.capability: self.capability_catalog.resolve(step.capability)
                for step in steps.values()
                if step.capability
            },
            tool_runtime=scoped_tools,
            communication_broker=communication_broker,
            agent_invoker=AgentInvocationAdapter(
                registry=(self.agent_registry.scoped(allowed_agent_ids) if allowed_agent_ids is not None else self.agent_registry)
            ),
            decision_store=self.decision_store,
            fault_hook=self._fault_hook,
        )

    def _project_acg_event(self, run: WorkflowRun, state: ACGExecutionState, event: dict) -> None:
        """投影单个图事件与步骤状态；事件正文只含步骤标识、摘要或引用。"""
        event_type = event.get("type")
        commit_id = event.get("commitId")
        node_trace_batch: list[TraceEvent] = []
        if event_type == "node_completed" and isinstance(commit_id, str) and self._is_projected_commit(run, commit_id):
            # Trace 已经确认过该提交，说明上次在状态保存前中断。重放时不能再次追加
            # 步骤成功、记忆访问或通信血缘事件；图状态本身由当前 checkpoint 继续推进。
            self._persist_acg_state(run, state)
            return
        if event_type == "nodes_scheduled":
            for step_id in event.get("stepIds", []):
                step = run.get_step(str(step_id))
                step.status = StepStatus.RUNNING
                step.started_at = step.started_at or utc_now()
            run.active_step_ids = list(event.get("stepIds", []))
        elif event_type == "node_completed":
            step_id = str(event.get("stepId"))
            step = run.get_step(step_id)
            step.status = StepStatus.COMPLETED
            step.completed_at = utc_now()
            run.current_step_id = step_id
            run.completed_step_ids = list(state.completed_step_ids)
            run.active_step_ids = list(state.active_step_ids)
        elif event_type == "superstep_completed":
            checkpoint_id = self._save_acg_checkpoint(run, state)
            state.checkpoint_id = checkpoint_id
            run.execution_state["checkpointId"] = checkpoint_id
            self.trace_store.append_execution_event(
                run,
                {"type": "checkpoint_created", "checkpointId": checkpoint_id},
            )
        elif event_type == "superstep_failed":
            for step_id in event.get("failedStepIds", []):
                step = run.get_step(str(step_id))
                if step.status in {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.RETRYING}:
                    self._transition_step(step, StepStatus.FAILED)
                    step.error = "ACG superstep node failed"
            for step_id in event.get("cancelledStepIds", []):
                step = run.get_step(str(step_id))
                if step.status in {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.RETRYING}:
                    self._transition_step(step, StepStatus.CANCELLED)
                    step.error = "ACG superstep cancelled after sibling failure"
            run.active_step_ids = []
        # 条件控制节点由图在超步边界内部推进，不会产生独立的节点事件。这里根据
        # 已持久化的 skippedStepIds 补齐 WorkflowRun 的可见步骤状态，供查询、
        # 审计和取消逻辑一致地区分“未执行”与“条件明确跳过”。
        for step_id in state.skipped_step_ids:
            step = run.get_step(step_id)
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.SKIPPED_BY_CONDITION
                step.completed_at = utc_now()
        if event_type not in {"superstep_completed", "superstep_failed"}:
            if event_type == "node_completed":
                node_trace_batch.append(self.trace_store.build_execution_event(run, event))
            else:
                self.trace_store.append_execution_event(run, event)
        if event_type == "superstep_failed":
            self.trace_store.append(
                run,
                TraceEventType.STEP_FAILED,
                step_id=(event.get("failedStepIds") or [None])[0],
                observation="ACG parallel superstep failed",
                payload={
                    "failedStepIds": list(event.get("failedStepIds") or []),
                    "cancelledStepIds": list(event.get("cancelledStepIds") or []),
                },
            )
        for model_call in event.get("modelInvocations", []):
            if event_type == "node_completed":
                node_trace_batch.append(self.trace_store.build_event(
                    run,
                    event_type=TraceEventType.MODEL_CALLED,
                    step_id=event.get("stepId"),
                    observation="Model invocation metadata projected",
                    payload=dict(model_call),
                ))
            else:
                self.trace_store.append(
                    run,
                    TraceEventType.MODEL_CALLED,
                    step_id=event.get("stepId"),
                    observation="Model invocation metadata projected",
                    payload=dict(model_call),
                )
        for tool_call in event.get("toolCalls", []):
            if event_type == "node_completed":
                node_trace_batch.append(self.trace_store.build_event(
                    run,
                    event_type=TraceEventType.TOOL_CALLED,
                    step_id=event.get("stepId"),
                    observation="Tool invocation metadata projected",
                    payload=dict(tool_call),
                ))
            else:
                self.trace_store.append(
                    run,
                    TraceEventType.TOOL_CALLED,
                    step_id=event.get("stepId"),
                    observation="Tool invocation metadata projected",
                    payload=dict(tool_call),
                )
        memory_access = event.get("memoryAccess")
        if isinstance(memory_access, dict):
            if event_type == "node_completed":
                node_trace_batch.append(self.trace_store.build_event(
                    run,
                    event_type=TraceEventType.DATA_CONSUMED,
                    step_id=event.get("stepId"),
                    observation="Step memory policy applied",
                    payload=dict(memory_access),
                ))
            else:
                self.trace_store.append(
                    run,
                    TraceEventType.DATA_CONSUMED,
                    step_id=event.get("stepId"),
                    observation="Step memory policy applied",
                    payload=dict(memory_access),
                )
        # 通信读取事件来自 Broker，仅允许引用、字段名、计数与逻辑通道进入审计。
        # 即便节点事件被外部调用方伪造，也不能借此把 reason 或任何正文塞进 Trace。
        for communication_read in event.get("communicationReads", []):
            if not isinstance(communication_read, dict):
                continue
            allowed = {
                "runId",
                "consumerStepId",
                "producerStepId",
                "outputRef",
                "fields",
                "tokens",
                "channel",
            }
            payload = {
                key: value
                for key, value in communication_read.items()
                if key in allowed
            }
            if event_type == "node_completed":
                node_trace_batch.append(self.trace_store.build_event(
                    run,
                    event_type=TraceEventType.DATA_CONSUMED,
                    step_id=event.get("stepId"),
                    observation="Broker communication read projected",
                    payload=payload,
                ))
            else:
                self.trace_store.append(
                    run,
                    TraceEventType.DATA_CONSUMED,
                    step_id=event.get("stepId"),
                    observation="Broker communication read projected",
                    payload=payload,
                )
        for provenance_event in event.get("provenanceEvents", []):
            if not isinstance(provenance_event, dict):
                continue
            event_name = provenance_event.get("eventType")
            trace_type = {
                "data_produced": TraceEventType.DATA_PRODUCED,
                "data_consumed": TraceEventType.DATA_CONSUMED,
            }.get(event_name)
            payload = provenance_event.get("payload")
            if trace_type is None or not isinstance(payload, dict):
                continue
            if event_type == "node_completed":
                node_trace_batch.append(self.trace_store.build_event(
                    run,
                    event_type=trace_type,
                    step_id=event.get("stepId"),
                    observation="Communication provenance projected",
                    payload=dict(payload),
                ))
            else:
                self.trace_store.append(
                    run,
                    trace_type,
                    step_id=event.get("stepId"),
                    observation="Communication provenance projected",
                    payload=dict(payload),
                )
        if node_trace_batch:
            self.trace_store.append_batch(run, node_trace_batch)
            self._inject_fault("after_trace")
        # 状态持久化属于图事件投影，不依赖模型或工具调用是否存在。若放在工具循环中，
        # 没有工具调用的普通节点会一直停留在存储层的旧快照，直到后续事件偶然覆盖。
        self._persist_acg_state(run, state)

    @staticmethod
    def _is_projected_commit(run: WorkflowRun, commit_id: str) -> bool:
        """通过既有步骤完成 Trace 判断提交是否已被投影，不额外保存正文状态。"""
        return any(
            event.event_type == TraceEventType.STEP_SUCCEEDED
            and event.payload.get("commitId") == commit_id
            for event in run.trace
        )

    def _persist_acg_state(self, run: WorkflowRun, state: ACGExecutionState) -> None:
        """保存只含摘要和引用的图投影，禁止写入 value store 中的完整正文。"""
        state_data = state.model_dump(by_alias=True, mode="json")
        run.execution_state.update(state_data)
        run.completed_step_ids = list(state.completed_step_ids)
        run.active_step_ids = list(state.active_step_ids)
        self.workflow_store.save_run(run)

    def _save_acg_checkpoint(self, run: WorkflowRun, state: ACGExecutionState) -> str:
        """按运行当前 checkpoint 版本保存下一份引用型状态。"""
        expected_version = self.checkpoint_store.latest_version(run_id=run.run_id)
        # 检查点标识来自不含既有 checkpointId 的状态摘要。同一超步在“保存成功、
        # 投影 Trace 前中断”后会生成完全相同的标识，底层仓库因此能复用旧快照和
        # 版本；状态真正推进时摘要才变化，绝不会覆盖历史检查点。
        checkpoint_data = state.model_dump(by_alias=True, mode="json")
        checkpoint_data["checkpointId"] = None
        encoded = json.dumps(checkpoint_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checkpoint_id = f"acgckpt_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"
        state.checkpoint_id = checkpoint_id
        saved = self.checkpoint_store.save(
            run_id=run.run_id,
            checkpoint_id=checkpoint_id,
            state=state.model_dump(by_alias=True, mode="json"),
            expected_version=expected_version,
        )
        self._inject_fault("after_checkpoint")
        return saved

    def _inject_fault(self, stage: str) -> None:
        """调用测试专用中断钩子；正常执行没有附加分支或持久化副作用。"""
        if self._fault_hook is not None:
            self._fault_hook(stage)

    @staticmethod
    def _acg_output(state: ACGExecutionState) -> dict[str, str]:
        """选择最后完成步骤的输出引用作为运行最终产物，不复制真实输出正文。"""
        if not state.completed_step_ids:
            return {}
        final_step_id = state.completed_step_ids[-1]
        output_ref = state.output_refs.get(final_step_id)
        return {"outputRef": output_ref} if output_ref else {}

    def _validate_blueprint_agents(
        self,
        blueprint: ACGBlueprint,
        *,
        domain: str,
        scope: RunExecutionScope | None = None,
    ) -> None:
        missing: list[str] = []
        for step in blueprint.step_nodes():
            try:
                self.agent_registry.resolve(
                    domain=domain,
                    agent_name=step.agent_name,
                    capability=step.capability,
                    allowed_agent_ids=(scope.agent_ids if scope is not None else None),
                )
            except KeyError:
                missing.append(step.agent_name or step.node_id)
        if missing:
            raise ValueError("ACG references unregistered Agents: " + ", ".join(sorted(set(missing))))

    def _register_and_freeze_resources(
        self,
        *,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
        scope: RunExecutionScope,
    ) -> None:
        """登记当前可见 Agent，并将每个 ACG Step 选择结果冻结到运行状态。"""
        for agent in self.agent_registry.all():
            self.resource_directory.register_agent(agent.profile)
        bindings: dict[str, str] = {}
        model_bindings: dict[str, dict[str, str] | None] = {}
        for step in run.steps:
            try:
                selected = self.resource_directory.resolve_agent(
                    domain=workflow.domain,
                    agent_name=step.agent_name,
                    capability=step.capability,
                    allowed_agent_ids=scope.agent_ids,
                )
            except ResourceNotFoundError as exc:
                raise ValueError(f"ACG step has no eligible resource: {step.step_id}") from exc
            bindings[step.step_id] = selected.agent_id
            agent = self.agent_registry.resolve_by_id(
                selected.agent_id,
                allowed_agent_ids=scope.agent_ids,
            )
            model_bindings[step.step_id] = self._freeze_model_binding(
                step_id=step.step_id,
                profile=agent.profile,
            )
        run.execution_state["resourceBindings"] = bindings
        run.execution_state["modelBindings"] = model_bindings

    def _freeze_model_binding(self, *, step_id: str, profile) -> dict[str, str] | None:
        """验证并冻结步骤的 Profile 模型路由，禁止恢复时读取可变 Profile。"""
        provider = (getattr(profile, "model_provider", None) or "").strip()
        model = (getattr(profile, "model_name", None) or "").strip()
        version = (getattr(profile, "model_version", None) or "").strip() or None
        if not provider and not model:
            return None
        if not provider or not model:
            raise ValueError(
                f"MODEL_PROFILE_INCOMPLETE: step {step_id} must set both modelProvider and modelName"
            )
        try:
            self.model_registry.resolve(provider, model, version=version)
        except LookupError as exc:
            raise ValueError(
                f"MODEL_PROFILE_UNAVAILABLE: step {step_id} cannot resolve {provider}/{model}"
            ) from exc
        binding = {"provider": provider, "model": model}
        if version is not None:
            binding["version"] = version
        return binding

    def _model_runtime_from_binding(self, binding: object) -> object | None:
        """依据冻结路由构造受保护运行时；未配置 Profile 时回退既有全局默认值。"""
        if binding is None:
            return None
        if not isinstance(binding, dict):
            raise ValueError("ACG model binding must be an object or null")
        provider = binding.get("provider")
        model = binding.get("model")
        version = binding.get("version")
        if not isinstance(provider, str) or not isinstance(model, str):
            raise ValueError("ACG model binding is incomplete")
        if version is not None and not isinstance(version, str):
            raise ValueError("ACG model binding version is invalid")
        return GuardedModelRuntime(
            delegate=RegisteredModelRuntime(
                registry=self.model_registry,
                provider=provider,
                model=model,
                version=version,
            ),
            retries=1,
        )

    def _build_acg_blueprint(
        self,
        task: AgentTask,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
    ) -> ACGBlueprint:
        """获取 ACG 蓝图，三级优先级：

        1. 现成蓝图：run.input['acgBlueprint'] 或 run.acg_blueprint（外部/前序产物）。
        2. 认知规划引擎：task.input['usePlanner'] 为真，或工作流未定义 steps，
           则调 PlanningEngine 走“静态优选、动态补位”生成 ACG，并把规划决策入 Trace。
        3. 线性升格：默认把静态工作流定义无损升格（行为等价线性执行）。
        """
        provided = run.input.get("acgBlueprint") or (run.acg_blueprint if run.acg_blueprint else None)
        if isinstance(provided, dict) and provided.get("nodes"):
            blueprint = ACGBlueprint.model_validate(provided)
            if not blueprint.task_id:
                blueprint = blueprint.model_copy(deep=True, update={"task_id": task.task_id})
            return blueprint

        planning_mode = str(run.input.get("planningMode") or "").strip().lower()
        force_dynamic = (
            workflow.is_native_bootstrap
            or bool(run.input.get("forceDynamicPlanning"))
            or planning_mode == "dynamic"
        )
        use_planner = force_dynamic or bool(run.input.get("usePlanner")) or not workflow.steps
        if use_planner:
            intent_text = str(
                run.input.get("userIntent")
                or run.input.get("intent")
                or task.title
                or workflow.description
            )
            planning_engine = self._planning_engine_for_run(run)
            plan = planning_engine.plan(
                task_id=task.task_id,
                intent=intent_text,
                domain=workflow.domain or task.domain,
                task_type=task.intent or workflow.intent,
                force_dynamic=force_dynamic,
                thinking_mode=str(run.input.get("thinkingMode") or "").strip() or None,
                # 强制动态图仍使用本地语义解析以避免模型往返；拓扑多样性由
                # 已持久化 seed 驱动，并且只作用于受约束的规划候选。
                deterministic_intent=force_dynamic,
                planning_diversity=run.planning_diversity,
                planning_seed=run.planning_seed,
                capability_catalog_revision=run.capability_catalog_revision,
            )
            run.planning_diversity = plan.planning_diversity
            run.planning_seed = plan.planning_seed
            run.planner_algorithm_version = plan.planner_algorithm_version
            run.planning_candidate_count = max(1, plan.candidate_count)
            run.selected_planning_variant_id = plan.selected_variant_id
            run.execution_state.update(
                {
                    "planningDiversity": plan.planning_diversity,
                    "planningSeed": plan.planning_seed,
                    "plannerAlgorithmVersion": plan.planner_algorithm_version,
                    "planningCandidateCount": plan.candidate_count,
                    "selectedPlanningVariantId": plan.selected_variant_id,
                    "selectedCapabilities": list(plan.selected_capabilities),
                    "selectedBindings": list(plan.selected_bindings),
                    "planningSelectionReasons": list(plan.selection_reasons),
                }
            )
            self.trace_store.append(
                run=run,
                event_type=TraceEventType.TASK_STATUS_CHANGED,
                observation=f"Planner produced ACG via {plan.strategy}",
                payload=plan.to_decision()
                | {
                    "resolvedEnabledPluginIds": list(run.enabled_plugin_ids),
                    "capabilityCatalogRevision": run.capability_catalog_revision,
                    "visibleCapabilityCount": (
                        len(run.execution_scope.capability_ids)
                        if run.execution_scope is not None
                        else len(self.capability_catalog.available())
                    ),
                    "scopeExcludedAgentCount": int(
                        run.execution_state.get("scopeExcludedAgentCount", 0)
                    ),
                },
            )
            if plan.stochastic_fallback:
                self.trace_store.append(
                    run=run,
                    event_type=TraceEventType.STOCHASTIC_PLANNING_FALLBACK,
                    observation="No stochastic candidate passed validation; stable planning used",
                    payload=plan.to_decision(),
                )
            return plan.blueprint

        return promote_workflow_to_acg(workflow, task_id=task.task_id)

    def _sync_run_steps_to_acg(self, run: WorkflowRun, blueprint: ACGBlueprint) -> None:
        """让 WorkflowRun 的步骤列表与最终 ACG 蓝图保持一致。"""
        existing = {step.step_id: step for step in run.steps}
        synced: list[WorkflowStep] = []
        for node in blueprint.step_nodes():
            # Blueprint 是规划期唯一真源。这里把记忆策略复制到本次运行步骤，后续
            # 即使蓝图对象被修改，也不能反向改变已创建 run 的读取、写入和预算边界。
            node_input = dict(node.input_spec)
            memory_policy = node.metadata.get("memoryPolicy")
            if memory_policy is not None:
                if not isinstance(memory_policy, dict):
                    raise ValueError(f"ACG step {node.node_id} memoryPolicy must be an object")
                # 在 prepare_run 冻结前立即校验并标准化策略。这样错误配置不会等到
                # 节点已经调用 Agent 后才暴露；保存到运行的快照始终采用读写分离格式。
                normalized = ACGNodeRunner._memory_policy({"memoryPolicy": memory_policy})
                node_input["memoryPolicy"] = {
                    "policyId": normalized["policyId"],
                    "read": normalized["read"],
                    "readTypes": [item.value for item in normalized["readTypes"]],
                    "write": normalized["write"],
                    "writeType": (
                        normalized["writeType"].value
                        if normalized["writeType"] is not None
                        else None
                    ),
                    "limit": normalized["limit"],
                    "tokenBudget": normalized["tokenBudget"],
                    "requireAudit": normalized["requireAudit"],
                }
            step = existing.get(node.node_id)
            if step is None:
                step = WorkflowStep(
                    stepId=node.node_id,
                    name=node.name or node.node_id,
                    agentName=node.agent_name or node.node_id,
                    capability=node.capability,
                    input=node_input,
                    outputSpec=dict(node.output_spec),
                    reviewRequired=node.review_required,
                    maxRetries=node.retry_limit,
                    timeout=node.timeout,
                    priority=node.priority,
                )
            else:
                step.name = node.name or step.name
                step.agent_name = node.agent_name or step.agent_name
                step.capability = node.capability
                step.input = node_input
                step.output_spec = dict(node.output_spec)
                step.requires_review = node.review_required
                step.max_retries = node.retry_limit
                step.timeout = node.timeout
                step.priority = node.priority
            synced.append(step)

        run.steps = synced
        step_ids = {step.step_id for step in synced}
        if run.current_step_id not in step_ids:
            run.current_step_id = synced[0].step_id if synced else None

    def _transition_run_if_needed(self, run: WorkflowRun, status: WorkflowStatus) -> None:
        if run.status != status:
            self._transition_run(run, status)

    def get_status(self, run_id: str) -> WorkflowRun:
        """读取指定运行的最新状态投影；不存在时由存储层抛出 ``KeyError``。"""
        return self.workflow_store.get_run(run_id)

    async def update_run_lifecycle(
        self,
        run_id: str,
        *,
        status: WorkflowStatus | None = None,
        phase: WorkflowProgressPhase | None = None,
        message: str | None = None,
        error: object = _ERROR_UNSET,
        set_started_at: bool = False,
    ) -> WorkflowRun:
        """重新读取、校验并持久化生命周期字段，返回最新投影；终态非法迁移会被拒绝。"""

        run = self.workflow_store.get_run(run_id)
        return self._set_run_lifecycle(
            run,
            status=status,
            phase=phase,
            message=message,
            error=error,
            set_started_at=set_started_at,
        )

    def _set_run_lifecycle(
        self,
        run: WorkflowRun,
        *,
        status: WorkflowStatus | None = None,
        phase: WorkflowProgressPhase | None = None,
        message: str | None = None,
        error: object = _ERROR_UNSET,
        set_started_at: bool = False,
    ) -> WorkflowRun:
        try:
            persisted = self.workflow_store.get_run(run.run_id)
        except KeyError:
            persisted = run
        if persisted.status in _TERMINAL_RUN_STATUSES and persisted.status != run.status:
            run = persisted
        if run.status in _TERMINAL_RUN_STATUSES:
            terminal_phase = WorkflowProgressPhase(run.status.value)
            if status not in {None, run.status} or phase not in {None, terminal_phase}:
                return run

        target_status = status or run.status
        terminal_phase_by_status = {
            WorkflowStatus.COMPLETED: WorkflowProgressPhase.COMPLETED,
            WorkflowStatus.FAILED: WorkflowProgressPhase.FAILED,
            WorkflowStatus.CANCELLED: WorkflowProgressPhase.CANCELLED,
        }
        target_phase = terminal_phase_by_status.get(target_status, phase)
        target_message = message
        if target_phase is not None and target_message is None:
            target_message = _LIFECYCLE_MESSAGES[target_phase]

        changed = False
        if target_status != run.status:
            run.status = self.state_machine.transition(run.status, target_status)
            changed = True
        if target_phase is not None and target_phase != run.lifecycle_phase:
            run.lifecycle_phase = target_phase
            changed = True
        if target_message is not None and target_message != run.lifecycle_message:
            run.lifecycle_message = target_message
            changed = True
        if set_started_at and run.started_at is None:
            run.started_at = utc_now()
            changed = True
        if error is not _ERROR_UNSET and error != run.error:
            run.error = error  # type: ignore[assignment]
            changed = True
        if changed:
            run.updated_at = utc_now()
            self.workflow_store.save_run(run)
        return run

    async def fail_run_safely(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> WorkflowRun:
        """在受管执行边界尽力收敛为失败终态，并写入有界错误信息和追踪事件。"""

        run = self.workflow_store.get_run(run_id)
        if run.status in _TERMINAL_RUN_STATUSES:
            return run
        error = {
            "code": error_code,
            "message": error_message[:500],
        }
        self._terminalize_active_execution(run, error["message"])
        run = self._set_run_lifecycle(
            run,
            status=WorkflowStatus.FAILED,
            phase=WorkflowProgressPhase.FAILED,
            message=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.FAILED],
            error=error,
        )
        try:
            self.task_manager.mark_failed(run.task_id)
        except Exception:
            logger.exception(
                "Failed to align task status after run failure",
                extra={"taskId": run.task_id, "runId": run.run_id},
            )
        self.trace_store.append(
            run=run,
            event_type=TraceEventType.RUN_FAILED,
            observation=error["message"],
            payload=error,
        )
        run.updated_at = utc_now()
        self.workflow_store.save_run(run)
        return run

    @staticmethod
    def _terminalize_active_execution(
        run: WorkflowRun,
        error_message: str,
        *,
        include_current_pending: bool = False,
    ) -> None:
        """Close active nodes before a failed Run is validated and persisted."""

        active_statuses = {StepStatus.RUNNING, StepStatus.RETRYING}
        current_step_id = run.current_step_id if include_current_pending else None
        ended_at = utc_now()
        for step in run.steps:
            if step.status in active_statuses or (
                current_step_id
                and step.step_id == current_step_id
                and step.status == StepStatus.PENDING
            ):
                step.status = StepStatus.FAILED
                step.error = error_message
                step.completed_at = ended_at
        run.active_step_ids = []

    async def close_orphaned_runs(self, *, limit: int = 200) -> list[str]:
        """关闭重启后失去进程内执行器的未终态运行，返回已关闭标识列表。"""

        closed: list[str] = []
        for run in self.workflow_store.list_non_terminal_runs(limit=limit):
            if run.status == WorkflowStatus.WAITING_REVIEW:
                if self._normalize_waiting_review_after_restart(run):
                    run.updated_at = utc_now()
                    self.workflow_store.save_run(run)
                continue
            if run.status not in {
                WorkflowStatus.PENDING,
                WorkflowStatus.PLANNING,
                WorkflowStatus.RUNNING,
                WorkflowStatus.RETRYING,
            }:
                continue
            self._fail_interrupted_run_after_restart(run)
            closed.append(run.run_id)
            logger.warning(
                "interrupted_run_closed_after_restart",
                extra={
                    "taskId": run.task_id,
                    "runId": run.run_id,
                    "workflowId": run.workflow_id,
                    "phase": run.lifecycle_phase.value if run.lifecycle_phase else None,
                },
            )
        return closed

    @staticmethod
    def _normalize_waiting_review_after_restart(run: WorkflowRun) -> bool:
        """Align both persisted step projections without leaving review state."""

        changed = False
        waiting_ids = {
            step.step_id for step in run.steps if step.status == StepStatus.WAITING_REVIEW
        }
        if not waiting_ids and run.current_step_id:
            waiting_ids.add(run.current_step_id)
        for step in run.steps:
            if step.step_id in waiting_ids and step.status != StepStatus.WAITING_REVIEW:
                step.status = StepStatus.WAITING_REVIEW
                changed = True
        if run.lifecycle_phase != WorkflowProgressPhase.REVIEW:
            run.lifecycle_phase = WorkflowProgressPhase.REVIEW
            changed = True
        if run.lifecycle_message != _LIFECYCLE_MESSAGES[WorkflowProgressPhase.REVIEW]:
            run.lifecycle_message = _LIFECYCLE_MESSAGES[WorkflowProgressPhase.REVIEW]
            changed = True
        return changed

    def _fail_interrupted_run_after_restart(self, run: WorkflowRun) -> None:
        """Mutate every run projection first, then persist one consistent snapshot."""

        interruption_message = "任务因服务重启而中断。"
        self._terminalize_active_execution(
            run,
            interruption_message,
            include_current_pending=True,
        )
        run.status = WorkflowStatus.FAILED
        run.lifecycle_phase = WorkflowProgressPhase.FAILED
        run.lifecycle_message = interruption_message
        run.error = {
            "code": "interrupted_after_restart",
            "message": interruption_message,
        }
        try:
            self.task_manager.mark_failed(run.task_id)
        except Exception:
            logger.exception(
                "Failed to align task status after interrupted run",
                extra={"taskId": run.task_id, "runId": run.run_id},
            )
        self.trace_store.append(
            run=run,
            event_type=TraceEventType.RUN_FAILED,
            observation=interruption_message,
            payload=dict(run.error),
        )
        run.updated_at = utc_now()
        self.workflow_store.save_run(run)

    @staticmethod
    def _safe_error_message(exc: BaseException) -> str:
        message = str(exc).strip()
        return (message or type(exc).__name__)[:500]

    def resolve_workflow_id(self, workflow_id: str | None) -> str | None:
        """规范化可选工作流标识；非空值会经注册表校验，不存在时抛出错误。"""
        if not workflow_id:
            return workflow_id
        return self.workflow_registry.get(workflow_id).workflow_id

    def list_checkpoints(self, run_id: str) -> list[Checkpoint]:
        """读取运行关联检查点列表，不改变运行或检查点状态。"""
        return list(self.workflow_store.get_run(run_id).checkpoints)

    def clean_execution_orphans(self, *, run_id: str, older_than: datetime):
        """延迟清理当前运行未被提交、State、检查点或审核意图保护的执行正文。

        调用方必须显式给出带时区的保留阈值，避免默认立即删除。整个收集和删除过程
        持有当前 run 锁，因此恢复、审核和清理不会交错地删除仍准备提交的引用。Trace
        只记录扫描、保护和删除计数，不能包含 output、ContextPack 或记忆正文。
        """
        with self.run_lock_manager.lock_for(run_id):
            run = self.workflow_store.get_run(run_id)
            protected_refs = self._protected_execution_references(run)
            stats = self.orphan_cleaner.clean(
                run_id=run_id,
                protected_refs=protected_refs,
                older_than=older_than,
            )
            self.trace_store.append(
                run,
                TraceEventType.TASK_STATUS_CHANGED,
                observation="Expired execution values cleaned",
                payload={
                    "kind": "execution_value_cleanup",
                    "scanned": stats.scanned,
                    "protected": stats.protected,
                    "deleted": stats.deleted,
                },
            )
            self.workflow_store.save_run(run)
            return stats

    def _protected_execution_references(self, run: WorkflowRun) -> set[str]:
        """从所有可恢复入口提取已知正文引用，不递归读取或复制任何正文。"""
        references: set[str] = set()
        self._collect_value_references(run.execution_state, references)
        self._collect_value_references(run.output, references)
        for commit in self.execution_value_store.list_node_commits(run_id=run.run_id):
            self._collect_value_references(commit, references)
        checkpoint_states = getattr(self.checkpoint_store, "list_states", None)
        if callable(checkpoint_states):
            for state in checkpoint_states(run_id=run.run_id):
                self._collect_value_references(state, references)
        for checkpoint in run.checkpoints:
            self._collect_value_references(checkpoint.state_snapshot, references)
            self._collect_value_references(checkpoint.output_snapshot, references)
        return references

    @staticmethod
    def _collect_value_references(payload: object, references: set[str]) -> None:
        """从已定义的引用字段收集标识，不能把任意字符串误当成可保护的引用。"""
        if not isinstance(payload, dict):
            return
        for field_name in ("outputRef", "contextRef", "graphPatchRef"):
            value = payload.get(field_name)
            if isinstance(value, str) and value:
                references.add(value)
        for field_name in ("outputRefs", "contextRefs", "graphPatchRefs"):
            values = payload.get(field_name)
            if isinstance(values, dict):
                references.update(
                    value for value in values.values() if isinstance(value, str) and value
                )
            elif isinstance(values, list):
                references.update(value for value in values if isinstance(value, str) and value)
        review_payload = payload.get("reviewPayload")
        if isinstance(review_payload, dict):
            pending_memory = review_payload.get("pendingMemory")
            if isinstance(pending_memory, dict):
                output_ref = pending_memory.get("outputRef")
                if isinstance(output_ref, str) and output_ref:
                    references.add(output_ref)
        pending_memory = payload.get("pendingMemory")
        if isinstance(pending_memory, dict):
            output_ref = pending_memory.get("outputRef")
            if isinstance(output_ref, str) and output_ref:
                references.add(output_ref)

    def list_reviews(self, run_id: str) -> list[ReviewRecord]:
        """读取运行审核记录列表，不执行审核决策或状态迁移。"""
        return self.review_manager.list(self.workflow_store.get_run(run_id))

    def evaluate_runs(
        self,
        *,
        status: WorkflowStatus | str | None = None,
        domain: str | None = None,
        workflow_id: str | None = None,
        source: str | None = None,
    ) -> EvaluationRun:
        """按可选状态、域和来源过滤运行并生成评估汇总，复杂度受存储查询结果规模限制。"""
        workflow_id = self.resolve_workflow_id(workflow_id)
        page = self.workflow_store.list_runs(
            status=status,
            domain=domain,
            workflow_id=workflow_id,
            source=source,
            page=1,
            page_size=10_000,
        )
        return self.evaluator.evaluate(
            page.items,
            domain=domain,
            workflow_id=workflow_id,
            source=source,
        )

    async def apply_review(self, decision: ReviewDecision) -> WorkflowRun:
        """在运行锁内校验并应用审核决定；过期、冲突或终态运行抛出 ``ReviewConflictError``。"""
        initial_run = self.workflow_store.get_run(decision.run_id)
        if self._normalize_runtime_engine(initial_run.runtime_engine) == "acg":
            return await self._apply_acg_review(decision)
        async with self.run_lock_manager.lock_for(decision.run_id):
            run = self.workflow_store.get_run(decision.run_id)
            existing = self._find_review_operation(run, decision.operation_id)
            if existing is not None:
                if (
                    existing.get("stepId") == decision.step_id
                    and existing.get("decision") == decision.decision.value
                ):
                    return run
                raise ReviewConflictError("review operation id was already used for a different decision")

            if run.status in _TERMINAL_RUN_STATUSES:
                raise ReviewConflictError("workflow run is already terminal")
            if run.status != WorkflowStatus.WAITING_REVIEW:
                raise ReviewConflictError("workflow run is no longer waiting for review")
            step = run.get_step(decision.step_id)
            if step.status != StepStatus.WAITING_REVIEW:
                raise ReviewConflictError("workflow step is no longer waiting for review")
            if (
                decision.expected_run_updated_at is not None
                and run.updated_at != decision.expected_run_updated_at
            ):
                raise ReviewConflictError("workflow run revision changed")
            if (
                decision.expected_step_status is not None
                and step.status != decision.expected_step_status
            ):
                raise ReviewConflictError("workflow step state changed")

        workflow = self._workflow_for_run(run)
        adapter = self._workflow_adapter(workflow)
        return await adapter.apply_review(decision)

    async def apply_graph_patch(self, patch: GraphPatch) -> GraphPatchResult:
        """Apply one audited graph revision at a persisted review barrier.

        Patch bodies live in ``ExecutionValueStore``; WorkflowRun and the
        checkpoint retain only the resulting revision and patch reference.
        Running or terminal graphs are never mutated in place.
        """
        async with self.run_lock_manager.lock_for(patch.run_id):
            run = self.workflow_store.get_run(patch.run_id)
            if self._normalize_runtime_engine(run.runtime_engine) != "acg":
                raise ValueError("graph patching is only available for ACG runs")
            if run.status is not WorkflowStatus.WAITING_REVIEW:
                raise GraphPatchConflictError(
                    "graph patches require a persisted WAITING_REVIEW barrier"
                )
            if not isinstance(run.acg_blueprint, dict):
                raise ValueError("ACG run has no persisted blueprint")
            checkpoint_id = str(run.execution_state.get("checkpointId") or "")
            checkpoint_data = self.checkpoint_store.load(
                run_id=run.run_id,
                checkpoint_id=checkpoint_id,
            )
            if checkpoint_data is None:
                raise ValueError("graph patch requires a persisted checkpoint")
            state = ACGExecutionState.model_validate(checkpoint_data)
            blueprint = ACGBlueprint.model_validate(run.acg_blueprint)
            outcome = GraphPatchService().apply(
                blueprint,
                patch,
                completed_step_ids=set(state.completed_step_ids),
                active_step_ids=set(state.active_step_ids),
            )
            previous = next(
                (
                    item
                    for item in outcome.blueprint.metadata.get("appliedGraphPatches", [])
                    if isinstance(item, dict) and item.get("patchId") == patch.patch_id
                ),
                {},
            )
            if outcome.idempotent_replay:
                uri = str(previous.get("patchRef") or "")
                if not uri:
                    raise ValueError("persisted graph patch is missing its reference")
                return GraphPatchResult(
                    applied=False,
                    idempotentReplay=True,
                    graphVersion=outcome.blueprint.version,
                    patchRef=GraphPatchRef(
                        patchId=patch.patch_id,
                        graph=GraphRef(
                            graphId=outcome.blueprint.graph_id,
                            version=str(outcome.blueprint.version),
                        ),
                        uri=uri,
                        checksum=outcome.checksum,
                    ),
                )

            task = self.task_manager.get_task(run.task_id)
            workflow = self._workflow_for_run(run)
            scope = run.execution_scope
            if scope is None:
                raise ValueError("graph patch requires a frozen execution scope")
            self._validate_blueprint_agents(
                outcome.blueprint,
                domain=workflow.domain or task.domain,
                scope=scope,
            )
            old_step_ids = {step.step_id for step in run.steps}
            self._sync_run_steps_to_acg(run, outcome.blueprint)
            for agent in self.agent_registry.all():
                self.resource_directory.register_agent(agent.profile)
            bindings = dict(run.execution_state.get("resourceBindings") or {})
            for step in run.steps:
                if step.step_id in old_step_ids:
                    continue
                selected = self.resource_directory.resolve_agent(
                    domain=workflow.domain,
                    agent_name=step.agent_name,
                    capability=step.capability,
                    allowed_agent_ids=scope.agent_ids,
                )
                bindings[step.step_id] = selected.agent_id

            patch_uri = self.execution_value_store.put_graph_patch(
                run_id=run.run_id,
                payload=patch.model_dump(by_alias=True, mode="json"),
            )
            patch_ref = GraphPatchRef(
                patchId=patch.patch_id,
                graph=GraphRef(
                    graphId=outcome.blueprint.graph_id,
                    version=str(outcome.blueprint.version),
                ),
                uri=patch_uri,
                checksum=outcome.checksum,
            )
            applied_metadata = list(outcome.blueprint.metadata["appliedGraphPatches"])
            applied_metadata[-1] = {**applied_metadata[-1], "patchRef": patch_uri}
            outcome.blueprint.metadata["appliedGraphPatches"] = applied_metadata
            run.acg_blueprint = outcome.blueprint.model_dump(by_alias=True, mode="json")
            state.graph_version = outcome.blueprint.version
            state.graph_patch_refs = list(dict.fromkeys([*state.graph_patch_refs, patch_uri]))
            state.checkpoint_id = None
            run.execution_state["resourceBindings"] = bindings
            run.execution_state["sourceBlueprintVersion"] = outcome.blueprint.version
            run.execution_state["graphVersion"] = outcome.blueprint.version
            self._persist_acg_state(run, state)
            new_checkpoint_id = self._save_acg_checkpoint(run, state)
            self._persist_acg_state(run, state)
            self.trace_store.append(
                run,
                TraceEventType.GRAPH_PATCH_APPLIED,
                observation="ACG graph patch applied",
                payload={
                    "patchId": patch.patch_id,
                    "patchRef": patch_uri,
                    "baseGraphVersion": patch.base_graph_version,
                    "graphVersion": outcome.blueprint.version,
                    "checkpointId": new_checkpoint_id,
                },
            )
            self.workflow_store.save_run(run)
            return GraphPatchResult(
                applied=True,
                graphVersion=outcome.blueprint.version,
                patchRef=patch_ref,
            )

    async def rebind_step(self, *, run_id: str, step_id: str, reason: str) -> str:
        """Select a healthy alternate Agent inside the run's frozen scope.

        Rebinding is intentionally limited to a persisted review barrier and a
        not-yet-executed step. It changes only the frozen resource projection;
        no executor, workflow state machine, or graph is duplicated.
        """
        async with self.run_lock_manager.lock_for(run_id):
            run = self.workflow_store.get_run(run_id)
            if self._normalize_runtime_engine(run.runtime_engine) != "acg":
                raise ValueError("resource rebinding is only available for ACG runs")
            if run.status is not WorkflowStatus.WAITING_REVIEW:
                raise ValueError("resource rebinding requires a persisted WAITING_REVIEW barrier")
            step = run.get_step(step_id)
            if step.status not in {StepStatus.PENDING, StepStatus.RETRYING}:
                raise ValueError("only a pending or retrying step can be rebound")
            scope = run.execution_scope
            if scope is None:
                raise ValueError("resource rebinding requires a frozen execution scope")
            bindings = dict(run.execution_state.get("resourceBindings") or {})
            current_agent_id = str(bindings.get(step_id) or "")
            if not current_agent_id:
                raise ValueError(f"ACG step has no frozen resource binding: {step_id}")
            history = list(run.execution_state.get("bindingHistory") or [])
            if any(item.get("stepId") == step_id for item in history if isinstance(item, dict)):
                raise ValueError(f"alternate binding budget exhausted for step: {step_id}")
            candidates = self.resource_directory.resolve_agent_candidates(
                domain=self._workflow_for_run(run).domain,
                capability=step.capability,
                allowed_agent_ids=scope.agent_ids,
                excluded_agent_ids=(current_agent_id,),
            )
            if not candidates:
                raise ResourceNotFoundError(f"no healthy alternate resource for step: {step_id}")
            selected = candidates[0]
            # Resolve the instance now so a stale directory entry cannot enter
            # persisted state.
            self.agent_registry.resolve_by_id(selected.agent_id, allowed_agent_ids=scope.agent_ids)
            bindings[step_id] = selected.agent_id
            run.execution_state["resourceBindings"] = bindings
            history.append(
                {
                    "stepId": step_id,
                    "previousAgentId": current_agent_id,
                    "agentId": selected.agent_id,
                    "reason": reason,
                }
            )
            run.execution_state["bindingHistory"] = history
            self.trace_store.append(
                run,
                TraceEventType.RUNTIME_PATCH_APPLIED,
                observation="ACG resource binding changed at review barrier",
                step_id=step_id,
                agent_name=selected.agent_name,
                payload={
                    "patchType": "alternate_binding",
                    "previousAgentId": current_agent_id,
                    "agentId": selected.agent_id,
                    "reason": reason,
                },
            )
            self.workflow_store.save_run(run)
            return selected.agent_id

    async def _apply_acg_review(self, decision: ReviewDecision) -> WorkflowRun:
        """校验审核决定并从同一 run 的 SQLite 检查点恢复融合 ACG。"""
        async with self.run_lock_manager.lock_for(decision.run_id):
            run = self.workflow_store.get_run(decision.run_id)
            existing = self._find_review_operation(run, decision.operation_id)
            if existing is not None:
                if existing.get("stepId") == decision.step_id and existing.get("decision") == decision.decision.value:
                    return run
                raise ReviewConflictError("review operation id was already used for a different decision")
            if run.status != WorkflowStatus.WAITING_REVIEW:
                raise ReviewConflictError("workflow run is no longer waiting for review")
            step = run.get_step(decision.step_id)
            if step.status != StepStatus.WAITING_REVIEW:
                raise ReviewConflictError("workflow step is no longer waiting for review")
            checkpoint_id = str(run.execution_state.get("checkpointId") or "")
            checkpoint_data = self.checkpoint_store.load(run_id=run.run_id, checkpoint_id=checkpoint_id)
            if checkpoint_data is None:
                raise ValueError("review checkpoint does not exist for this run")
            restored = ACGExecutionState.model_validate(checkpoint_data)
            # 拒绝路径也必须验证 checkpoint 中的审计引用。否则攻击者可借由“直接
            # 拒绝”绕过归属检查，留下无法解释的审核记录或伪造的待写入意图。
            self._validate_acg_state_references(run=run, state=restored)
            if decision.decision is not ReviewDecisionType.APPROVED:
                self._transition_step(step, StepStatus.FAILED)
                run.error = {"code": "review_rejected", "message": decision.comment[:500]}
                self.trace_store.append(
                    run,
                    TraceEventType.REVIEW_DECIDED,
                    step_id=step.step_id,
                    observation="ACG review rejected",
                    payload={
                        "decision": decision.decision.value,
                        "operationId": decision.operation_id,
                        "reviewer": decision.reviewer,
                        "comment": decision.comment,
                        "deferredMemoryDiscarded": isinstance(
                            (restored.review_payload or {}).get("pendingMemory"), dict
                        ),
                    },
                )
                run = self._set_run_lifecycle(run, status=WorkflowStatus.FAILED, phase=WorkflowProgressPhase.FAILED)
                self.task_manager.mark_failed(run.task_id)
                self.workflow_store.save_run(run)
                return run
            self._commit_deferred_memory(run=run, step=step, state=restored)
            # The node result was committed before the interrupt; approval
            # resolves the review projection and must not leave a stale
            # WAITING_REVIEW step in an otherwise completed persisted run.
            self._transition_step(step, StepStatus.COMPLETED)
            self.trace_store.append(
                run,
                event_type=TraceEventType.REVIEW_DECIDED,
                step_id=step.step_id,
                observation="ACG review approved",
                payload={
                    "decision": decision.decision.value,
                    "operationId": decision.operation_id,
                    "reviewer": decision.reviewer,
                    "comment": decision.comment,
                },
            )
        return await self._execute_acg(
            run,
            state=restored,
            command=ExecutionResumeCommand(
                runId=run.run_id,
                payload={"decision": decision.decision.value, "operationId": decision.operation_id},
            ),
        )

    def _commit_deferred_memory(
        self,
        *,
        run: WorkflowRun,
        step: WorkflowStep,
        state: ACGExecutionState,
    ) -> None:
        """在人工批准后按待写入意图落入正式记忆，不读取检查点中的正文。

        待写入意图来自节点提交和审核检查点，只允许引用、策略标识与审计决定。真正
        输出仍必须通过 ``ExecutionValueStore`` 按 run/step 重新读取，避免人工审核
        路径意外成为把正文写回 State 或绕过输出合同的后门。
        """
        review_payload = state.review_payload or {}
        pending = review_payload.get("pendingMemory")
        if pending is None:
            return
        if not isinstance(pending, dict):
            raise ValueError("review pendingMemory must be an object")
        output_ref = pending.get("outputRef")
        policy_id = pending.get("policyId")
        write_type = pending.get("writeType")
        decision_ref = pending.get("auditDecisionRef")
        if not all(isinstance(value, str) and value for value in (output_ref, policy_id, write_type, decision_ref)):
            raise ValueError("review pendingMemory is incomplete")
        if review_payload.get("auditDecisionRef") != decision_ref:
            raise ValueError("review pendingMemory audit decision does not match review payload")
        allowed_audit_outcomes = {"review"}
        if step.requires_review:
            # A Blueprint-declared review gate is authoritative even when the
            # generic output-risk audit independently returns ``allow``.
            allowed_audit_outcomes.add("allow")
        self.decision_store.assert_decision(
            run_id=run.run_id,
            step_id=step.step_id,
            decision_ref=decision_ref,
            outcomes=allowed_audit_outcomes,
        )
        policy = ACGNodeRunner._memory_policy(step.input)
        if not policy["write"]:
            raise ValueError("review pendingMemory exists while step memory write is disabled")
        if policy["policyId"] != policy_id or policy["writeType"].value != write_type:
            raise ValueError("review pendingMemory does not match frozen memory policy")
        self.execution_value_store.assert_reference(
            kind="output",
            run_id=run.run_id,
            step_id=step.step_id,
            reference=output_ref,
        )
        output = self.execution_value_store.get_output(run_id=run.run_id, output_ref=output_ref)
        record = MemoryService(store=self.memory_store).remember_step_output(
            run_id=run.run_id,
            step_id=step.step_id,
            output=output,
            memory_type=MemoryType(write_type),
            policy=MemoryPolicy(
                policyId=policy_id,
                allowedTypes=[MemoryType(write_type)],
                requireAudit=bool(policy["requireAudit"]),
            ),
        )
        if record is None:
            raise ValueError("review deferred memory was rejected by frozen policy")
        state.memory_refs[step.step_id] = record.memory_id
        self.trace_store.append(
            run,
            TraceEventType.DATA_CONSUMED,
            step_id=step.step_id,
            observation="Deferred memory committed after review approval",
            payload={
                "policyId": policy_id,
                "writeType": write_type,
                "written": True,
                "auditDecisionRef": decision_ref,
            },
        )

    @staticmethod
    def _find_review_operation(run: WorkflowRun, operation_id: str | None) -> dict | None:
        if not operation_id:
            return None
        for event in run.trace:
            if event.event_type != TraceEventType.REVIEW_DECIDED:
                continue
            payload = event.payload or {}
            if payload.get("operationId") == operation_id:
                return payload
        return None

    async def resume_from_checkpoint(self, *, run_id: str, checkpoint_id: str) -> WorkflowRun:
        """从同版本检查点恢复 ACG 运行；范围、图或工作流版本不匹配时明确拒绝。"""
        initial_run = self.workflow_store.get_run(run_id)
        if self._normalize_runtime_engine(initial_run.runtime_engine) == "acg":
            checkpoint_data = self.checkpoint_store.load(run_id=run_id, checkpoint_id=checkpoint_id)
            if checkpoint_data is None:
                raise ValueError("checkpoint does not exist for this run")
            state = ACGExecutionState.model_validate(checkpoint_data)
            return await self._execute_acg(
                initial_run,
                state=state,
                command=ExecutionResumeCommand(runId=run_id),
            )
        raise ValueError("Checkpoint resume is only available for the ACG execution engine")

    def cancel(self, run_id: str) -> WorkflowRun:
        """在运行锁内取消可继续步骤并持久化终态；已终态的迁移规则由状态机校验。"""
        with self.run_lock_manager.lock_for(run_id):
            latest = self.workflow_store.get_run(run_id)
            run = latest.model_copy(deep=True)
            self._transition_run(run, WorkflowStatus.CANCELLED)
            self.task_manager.mark_cancelled(run.task_id)
            self.trace_store.append(
                run=run,
                event_type=TraceEventType.RUN_CANCELLED,
                observation="Workflow cancelled.",
            )
            self.workflow_store.save_run(run)
            return run

    def _resolve_workflow(
        self,
        task: AgentTask,
        workflow_id: Optional[str],
        *,
        allowed_workflow_ids: tuple[str, ...] | None = None,
    ) -> WorkflowDefinition:
        return self.task_manager.bind_workflow(
            task,
            workflow_id=workflow_id,
            allowed_workflow_ids=allowed_workflow_ids,
        )

    def _planning_engine_for_run(self, run: WorkflowRun):
        if run.execution_scope is None:
            return self.planning_engine
        from components.planner.service import PlanningEngine

        return PlanningEngine(
            workflow_registry=self.plugin_scope_resolver.scoped_workflows(
                run.execution_scope
            ),
            agent_registry=self.plugin_scope_resolver.scoped_agents(
                run.execution_scope
            ),
            capability_catalog=self.plugin_scope_resolver.scoped_catalog(
                run.execution_scope
            ),
            intent_llm=self._intent_llm,
        )

    def _workflow_for_run(self, run: WorkflowRun) -> WorkflowDefinition:
        if run.execution_scope is None:
            if run.legacy_plugin_scope:
                raise PluginScopeError(
                    "LEGACY_PLUGIN_SNAPSHOT_MISSING",
                    f"run {run.run_id} has no frozen plugin scope",
                )
            return self.workflow_registry.get(run.workflow_id)
        self.plugin_scope_resolver.validate_snapshot(run.execution_scope)
        return self.workflow_registry.get(
            run.workflow_id,
            allowed_workflow_ids=run.execution_scope.workflow_ids,
        )

    def _workflow_adapter(self, workflow: WorkflowDefinition):
        runtime_engine = workflow.effective_runtime_engine
        implementation_id = workflow.effective_implementation_id
        adapter_key = f"{runtime_engine}:{implementation_id}"
        adapter = self._runtime_adapters.get(adapter_key)
        if adapter is None:
            if runtime_engine == "acg":
                raise ExecutionEngineMigratingError()
            else:
                factory = self.execution_adapter_factories.get(runtime_engine)
                if factory is None:
                    raise ValueError(f"Unsupported workflow runtime engine: {runtime_engine}")
                adapter = factory(
                    runtime=self,
                    workflow=workflow,
                    implementation_id=implementation_id,
                )
            self._runtime_adapters[adapter_key] = adapter
        return adapter

    @staticmethod
    def _normalize_runtime_engine(runtime_engine: str) -> str:
        return (runtime_engine or "").strip().lower()

    def _mark_step_failed(
        self,
        run: WorkflowRun,
        task: AgentTask,
        step: WorkflowStep,
        exc: Exception,
    ) -> None:
        step.error = str(exc)
        if step.retry_count < step.max_retries:
            step.retry_count += 1
            self._transition_step(step, StepStatus.RETRYING)
            self._transition_run(run, WorkflowStatus.RETRYING)
            self.task_manager.mark_retrying(task)
        else:
            self._transition_step(step, StepStatus.FAILED)
            self._transition_run(run, WorkflowStatus.FAILED)
            self.task_manager.mark_failed(task)
        run.current_step_id = step.step_id
        run.error = str(exc)
        run.updated_at = utc_now()
        self.trace_store.append(
            run=run,
            event_type=TraceEventType.STEP_FAILED,
            step_id=step.step_id,
            agent_name=step.agent_name,
            observation=str(exc),
        )
        self.trace_store.append(
            run=run,
            event_type=TraceEventType.RUN_FAILED,
            step_id=step.step_id,
            observation=str(exc),
        )
        self.workflow_store.save_run(run)

    def _transition_run(self, run: WorkflowRun, status: WorkflowStatus) -> None:
        try:
            persisted = self.workflow_store.get_run(run.run_id)
        except KeyError:
            persisted = run
        if persisted.status in _TERMINAL_RUN_STATUSES and persisted.status != run.status:
            for field_name in WorkflowRun.model_fields:
                setattr(run, field_name, deepcopy(getattr(persisted, field_name)))
            return
        run.status = self.state_machine.transition(run.status, status)
        phase_by_status = {
            WorkflowStatus.WAITING_REVIEW: WorkflowProgressPhase.REVIEW,
            WorkflowStatus.RETRYING: WorkflowProgressPhase.RECOVERY,
            WorkflowStatus.COMPLETED: WorkflowProgressPhase.COMPLETED,
            WorkflowStatus.FAILED: WorkflowProgressPhase.FAILED,
            WorkflowStatus.CANCELLED: WorkflowProgressPhase.CANCELLED,
        }
        phase = phase_by_status.get(status)
        if phase is None and status == WorkflowStatus.RUNNING:
            if run.lifecycle_phase not in {
                WorkflowProgressPhase.PLANNING,
                WorkflowProgressPhase.GRAPH_BUILDING,
            }:
                phase = WorkflowProgressPhase.EXECUTING
        if phase is not None:
            run.lifecycle_phase = phase
            run.lifecycle_message = _LIFECYCLE_MESSAGES[phase]
        if status == WorkflowStatus.RUNNING:
            run.started_at = run.started_at or utc_now()
        run.updated_at = utc_now()

    def _transition_step(self, step: WorkflowStep, status: StepStatus) -> None:
        step.status = self.state_machine.transition(step.status, status)
        if status == StepStatus.RUNNING:
            step.started_at = step.started_at or utc_now()
        if status == StepStatus.COMPLETED:
            step.completed_at = step.completed_at or utc_now()


def build_default_runtime() -> WorkflowRuntime:
    """按环境变量装配默认运行时并登记原生与已安装插件；缺少数据库路径时抛出错误。"""
    agent_registry = AgentRegistry()
    workflow_registry = WorkflowRegistry()

    db_path = os.getenv("AGENTOS_WORKFLOW_DB_PATH", "").strip()
    workflow_store: WorkflowStore
    if not db_path:
        raise RuntimeError("Workflow database path is required outside test mode.")
    workflow_store = SQLiteWorkflowStore(db_path)

    runtime = WorkflowRuntime(
        agent_registry=agent_registry,
        workflow_registry=workflow_registry,
        workflow_store=workflow_store,
    )
    register_native_runtime(
        agent_registry=runtime.agent_registry,
        workflow_registry=runtime.workflow_registry,
    )
    runtime.plugin_manifests = register_installed_packs(
        agent_registry=runtime.agent_registry,
        workflow_registry=runtime.workflow_registry,
        capability_catalog=runtime.capability_catalog,
    )
    return runtime


__all__ = ["WorkflowRuntime", "build_default_runtime"]
