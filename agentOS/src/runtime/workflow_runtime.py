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
from contracts.identity import new_attempt_id, new_step_execution_id
from typing import Callable, Mapping, Optional
from uuid import uuid4

from service.agents import AgentRegistry
from support.acg.models import (
    RuntimeBlueprintSpec,
    promote_workflow_to_acg,
)
from components.auditor.governance.evaluation import WorkflowEvaluator
from components.mission_manager.store import WorkflowRegistry
from components.auditor.governance.review import ReviewManager
from components.mission_manager.state_machine import StateMachine
from components.mission_manager.service import MissionManager
from components.auditor.governance.trace import TraceStore
from components.auditor.decision_store import DecisionStore, SQLiteDecisionStore
from components.communicator import CommunicationBroker, CommunicatorService, ReliableMessage, SQLiteReliableCommunicationStore
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
from components.memory import MemoryService, StructuredMemoryEvent
from components.evolution.service import EvolutionService
from contracts.evolution import (
    EvolutionPolicyVersion,
    EvolutionProposal,
    Trajectory,
    TrajectoryEvaluation,
)
from components.memory.store import SQLiteMemoryStore
from contracts.memory import MemoryPolicy, MemoryType
from contracts.resource import BindingRequirement, ResourceType
from contracts.acg_lifecycle import AcgIdentityLifecyclePort
from contracts.planning import (
    TaskBindingPatch,
    TaskImplementationBinding,
    TaskPlan,
)
from components.resource.directory import ResourceDirectory, ResourceNotFoundError
from components.resource.service import ResourceService
from components.scheduler.service import SchedulerService
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
    MissionRecordState,
    RuntimeMissionRecord,
    Checkpoint,
    EvaluationRun,
    ReviewDecision,
    ReviewDecisionType,
    ReviewRecord,
    StepStatus,
    TraceEvent,
    TraceEventType,
    WorkflowDefinition,
    RuntimeRunRecord,
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
from components.planner.service import (
    apply_task_plan_patch,
)
from runtime.dependencies import PluginScopeError, PluginScopeResolver
from support.packs.registry import register_installed_packs
from adapters.model.native import register_native_runtime
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.stores.workflow_store import WorkflowStore
from support.stores._policy import acg_review_subject


logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
    WorkflowStatus.SUPERSEDED,
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


class ExecutionRuntime:
    """唯一 Execution Runtime 执行内核，串联规划、调度、节点执行、审核与恢复。"""

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
        mission_manager: Optional[MissionManager] = None,
        execution_adapter_factories: Optional[Mapping[str, ExecutionAdapterFactory]] = None,
        run_lock_manager: Optional[RunLockManager] = None,
        recovery_recipe_registry: Optional[object] = None,
        capability_catalog: CapabilityCatalog | None = None,
        resource_service: ResourceService | None = None,
        resource_directory: ResourceDirectory | None = None,
        scheduler_service: SchedulerService | None = None,
        evolution_service: EvolutionService | None = None,
        model_registry: ModelCompatibilityRegistry | None = None,
        plugin_manifests: tuple = (),
        identity_lifecycle: AcgIdentityLifecyclePort | None = None,
        require_planner_identity: bool = False,
    ):
        self.agent_registry = agent_registry or AgentRegistry()
        self.workflow_registry = workflow_registry or WorkflowRegistry()
        self.capability_catalog = capability_catalog or build_default_capability_catalog()
        if resource_directory is not None:
            directory_service = resource_directory.resource_service
            if resource_service is not None and directory_service is not resource_service:
                raise ValueError("ResourceDirectory must delegate to the injected ResourceService")
            self.resource_service = resource_service or directory_service
            self.resource_directory = resource_directory
        else:
            self.resource_service = resource_service or ResourceService()
            self.resource_directory = ResourceDirectory(self.resource_service)
        self.scheduler_service = scheduler_service or SchedulerService(
            resource_service=self.resource_service
        )
        self.evolution_service = evolution_service or EvolutionService()
        # 注册表只保存应用层已创建的模型适配器；Runtime 不在内部创建网络客户端。
        # 调用方可传入 bootstrap 产生的同一实例，使启动装配与工作流执行共享路由。
        self.model_registry = model_registry or ModelCompatibilityRegistry()
        self.plugin_manifests = tuple(plugin_manifests)
        self.identity_lifecycle = identity_lifecycle
        self.require_planner_identity = require_planner_identity
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
        self.reliable_communication_store = SQLiteReliableCommunicationStore(
            os.getenv("AGENTOS_COMMUNICATION_DB", "data/communication.sqlite3")
        )
        # 测试可临时设置该私有钩子，模拟进程在一个已提交边界后消失。它不属于构造
        # 参数、环境变量或公开 contracts，生产运行时始终保持 ``None``。
        self._fault_hook: Callable[[str], None] | None = None
        self.tool_runtime = tool_runtime
        self.review_manager = review_manager or ReviewManager(self.trace_store)
        self.evaluator = evaluator or WorkflowEvaluator()
        self.state_machine = StateMachine()
        self._model_runtime = None
        self.mission_manager = mission_manager or MissionManager(
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

    def create_mission(
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
    ) -> RuntimeMissionRecord:
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
        task = self.mission_manager.create_mission(
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
            mission_id=(self.identity_lifecycle.new_mission_id() if self.identity_lifecycle else None),
        )
        if self.identity_lifecycle is not None and task.recommended_workflow:
            recommended = self.workflow_registry.get(task.recommended_workflow)
            if recommended.effective_runtime_engine == "acg":
                self._flush_identity_outbox()
        return task

    async def start(
        self,
        mission_id: str,
        workflow_id: Optional[str] = None,
        review_mode: str = "auto",
        enabled_plugin_ids: Optional[list[str]] = None,
    ) -> RuntimeRunRecord:
        """为任务选择工作流并启动运行；持久化和同运行互斥由内部运行锁协调。"""
        _, run = self.prepare_run(
            mission_id=mission_id,
            workflow_id=workflow_id,
            review_mode=review_mode,
            enabled_plugin_ids=enabled_plugin_ids,
        )
        return await self.execute_prepared_run(run.run_id)

    def prepare_run(
        self,
        mission_id: str,
        workflow_id: Optional[str] = None,
        review_mode: str = "auto",
        *,
        idempotency_key: Optional[str] = None,
        idempotency_fingerprint: Optional[str] = None,
        enabled_plugin_ids: Optional[list[str]] = None,
    ) -> tuple[RuntimeMissionRecord, RuntimeRunRecord]:
        """在规划或节点执行前持久化可查询运行；幂等键冲突时抛出 ``ValueError``。"""

        if idempotency_key:
            existing = self.workflow_store.find_run_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.idempotency_fingerprint != idempotency_fingerprint:
                    raise ValueError("idempotency key conflicts with the workflow start request")
                return self.mission_manager.get_mission(existing.mission_id), existing

        task = self.mission_manager.get_mission(mission_id)
        if task.record_state is not MissionRecordState.ACTIVE:
            raise ValueError("mission must be active before preparing a new run")
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
        if is_acg and self.require_planner_identity and self.identity_lifecycle is None:
            raise ValueError(
                "production ACG execution requires the identity lifecycle adapter"
            )
        if self.identity_lifecycle is not None and is_acg:
            # A task may have been created against a legacy/default workflow and
            # explicitly rebound to ACG only when the run is prepared.
            self.workflow_store.save_mission(task)
            self._flush_identity_outbox()
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
        run = RuntimeRunRecord(
            **(
                {"runId": self.identity_lifecycle.new_run_id(task.mission_id)}
                if self.identity_lifecycle is not None and is_acg
                else {}
            ),
            missionId=task.mission_id,
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
        if (workflow.domain or task.domain).strip().lower() == "general":
            active_evolution = self.evolution_service.store.active()
            run.execution_state["evolutionPolicyVersion"] = active_evolution.version
            run.execution_state["evolutionPolicy"] = dict(active_evolution.policy)
        if is_acg:
            blueprint, task_plan, task_bindings = self._build_acg_blueprint(
                task,
                run,
                workflow,
            )
            self._validate_blueprint_agents(
                blueprint,
                domain=workflow.domain or task.domain,
                scope=scope,
            )
            self._sync_run_steps_to_acg(run, blueprint)
            compiler = ACGGraphCompiler()
            compiled_package = compiler.compile_package(blueprint, run_id=run.run_id)
            self._register_and_freeze_resources(
                run=run,
                workflow=workflow,
                scope=scope,
                binding_manifest=compiled_package.binding_manifest,
            )
            run.acg_blueprint = blueprint.model_dump(by_alias=True, mode="json")
            run.execution_state.update(
                {
                    "workflowVersion": workflow.version,
                    "graphId": blueprint.graph_id,
                    "sourceBlueprintVersion": blueprint.version,
                    "compiledACGPackage": compiled_package.model_dump(
                        by_alias=True, mode="json"
                    ),
                    "compiledPackageId": compiled_package.package_id,
                    "compiledPackageChecksum": compiled_package.checksum,
                    "compiledPackageVersion": compiled_package.package_version,
                    "compiledPackageBlueprintHash": compiled_package.blueprint_hash,
                    "compilerWarnings": list(compiled_package.compatibility_warnings),
                    **(
                        {
                            "taskPlanVersion": task_plan.plan_version,
                            "taskPlan": task_plan.model_dump(by_alias=True, mode="json"),
                            "taskBindings": [
                                item.model_dump(by_alias=True, mode="json")
                                for item in task_bindings
                            ],
                        }
                        if task_plan is not None
                        else {}
                    ),
                }
            )
            if self.identity_lifecycle is not None and task_plan is None:
                raise ValueError(
                    "identity-enabled ACG execution requires Planner output"
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
        if self.identity_lifecycle is not None and is_acg:
            self._flush_identity_outbox()
        logger.info(
            "run_prepared",
            extra={
                "missionId": task.mission_id,
                "runId": run.run_id,
                "workflowId": workflow.workflow_id,
                "phase": run.lifecycle_phase.value,
            },
        )
        return task, run

    async def execute_prepared_run(self, run_id: str) -> RuntimeRunRecord:
        """执行已持久化运行并保持终态不回退；插件范围失效时安全标记失败后继续抛错。"""

        run = self.workflow_store.get_run(run_id)
        if self._normalize_runtime_engine(run.runtime_engine) == "acg":
            if run.status == WorkflowStatus.WAITING_REVIEW:
                return run
            return await self._execute_acg(run)
        if run.status in _TERMINAL_RUN_STATUSES:
            return run

        task = self.mission_manager.get_mission(run.mission_id)
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
            self.mission_manager.mark_running(task)
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
                extra={"missionId": run.mission_id, "runId": run.run_id, "elapsedMs": int((monotonic() - started) * 1000)},
            )
            raise

    async def _execute_acg(
        self,
        run: RuntimeRunRecord,
        *,
        state: ACGExecutionState | None = None,
        command: ExecutionResumeCommand | None = None,
    ) -> RuntimeRunRecord:
        """执行或续跑融合 ACG，并把图状态投影为既有运行合同。

        图、值仓库和检查点均只传递引用型状态。此方法是 Runtime 唯一的 ACG 接线点：
        通信、记忆、审计、Agent 适配由 ``ACGNodeRunner`` 组合，RuntimeRunRecord 只保存
        生命周期、步骤状态、摘要和引用，绝不写入 Agent 的完整输出正文。
        """
        if run.status in _TERMINAL_RUN_STATUSES:
            return run
        task = self.mission_manager.get_mission(run.mission_id)
        workflow = self._workflow_for_run(run)
        blueprint_data = run.acg_blueprint
        if not isinstance(blueprint_data, dict):
            raise ExecutionEngineMigratingError(run.run_id)
        blueprint = RuntimeBlueprintSpec.model_validate(blueprint_data)
        raw_package = run.execution_state.get("compiledACGPackage")
        if not isinstance(raw_package, dict):
            raise ExecutionEngineMigratingError(run.run_id)
        from contracts.compiled_acg import CompiledACGPackage

        compiled_package = CompiledACGPackage.model_validate(raw_package)
        graph = ACGGraphCompiler().compile(
            blueprint,
            run_id=run.run_id,
            package=compiled_package,
        )
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
        ledger = self.provenance_store.load_ledger(run_id=run.run_id, mission_id=task.mission_id)
        self._validate_acg_state_references(run=run, state=execution_state, ledger=ledger)
        runner = self._build_acg_runner(
            task=task,
            run=run,
            workflow=workflow,
            graph=graph,
            state=execution_state,
            ledger=ledger,
        )
        scheduled_runner = self._ready_node_runner(run=run, runner=runner)
        run.execution_state["engineMigration"] = "langgraph_fused_v1"
        run.execution_state["graphId"] = blueprint.graph_id
        run.execution_state["compiledPackageId"] = compiled_package.package_id
        run = self._set_run_lifecycle(
            run,
            status=WorkflowStatus.RUNNING,
            phase=WorkflowProgressPhase.EXECUTING,
            message=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.EXECUTING],
            set_started_at=True,
        )
        if self.identity_lifecycle is not None:
            self.mission_manager.mark_running_for_new_run(task, run_id=run.run_id)
        else:
            self.mission_manager.mark_running(task)
        try:
            stream = (
                graph.astream(execution_state, scheduled_runner)
                if command is None
                else graph.astream_after_resume(execution_state, command, scheduled_runner)
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
            self.mission_manager.mark_completed(task)
            self.trace_store.append(run, TraceEventType.RUN_COMPLETED, observation="ACG workflow completed")
            self.workflow_store.save_run(run)
            if self.identity_lifecycle is not None:
                self._flush_identity_outbox()
            return run
        except ExecutionInterrupt as interrupt:
            self._persist_acg_state(run, execution_state)
            checkpoint_id = self._save_acg_checkpoint(run, execution_state)
            self._persist_acg_state(run, execution_state)
            subject_type, subject_id = acg_review_subject(interrupt.payload)
            blueprint = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)
            subject_node = blueprint.get_node(subject_id)
            expected_node_type = "step" if subject_type == "step" else "control"
            if subject_node.node_type.value != expected_node_type:
                raise ValueError(
                    f"ACG review subject type does not match blueprint node: {subject_id}"
                )
            if subject_type == "step":
                step = run.get_step(subject_id)
                step.status = StepStatus.WAITING_REVIEW
            run.current_step_id = subject_id
            self.trace_store.append_execution_event(run, {"type": "interrupted", **interrupt.payload})
            self.trace_store.append_execution_event(run, {"type": "checkpoint_created", "checkpointId": checkpoint_id})
            run = self._set_run_lifecycle(
                run,
                status=WorkflowStatus.WAITING_REVIEW,
                phase=WorkflowProgressPhase.REVIEW,
                message=_LIFECYCLE_MESSAGES[WorkflowProgressPhase.REVIEW],
            )
            self.mission_manager.mark_waiting_review(task)
            self.workflow_store.save_run(run)
            return run
        except Exception as exc:
            from components.recovery import RecoveryService, failure_event_from_exception

            failure = failure_event_from_exception(
                exc,
                subject_ref=(
                    f"run:{run.run_id}:step:{execution_state.current_step_id}"
                    if execution_state.current_step_id
                    else f"run:{run.run_id}"
                ),
            )
            recovery_plan = RecoveryService().propose(failure)
            run.execution_state.setdefault("failureEvents", []).append(
                failure.model_dump(by_alias=True, mode="json")
            )
            run.execution_state["recoveryOutcome"] = {
                "failureId": failure.failure_id,
                "source": failure.source.value,
                "reasonCode": failure.reason_code,
                "action": recovery_plan.strategy.value,
                "status": "proposed",
            }
            self.workflow_store.save_run(run)
            await self.fail_run_safely(
                run.run_id,
                error_code="acg_execution_failed",
                error_message=self._safe_error_message(exc),
            )
            if self.identity_lifecycle is not None:
                self._flush_identity_outbox()
            raise

    def _ready_node_runner(self, *, run: RuntimeRunRecord, runner: ACGNodeRunner):
        """Decorate NodeRunner after Executor readiness with binding and lease coordination."""
        raw_requirements = run.execution_state.get("bindingRequirements")
        if not isinstance(raw_requirements, dict):
            return runner
        # A recreated Runtime resumes an already-prepared run without repeating
        # prepare_run. Re-project the current registry through the authoritative
        # resource service so every resource starts UNKNOWN and becomes usable
        # only after this live registration heartbeat.
        for agent in self.agent_registry.all():
            self.resource_directory.register_agent(agent.profile)

        async def execute(step_id: str, state: ACGExecutionState):
            payload = raw_requirements.get(step_id)
            if not isinstance(payload, dict):
                raise ValueError(f"READY step has no binding requirement: {step_id}")
            requirement = BindingRequirement.model_validate(payload)
            step = run.get_step(step_id)
            attempt_number = max(step.attempt, step.retry_count) + 1
            loop_path = tuple(state.loop_paths.get(step_id, ()))
            loop_key = ".".join(str(item) for item in loop_path) or "root"
            attempts = run.execution_state.setdefault("attemptIds", {})
            attempt_key = f"{step_id}:{attempt_number}:{loop_key}"
            attempt_id = str(attempts.setdefault(
                attempt_key,
                new_attempt_id() if self.identity_lifecycle is not None
                else f"{run.run_id}:{step_id}:{step.attempt}:{loop_key}",
            ))
            while True:
                decision = self.scheduler_service.schedule_ready(
                    run_id=run.run_id,
                    step_id=step_id,
                    attempt_id=attempt_id,
                    requirement=requirement,
                )
                if decision.status == "allocated":
                    break
                await asyncio.sleep(0.01)
            assert decision.binding is not None and decision.lease is not None
            selected_agent = self.agent_registry.resolve_by_id(
                decision.binding.resource_id,
                allowed_agent_ids=(run.execution_scope.agent_ids if run.execution_scope else None),
            )
            runner.agents[step_id] = selected_agent
            step_execution_id = (
                run.execution_state.setdefault("stepExecutionIds", {}).setdefault(
                    attempt_key,
                    new_step_execution_id()
                    if self.identity_lifecycle is not None
                    else f"execution:{attempt_id}",
                )
            )
            profile = selected_agent.profile
            base_events = [
                self._lifecycle_event(
                    f"attempt.ensured:{attempt_id}", "attempt.ensured", run.run_id,
                    {"runId": run.run_id, "missionId": run.mission_id, "stepId": step_id,
                     "attemptId": attempt_id, "attemptNumber": attempt_number},
                ),
                self._lifecycle_event(
                    f"resource.bound:{attempt_id}", "resource.bound", attempt_id,
                    {"attemptId": attempt_id,
                     "binding": decision.binding.model_dump(by_alias=True, mode="json"),
                     "agentId": str(profile.agent_id or decision.binding.resource_id),
                     "modelId": str(profile.model_name or "runtime-default")},
                ),
                self._lifecycle_event(
                    f"step.started:{step_execution_id}", "step.started", step_execution_id,
                    {"runId": run.run_id, "attemptId": attempt_id, "stepId": step_id,
                     "stepExecutionId": step_execution_id},
                ),
            ]
            run.execution_state.setdefault("executionBindings", {})[step_id] = (
                decision.binding.model_dump(by_alias=True, mode="json")
            )
            run.execution_state.setdefault("schedulingDecisions", []).append(
                {
                    "stepId": step_id,
                    "attemptId": attempt_id,
                    "candidates": [
                        item.model_dump(by_alias=True, mode="json") for item in decision.candidates
                    ],
                    "binding": decision.binding.model_dump(by_alias=True, mode="json"),
                    "lease": decision.lease.model_dump(by_alias=True, mode="json"),
                }
            )
            run.execution_state.setdefault("resourceBindings", {})[step_id] = (
                decision.binding.resource_id
            )
            base_events = self._reuse_persisted_lifecycle_events(base_events)
            self.workflow_store.save_run_with_events(run, base_events)
            self._flush_identity_outbox()
            try:
                result = await runner(step_id, state)
                self.workflow_store.save_run_with_events(run, [self._lifecycle_event(
                    f"step.succeeded:{step_execution_id}", "step.succeeded", step_execution_id,
                    {"runId": run.run_id, "attemptId": attempt_id,
                     "stepExecutionId": step_execution_id,
                     "result": self._safe_lifecycle_result(result)},
                )])
                self._flush_identity_outbox()
                return result
            except asyncio.CancelledError:
                reason = "ACG superstep cancelled after sibling failure"
                self.workflow_store.save_run_with_events(run, [self._lifecycle_event(
                    f"step.cancelled:{step_execution_id}", "step.cancelled", step_execution_id,
                    {"runId": run.run_id, "attemptId": attempt_id,
                     "stepExecutionId": step_execution_id, "reason": reason},
                )])
                self._flush_identity_outbox()
                raise
            except Exception as exc:
                self.workflow_store.save_run_with_events(run, [self._lifecycle_event(
                    f"step.failed:{step_execution_id}", "step.failed", step_execution_id,
                    {"runId": run.run_id, "attemptId": attempt_id,
                     "stepExecutionId": step_execution_id, "reason": self._safe_error_message(exc)},
                )])
                self._flush_identity_outbox()
                raise
            finally:
                released = self.scheduler_service.release(decision.lease.lease_id)
                if released:
                    for scheduling_item in reversed(
                        run.execution_state.get("schedulingDecisions") or []
                    ):
                        lease = scheduling_item.get("lease") if isinstance(scheduling_item, dict) else None
                        if isinstance(lease, dict) and lease.get("leaseId") == decision.lease.lease_id:
                            lease["status"] = "released"
                            break

        execute.prepare_superstep = runner.prepare_superstep
        return execute

    @staticmethod
    def _lifecycle_event(event_id: str, event_type: str, aggregate_id: str, payload: dict) -> dict:
        return {"eventId": event_id, "eventType": event_type, "aggregateId": aggregate_id, "payload": payload}

    @staticmethod
    def _safe_lifecycle_result(result: dict) -> dict:
        allowed = {
            "commitId", "outputRef", "outputSummary", "contextRef", "memoryRef",
            "traceRef", "auditDecisionRef", "auditOutcome", "nodeExecution",
            "communicationRefs", "evidenceRefs", "provenanceEvents",
        }
        return {key: result[key] for key in allowed if result.get(key) is not None}

    def _flush_identity_outbox(self) -> None:
        if self.identity_lifecycle is None:
            return
        from runtime.v2.reconciliation import IdentityProjectionReconciler

        report = IdentityProjectionReconciler(self.identity_lifecycle).reconcile_workflow_store(
            self.workflow_store,
            limit=200,
        )
        if report.failures:
            raise RuntimeError("identity inbox consumption failed: " + "; ".join(report.failures))

    def _reuse_persisted_lifecycle_events(self, events: list[dict]) -> list[dict]:
        """Reuse the first committed event body during an idempotent attempt resume.

        Scheduler leases carry timestamps and scores, so rebuilding the same attempt
        can otherwise produce a different payload for an already persisted event ID.
        The store remains authoritative: a different payload is still rejected by
        ``save_run_with_events`` when no prior event exists in the outbox.
        """
        existing = {
            str(item.get("event_id")): item
            for item in self.workflow_store.list_outbox(limit=100000)
            if isinstance(item, dict) and item.get("event_id")
        }
        normalized: list[dict] = []
        for event in events:
            prior = existing.get(str(event.get("eventId")))
            if prior is None:
                normalized.append(event)
                continue
            payload = prior.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = None
            normalized.append({
                "eventId": prior["event_id"],
                "eventType": prior["event_type"],
                "aggregateId": prior["aggregate_id"],
                "payload": payload if isinstance(payload, dict) else event.get("payload", {}),
            })
        return normalized

    @staticmethod
    def _validate_acg_resume_identity(
        *,
        run: RuntimeRunRecord,
        workflow: WorkflowDefinition,
        blueprint: RuntimeBlueprintSpec,
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
        run: RuntimeRunRecord,
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
            mission_id=run.mission_id,
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
        task: RuntimeMissionRecord,
        run: RuntimeRunRecord,
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
                mission_id=task.mission_id,
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
            reliable_communication_store=self.reliable_communication_store,
            compiled_package=graph.compiled_package,
            skill_manifest=graph.compiled_package.skill_manifest,
            memory_manifest=graph.compiled_package.memory_manifest,
            evidence_manifest=graph.compiled_package.evidence_manifest,
            agent_invoker=AgentInvocationAdapter(
                registry=(self.agent_registry.scoped(allowed_agent_ids) if allowed_agent_ids is not None else self.agent_registry)
            ),
            decision_store=self.decision_store,
            fault_hook=self._fault_hook,
        )

    def _project_acg_event(self, run: RuntimeRunRecord, state: ACGExecutionState, event: dict) -> None:
        """投影单个图事件与步骤状态；事件正文只含步骤标识、摘要或引用。"""
        event_type = event.get("type")
        commit_id = event.get("commitId")
        node_trace_batch: list[TraceEvent] = []
        if event_type == "node_completed" and isinstance(commit_id, str) and self._is_projected_commit(run, commit_id):
            # Trace 已经确认过该提交，说明上次在状态保存前中断。重放时不能再次追加
            # 步骤成功、记忆访问或通信血缘事件；但可变 WorkflowStep 投影仍必须与
            # 提交事实对齐，否则 Run 会在完成时残留 RUNNING 步骤。
            step_id = str(event.get("stepId"))
            step = run.get_step(step_id)
            step.status = StepStatus.COMPLETED
            step.completed_at = step.completed_at or utc_now()
            run.current_step_id = step_id
            run.completed_step_ids = list(state.completed_step_ids)
            run.active_step_ids = list(state.active_step_ids)
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
            self._project_completed_phase_capsules(run=run, state=state)
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
        # 已持久化的 skippedStepIds 补齐 RuntimeRunRecord 的可见步骤状态，供查询、
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
        memory_event = event.get("memoryEvent")
        if isinstance(memory_event, dict) and memory_event:
            projected = StructuredMemoryEvent.model_validate(memory_event).model_dump(
                by_alias=True, mode="json"
            )
            if event_type == "node_completed":
                node_trace_batch.append(self.trace_store.build_event(
                    run,
                    event_type=TraceEventType.DATA_PRODUCED,
                    step_id=event.get("stepId"),
                    observation="Structured memory event projected",
                    payload=projected,
                ))
            else:
                self.trace_store.append(
                    run,
                    TraceEventType.DATA_PRODUCED,
                    step_id=event.get("stepId"),
                    observation="Structured memory event projected",
                    payload=projected,
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

    def _project_completed_phase_capsules(
        self,
        *,
        run: RuntimeRunRecord,
        state: ACGExecutionState,
    ) -> None:
        """Persist one deterministic capsule when every step in a planning stage completed."""
        if not isinstance(run.acg_blueprint, dict):
            return
        blueprint = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)
        stages: dict[str, list[str]] = {}
        for node in blueprint.step_nodes():
            stage = str(node.metadata.get("planningStage") or "execution")
            stages.setdefault(stage, []).append(node.node_id)
        completed = set(state.completed_step_ids)
        capsule_refs = run.execution_state.setdefault("phaseCapsuleRefs", {})
        if not isinstance(capsule_refs, dict):
            raise ValueError("phaseCapsuleRefs must be an object")
        task = self.mission_manager.get_mission(run.mission_id)
        raw_constraints = task.input.get("constraints")
        constraints = raw_constraints if isinstance(raw_constraints, list) else []
        raw_questions = task.input.get("openQuestions")
        open_questions = raw_questions if isinstance(raw_questions, list) else []
        service = MemoryService(store=self.memory_store)
        for stage, step_ids in stages.items():
            if not set(step_ids) <= completed:
                continue
            source_refs = [
                state.memory_refs[step_id]
                for step_id in step_ids
                if state.memory_refs.get(step_id) not in {None, "memory:none"}
            ]
            if not source_refs:
                continue
            capsule = service.create_phase_capsule(
                run_id=run.run_id,
                phase_id=stage,
                source_memory_refs=source_refs,
                goal=task.title,
                constraints=constraints,
                open_questions=open_questions,
            )
            previous = capsule_refs.get(stage)
            if previous is not None and previous != capsule.capsule_id:
                raise ValueError(f"phase {stage} already points to a different capsule")
            if previous == capsule.capsule_id:
                continue
            capsule_refs[stage] = capsule.capsule_id
            self.trace_store.append(
                run,
                TraceEventType.DATA_PRODUCED,
                observation="Phase capsule persisted",
                payload={
                    "kind": "phase_capsule",
                    "phaseId": stage,
                    "capsuleRef": capsule.capsule_id,
                    "sourceMemoryRefs": list(capsule.source_memory_refs),
                    "evidenceRefs": list(capsule.evidence_refs),
                    "tokenCount": capsule.token_count,
                },
            )

    @staticmethod
    def _is_projected_commit(run: RuntimeRunRecord, commit_id: str) -> bool:
        """通过既有步骤完成 Trace 判断提交是否已被投影，不额外保存正文状态。"""
        return any(
            event.event_type == TraceEventType.STEP_SUCCEEDED
            and event.payload.get("commitId") == commit_id
            for event in run.trace
        )

    def _persist_acg_state(self, run: RuntimeRunRecord, state: ACGExecutionState) -> None:
        """保存只含摘要和引用的图投影，禁止写入 value store 中的完整正文。"""
        state_data = state.model_dump(by_alias=True, mode="json")
        run.execution_state.update(state_data)
        run.completed_step_ids = list(state.completed_step_ids)
        run.active_step_ids = list(state.active_step_ids)
        self.workflow_store.save_run(run)

    def _save_acg_checkpoint(self, run: RuntimeRunRecord, state: ACGExecutionState) -> str:
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
        # Enriched planner graphs may complete support/control projections after
        # the last value-producing step. Select the latest committed output,
        # not merely the last completed node identifier.
        for final_step_id in reversed(state.completed_step_ids):
            output_ref = state.output_refs.get(final_step_id)
            if output_ref:
                return {"outputRef": output_ref}
        return {}

    def _validate_blueprint_agents(
        self,
        blueprint: RuntimeBlueprintSpec,
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
        run: RuntimeRunRecord,
        workflow: WorkflowDefinition,
        scope: RunExecutionScope,
        binding_manifest,
    ) -> None:
        """登记当前可见 Agent，并将每个 ACG Step 选择结果冻结到运行状态。"""
        for agent in self.agent_registry.all():
            self.resource_directory.register_agent(agent.profile)
        bindings: dict[str, str] = {}
        requirements: dict[str, dict[str, object]] = {}
        model_bindings: dict[str, dict[str, str] | None] = {}
        for step in run.steps:
            rule = binding_manifest.for_step(step.step_id)
            required_capabilities = list(rule.required_capabilities)
            if not required_capabilities:
                raise ValueError(
                    f"BindingManifest has no capability requirement: {step.step_id}"
                )
            allowed_agent_ids = list(scope.agent_ids)
            if rule.allowed_resource_ids:
                allowed_agent_ids = [
                    item for item in allowed_agent_ids
                    if item in set(rule.allowed_resource_ids)
                ]
            try:
                selected = self.resource_directory.resolve_agent(
                    domain=rule.domain or workflow.domain,
                    agent_name=step.agent_name,
                    capability=required_capabilities[0],
                    allowed_agent_ids=allowed_agent_ids,
                )
            except ResourceNotFoundError as exc:
                raise ValueError(f"ACG step has no eligible resource: {step.step_id}") from exc
            bindings[step.step_id] = selected.agent_id
            requirement = BindingRequirement(
                requiredCapabilities=required_capabilities,
                domain=rule.domain or workflow.domain,
                resourceTypes=[ResourceType.AGENT],
                allowedResourceIds=allowed_agent_ids,
                preferences={"resourceId": selected.agent_id},
                policyMetadata={
                    "source": "compiled-binding-manifest",
                    "stepId": step.step_id,
                    "agentNodeIds": list(rule.agent_node_ids),
                    "maxConcurrency": rule.max_concurrency,
                    "compatibilitySource": rule.compatibility_source,
                },
            )
            requirements[step.step_id] = requirement.model_dump(by_alias=True, mode="json")
            agent = self.agent_registry.resolve_by_id(
                selected.agent_id,
                allowed_agent_ids=scope.agent_ids,
            )
            model_bindings[step.step_id] = self._freeze_model_binding(
                step_id=step.step_id,
                profile=agent.profile,
            )
        run.execution_state["resourceBindings"] = bindings
        run.execution_state["bindingRequirements"] = requirements
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
        task: RuntimeMissionRecord,
        run: RuntimeRunRecord,
        workflow: WorkflowDefinition,
    ) -> tuple[
        RuntimeBlueprintSpec,
        TaskPlan | None,
        tuple[TaskImplementationBinding, ...],
    ]:
        """Resolve one complete ACG production package.

        Identity-enabled production accepts either an explicit Blueprint plus
        TaskPlan/bindings, or Planner output. The final workflow promotion branch
        is reserved for the identity-free Execution Runtime execution-kernel harness and does
        not manufacture semantic identities from WorkflowStep definitions.
        """
        provided = run.input.get("acgBlueprint") or (run.acg_blueprint if run.acg_blueprint else None)
        if isinstance(provided, dict) and provided.get("nodes"):
            blueprint = RuntimeBlueprintSpec.model_validate(provided)
            if not blueprint.mission_id:
                blueprint = blueprint.model_copy(deep=True, update={"mission_id": task.mission_id})
            raw_plan = run.input.get("taskPlan")
            raw_bindings = run.input.get("taskBindings")
            if not isinstance(raw_plan, dict) or not isinstance(raw_bindings, list):
                raise ValueError(
                    "explicit ACG Blueprint requires taskPlan and taskBindings"
                )
            if isinstance(raw_plan, dict) and isinstance(raw_bindings, list):
                task_plan = TaskPlan.model_validate(raw_plan)
                task_bindings = tuple(
                    TaskImplementationBinding.model_validate(item)
                    for item in raw_bindings
                )
            if task_plan.mission_id != task.mission_id:
                raise ValueError("TaskPlan missionId does not match RuntimeMissionRecord")
            binding_keys = [item.plan_node_key for item in task_bindings]
            binding_nodes = [item.acg_node_id for item in task_bindings]
            plan_keys = {node.key for node in task_plan.nodes}
            executable_ids = {node.node_id for node in blueprint.step_nodes()}
            if (
                len(set(binding_keys)) != len(binding_keys)
                or len(set(binding_nodes)) != len(binding_nodes)
                or set(binding_keys) != plan_keys
                or set(binding_nodes) != executable_ids
            ):
                raise ValueError(
                    "Blueprint bindings must cover the complete TaskPlan and executable Blueprint"
                )
            return blueprint, task_plan, task_bindings

        planning_mode = str(run.input.get("planningMode") or "").strip().lower()
        force_dynamic = (
            workflow.is_native_bootstrap
            or bool(run.input.get("forceDynamicPlanning"))
            or planning_mode == "dynamic"
        )
        use_planner = (
            self.require_planner_identity
            or self.identity_lifecycle is not None
            or force_dynamic
            or bool(run.input.get("usePlanner"))
            or not workflow.steps
        )
        if use_planner:
            intent_text = str(
                run.input.get("userIntent")
                or run.input.get("intent")
                or task.title
                or workflow.description
            )
            planning_engine = self._planning_engine_for_run(run)
            plan = planning_engine.plan(
                mission_id=task.mission_id,
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
                required_capabilities=workflow.required_capabilities,
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
            blueprint = plan.blueprint
            if workflow.review_capability:
                review_nodes = [
                    node
                    for node in blueprint.step_nodes()
                    if node.capability == workflow.review_capability
                ]
                if len(review_nodes) != 1:
                    raise ValueError(
                        "workflow review capability must resolve to exactly one ACG step: "
                        f"{workflow.review_capability}"
                    )
                review_nodes[0].review_required = True
                review_nodes[0].metadata["reviewBarrier"] = True
                blueprint.metadata["reviewCapability"] = workflow.review_capability
            return blueprint, plan.task_plan, plan.task_bindings

        blueprint = promote_workflow_to_acg(workflow, mission_id=task.mission_id)
        return blueprint, None, ()

    def _sync_run_steps_to_acg(
        self,
        run: RuntimeRunRecord,
        blueprint: RuntimeBlueprintSpec,
    ) -> None:
        """让 RuntimeRunRecord 的步骤列表与最终 ACG 蓝图保持一致。"""
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
                memory_policy = dict(memory_policy)
                evolved_budget = (run.execution_state.get("evolutionPolicy") or {}).get(
                    "budget_adjustment:memory_token_budget"
                )
                if evolved_budget is not None:
                    if (
                        not isinstance(evolved_budget, (int, float))
                        or isinstance(evolved_budget, bool)
                        or evolved_budget <= 0
                    ):
                        raise ValueError("active evolution memory token budget must be positive")
                    memory_policy["tokenBudget"] = int(evolved_budget)
                    run.execution_state.setdefault("appliedEvolutionPolicy", {})[
                        "memoryTokenBudget"
                    ] = int(evolved_budget)
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

    def _transition_run_if_needed(self, run: RuntimeRunRecord, status: WorkflowStatus) -> None:
        if run.status != status:
            self._transition_run(run, status)

    def get_status(self, run_id: str) -> RuntimeRunRecord:
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
    ) -> RuntimeRunRecord:
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
        run: RuntimeRunRecord,
        *,
        status: WorkflowStatus | None = None,
        phase: WorkflowProgressPhase | None = None,
        message: str | None = None,
        error: object = _ERROR_UNSET,
        set_started_at: bool = False,
    ) -> RuntimeRunRecord:
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
    ) -> RuntimeRunRecord:
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
            self.mission_manager.mark_failed(run.mission_id)
        except Exception:
            logger.exception(
                "Failed to align task status after run failure",
                extra={"missionId": run.mission_id, "runId": run.run_id},
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
        run: RuntimeRunRecord,
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
                    "missionId": run.mission_id,
                    "runId": run.run_id,
                    "workflowId": run.workflow_id,
                    "phase": run.lifecycle_phase.value if run.lifecycle_phase else None,
                },
            )
        return closed

    @staticmethod
    def _normalize_waiting_review_after_restart(run: RuntimeRunRecord) -> bool:
        """Restore the persisted review subject without inventing a WorkflowStep."""

        changed = False
        if (run.runtime_engine or "").strip().lower() == "acg":
            subject_type, subject_id = acg_review_subject(
                run.execution_state.get("reviewPayload")
            )
            if run.current_step_id != subject_id:
                run.current_step_id = subject_id
                changed = True
            if subject_type == "step":
                step = run.get_step(subject_id)
                if step.status != StepStatus.WAITING_REVIEW:
                    step.status = StepStatus.WAITING_REVIEW
                    changed = True
        else:
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

    def _fail_interrupted_run_after_restart(self, run: RuntimeRunRecord) -> None:
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
            self.mission_manager.mark_failed(run.mission_id)
        except Exception:
            logger.exception(
                "Failed to align task status after interrupted run",
                extra={"missionId": run.mission_id, "runId": run.run_id},
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

    def _protected_execution_references(self, run: RuntimeRunRecord) -> set[str]:
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

    def propose_evolution_from_run(
        self, run_id: str
    ) -> tuple[Trajectory, TrajectoryEvaluation, EvolutionProposal]:
        """从一个真实完成运行投影轨迹并生成待人工审核的演化提案。"""
        run = self.workflow_store.get_run(run_id)
        if run.status is not WorkflowStatus.COMPLETED:
            raise ValueError("only a completed workflow run can produce an evolution proposal")
        ledger = self.provenance_store.load_ledger(run_id=run.run_id, mission_id=run.mission_id)
        return self.evolution_service.propose_from_run(
            run,
            provenance_events=ledger.trace_events(),
        )

    def approve_evolution_proposal(
        self, proposal_id: str, *, approved_by: str
    ) -> EvolutionPolicyVersion:
        """审核一个已持久化提案并以 CAS 创建新的 General 策略版本。"""
        if not approved_by.strip():
            raise ValueError("evolution proposal reviewer is required")
        proposal = self.evolution_service.store.get_proposal(proposal_id)
        return self.evolution_service.approve(proposal, approved_by=approved_by.strip())

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

    async def apply_review(self, decision: ReviewDecision) -> RuntimeRunRecord:
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

        Patch bodies live in ``ExecutionValueStore``; RuntimeRunRecord and the
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
            blueprint = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)
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
                    runId=str(previous.get("newRunId") or "") or None,
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

            task = self.mission_manager.get_mission(run.mission_id)
            workflow = self._workflow_for_run(run)
            scope = run.execution_scope
            if scope is None:
                raise ValueError("graph patch requires a frozen execution scope")
            self._validate_blueprint_agents(
                outcome.blueprint,
                domain=workflow.domain or task.domain,
                scope=scope,
            )
            if self.identity_lifecycle is None:
                raise ValueError(
                    "graph patch requires the identity lifecycle adapter"
                )
            old_step_ids = {step.step_id for step in run.steps}
            raw_plan = run.execution_state.get("taskPlan")
            raw_bindings = run.execution_state.get("taskBindings")
            if not isinstance(raw_plan, dict) or not isinstance(raw_bindings, list):
                raise ValueError("graph patch requires persisted Planner identity data")
            current_plan = TaskPlan.model_validate(raw_plan)
            active_old_step_ids = {
                node.node_id for node in blueprint.step_nodes()
                if str(node.metadata.get("lifecycleStatus", "active")).lower() != "retired"
            }
            active_new_step_ids = {
                node.node_id for node in outcome.blueprint.step_nodes()
                if str(node.metadata.get("lifecycleStatus", "active")).lower() != "retired"
            }
            semantic_execution_change = active_old_step_ids != active_new_step_ids
            if semantic_execution_change and patch.task_plan_patch is None:
                raise ValueError(
                    "executable Graph Patch changes require Planner TaskPlanPatch"
                )
            if not semantic_execution_change and (
                patch.task_plan_patch is not None
                or patch.task_binding_patch is not None
            ):
                raise ValueError(
                    "pure control Graph Patch cannot change TaskPlan or SemanticTask bindings"
                )
            if patch.task_plan_patch is not None:
                next_plan = apply_task_plan_patch(current_plan, patch.task_plan_patch)
            else:
                next_plan = current_plan
            binding_patch = patch.task_binding_patch
            added_step_ids = active_new_step_ids - active_old_step_ids
            if added_step_ids and binding_patch is None:
                raise ValueError("new executable Graph Patch nodes require TaskBindingPatch")
            base_bindings = tuple(
                TaskImplementationBinding.model_validate(item)
                for item in raw_bindings
            )
            removed_plan_keys = (
                set(patch.task_plan_patch.retire_keys)
                | set(patch.task_plan_patch.replace_keys)
                if patch.task_plan_patch is not None
                else set()
            )
            next_bindings = tuple(
                item for item in base_bindings
                if item.plan_node_key not in removed_plan_keys
                and item.acg_node_id in active_new_step_ids
            ) + (binding_patch.bindings if binding_patch is not None else ())
            if len({item.plan_node_key for item in next_bindings}) != len(next_bindings):
                raise ValueError("Graph Patch contains duplicate semantic bindings")
            if len({item.acg_node_id for item in next_bindings}) != len(next_bindings):
                raise ValueError("Graph Patch contains duplicate executable bindings")
            if {item.plan_node_key for item in next_bindings} != {
                node.key for node in next_plan.nodes
            }:
                raise ValueError("Graph Patch bindings must cover the complete revised TaskPlan")
            if {item.acg_node_id for item in next_bindings} != active_new_step_ids:
                raise ValueError(
                    "Graph Patch bindings must cover every active executable node"
                )

            new_run_id = (
                self.identity_lifecycle.new_run_id(task.mission_id)
            )
            new_payload = run.model_dump(by_alias=True, mode="json")
            new_payload.update({
                "runId": new_run_id,
                "status": WorkflowStatus.PENDING.value,
                "lifecyclePhase": WorkflowProgressPhase.UNDERSTANDING.value,
                "lifecycleMessage": _LIFECYCLE_MESSAGES[WorkflowProgressPhase.UNDERSTANDING],
                "startedAt": None,
                "currentStepId": None,
                "output": {},
                "steps": [],
                "checkpoints": [],
                "trace": [],
                "error": None,
                "completedStepIds": [],
                "activeStepIds": [],
                "acgBlueprint": outcome.blueprint.model_dump(by_alias=True, mode="json"),
                "createdAt": utc_now().isoformat(),
                "updatedAt": utc_now().isoformat(),
            })
            new_run = RuntimeRunRecord.model_validate(new_payload)
            self._sync_run_steps_to_acg(new_run, outcome.blueprint)
            for agent in self.agent_registry.all():
                self.resource_directory.register_agent(agent.profile)
            bindings = dict(run.execution_state.get("resourceBindings") or {})
            requirements = dict(run.execution_state.get("bindingRequirements") or {})
            for step in new_run.steps:
                if step.step_id in old_step_ids:
                    continue
                selected = self.resource_directory.resolve_agent(
                    domain=workflow.domain,
                    agent_name=step.agent_name,
                    capability=step.capability,
                    allowed_agent_ids=scope.agent_ids,
                )
                bindings[step.step_id] = selected.agent_id
                requirements[step.step_id] = BindingRequirement(
                    requiredCapabilities=[
                        step.capability or f"agent:{step.agent_name.lower()}"
                    ],
                    domain=workflow.domain,
                    resourceTypes=[ResourceType.AGENT],
                    allowedResourceIds=list(scope.agent_ids),
                    preferences={"resourceId": selected.agent_id},
                    policyMetadata={"source": "graph-patch", "stepId": step.step_id},
                ).model_dump(by_alias=True, mode="json")

            patch_uri = self.execution_value_store.put_graph_patch(
                run_id=new_run.run_id,
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
            applied_metadata[-1] = {
                **applied_metadata[-1],
                "patchRef": patch_uri,
                "sourceRunId": run.run_id,
                "newRunId": new_run.run_id,
            }
            outcome.blueprint.metadata["appliedGraphPatches"] = applied_metadata
            new_run.acg_blueprint = outcome.blueprint.model_dump(by_alias=True, mode="json")
            new_run.execution_state.update({
                "resourceBindings": bindings,
                "bindingRequirements": requirements,
                "sourceBlueprintVersion": outcome.blueprint.version,
                "graphVersion": outcome.blueprint.version,
                "taskPlanVersion": next_plan.plan_version,
                "taskPlan": next_plan.model_dump(by_alias=True, mode="json"),
                "taskBindings": [
                    item.model_dump(by_alias=True, mode="json") for item in next_bindings
                ],
                "parentRunId": run.run_id,
                "supersedesRunId": run.run_id,
                "sourcePatchId": patch.patch_id,
                "graphPatchRefs": [patch_uri],
            })
            compiled_package = ACGGraphCompiler().compile_package(
                outcome.blueprint, run_id=new_run.run_id
            )
            new_run.execution_state.update({
                "compiledACGPackage": compiled_package.model_dump(
                    by_alias=True, mode="json"
                ),
                "compiledPackageId": compiled_package.package_id,
                "compiledPackageChecksum": compiled_package.checksum,
                "compiledPackageVersion": compiled_package.package_version,
                "compiledPackageBlueprintHash": compiled_package.blueprint_hash,
                "compilerWarnings": list(compiled_package.compatibility_warnings),
            })
            run.status = WorkflowStatus.SUPERSEDED
            run.execution_state["supersededByRunId"] = new_run.run_id
            run_graph = deepcopy(run.acg_blueprint or {})
            run_graph["metadata"] = deepcopy(run_graph.get("metadata") or {})
            run_graph["metadata"]["appliedGraphPatches"] = applied_metadata
            run.acg_blueprint = run_graph
            run.updated_at = utc_now()
            self.trace_store.append(
                run,
                TraceEventType.GRAPH_PATCH_APPLIED,
                observation="ACG graph patch applied",
                payload={
                    "patchId": patch.patch_id,
                    "patchRef": patch_uri,
                    "baseGraphVersion": patch.base_graph_version,
                    "graphVersion": outcome.blueprint.version,
                    "newRunId": new_run.run_id,
                },
            )
            self.workflow_store.save_graph_patch_transition(
                run,
                new_run,
                {
                    "eventId": f"graph.patch.prepared:{run.run_id}:{patch.patch_id}",
                    "eventType": "graph.patch.prepared",
                    "aggregateId": run.run_id,
                    "payload": {
                        "missionId": task.mission_id,
                        "oldRunId": run.run_id,
                        "newRunId": new_run.run_id,
                        "workflowId": new_run.workflow_id,
                        "patchId": patch.patch_id,
                        "blueprint": outcome.blueprint.model_dump(
                            by_alias=True, mode="json"
                        ),
                        "taskPlan": next_plan.model_dump(by_alias=True, mode="json"),
                        "taskBindings": [
                            item.model_dump(by_alias=True, mode="json")
                            for item in next_bindings
                        ],
                        "executionState": dict(new_run.execution_state),
                    },
                },
            )
            self._flush_identity_outbox()
            return GraphPatchResult(
                applied=True,
                graphVersion=outcome.blueprint.version,
                runId=new_run.run_id,
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
            requirements = dict(run.execution_state.get("bindingRequirements") or {})
            requirement_payload = requirements.get(step_id)
            if isinstance(requirement_payload, dict):
                requirement = BindingRequirement.model_validate(requirement_payload)
                requirements[step_id] = requirement.model_copy(
                    update={
                        "preferences": {
                            **requirement.preferences,
                            "resourceId": selected.agent_id,
                        }
                    }
                ).model_dump(by_alias=True, mode="json")
                run.execution_state["bindingRequirements"] = requirements
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

    async def _apply_acg_review(self, decision: ReviewDecision) -> RuntimeRunRecord:
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
            checkpoint_id = str(run.execution_state.get("checkpointId") or "")
            checkpoint_data = self.checkpoint_store.load(run_id=run.run_id, checkpoint_id=checkpoint_id)
            if checkpoint_data is None:
                raise ValueError("review checkpoint does not exist for this run")
            restored = ACGExecutionState.model_validate(checkpoint_data)
            subject_type, subject_id = acg_review_subject(restored.review_payload)
            if decision.step_id != subject_id:
                raise ReviewConflictError("review decision does not match the persisted ACG subject")
            step = run.get_step(subject_id) if subject_type == "step" else None
            if (
                decision.expected_run_updated_at is not None
                and run.updated_at != decision.expected_run_updated_at
            ):
                raise ReviewConflictError("workflow run revision changed")
            if step is not None and step.status != StepStatus.WAITING_REVIEW:
                raise ReviewConflictError("workflow step is no longer waiting for review")
            if (
                step is not None
                and decision.expected_step_status is not None
                and step.status != decision.expected_step_status
            ):
                raise ReviewConflictError("workflow step state changed")
            # 拒绝路径也必须验证 checkpoint 中的审计引用。否则攻击者可借由“直接
            # 拒绝”绕过归属检查，留下无法解释的审核记录或伪造的待写入意图。
            self._validate_acg_state_references(run=run, state=restored)
            if decision.decision is not ReviewDecisionType.APPROVED:
                if step is not None:
                    self._transition_step(step, StepStatus.FAILED)
                run.error = {"code": "review_rejected", "message": decision.comment[:500]}
                self.trace_store.append(
                    run,
                    TraceEventType.REVIEW_DECIDED,
                    step_id=subject_id,
                    observation="ACG review rejected",
                    payload={
                        "subjectType": subject_type,
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
                self.mission_manager.mark_failed(run.mission_id)
                self.workflow_store.save_run(run)
                return run
            if step is not None:
                self._commit_deferred_memory(run=run, step=step, state=restored)
            # The node result was committed before the interrupt; approval
            # resolves the review projection and must not leave a stale
            # WAITING_REVIEW step in an otherwise completed persisted run.
            if step is not None:
                self._transition_step(step, StepStatus.COMPLETED)
            self.trace_store.append(
                run,
                event_type=TraceEventType.REVIEW_DECIDED,
                step_id=subject_id,
                observation="ACG review approved",
                payload={
                    "subjectType": subject_type,
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
        run: RuntimeRunRecord,
        step: WorkflowStep,
        state: ACGExecutionState,
    ) -> None:
        """在人工批准后按待写入的结构化事件落入正式记忆。

        待写入意图只携带输出引用、策略、审计决定和经过白名单验证的 MemoryEvent；
        输出引用仍需按 run/step 校验，但完整输出正文不会进入 MemoryStore。
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
        memory_event = pending.get("memoryEvent")
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
        event = StructuredMemoryEvent.model_validate(memory_event)
        if event.run_id != run.run_id or event.step_id != step.step_id:
            raise ValueError("review pendingMemory event belongs to a different run or step")
        record = MemoryService(store=self.memory_store).remember_step_output(
            run_id=run.run_id,
            step_id=step.step_id,
            output=event.model_dump(by_alias=True, mode="json"),
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
                "memoryEventRef": event.event_id,
                "auditDecisionRef": decision_ref,
            },
        )

    @staticmethod
    def _find_review_operation(run: RuntimeRunRecord, operation_id: str | None) -> dict | None:
        if not operation_id:
            return None
        for event in run.trace:
            if event.event_type != TraceEventType.REVIEW_DECIDED:
                continue
            payload = event.payload or {}
            if payload.get("operationId") == operation_id:
                return payload
        return None

    async def resume_from_checkpoint(self, *, run_id: str, checkpoint_id: str) -> RuntimeRunRecord:
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

    def cancel(self, run_id: str) -> RuntimeRunRecord:
        """在运行锁内取消可继续步骤并持久化终态；已终态的迁移规则由状态机校验。"""
        with self.run_lock_manager.lock_for(run_id):
            latest = self.workflow_store.get_run(run_id)
            run = latest.model_copy(deep=True)
            self._transition_run(run, WorkflowStatus.CANCELLED)
            self.mission_manager.mark_cancelled(run.mission_id)
            self.trace_store.append(
                run=run,
                event_type=TraceEventType.RUN_CANCELLED,
                observation="Workflow cancelled.",
            )
            self.workflow_store.save_run(run)
            if (
                self.identity_lifecycle is not None
                and self._normalize_runtime_engine(run.runtime_engine) == "acg"
            ):
                self._flush_identity_outbox()
            return run

    def _resolve_workflow(
        self,
        task: RuntimeMissionRecord,
        workflow_id: Optional[str],
        *,
        allowed_workflow_ids: tuple[str, ...] | None = None,
    ) -> WorkflowDefinition:
        return self.mission_manager.bind_workflow(
            task,
            workflow_id=workflow_id,
            allowed_workflow_ids=allowed_workflow_ids,
        )

    def _planning_engine_for_run(self, run: RuntimeRunRecord):
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

    def _workflow_for_run(self, run: RuntimeRunRecord) -> WorkflowDefinition:
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
        run: RuntimeRunRecord,
        task: RuntimeMissionRecord,
        step: WorkflowStep,
        exc: Exception,
    ) -> None:
        step.error = str(exc)
        if step.retry_count < step.max_retries:
            step.retry_count += 1
            self._transition_step(step, StepStatus.RETRYING)
            self._transition_run(run, WorkflowStatus.RETRYING)
            self.mission_manager.mark_retrying(task)
        else:
            self._transition_step(step, StepStatus.FAILED)
            self._transition_run(run, WorkflowStatus.FAILED)
            self.mission_manager.mark_failed(task)
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

    def _transition_run(self, run: RuntimeRunRecord, status: WorkflowStatus) -> None:
        try:
            persisted = self.workflow_store.get_run(run.run_id)
        except KeyError:
            persisted = run
        if persisted.status in _TERMINAL_RUN_STATUSES and persisted.status != run.status:
            for field_name in RuntimeRunRecord.model_fields:
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


def build_default_runtime() -> ExecutionRuntime:
    """按环境变量装配默认运行时并登记原生与已安装插件；缺少数据库路径时抛出错误。"""
    agent_registry = AgentRegistry()
    workflow_registry = WorkflowRegistry()

    db_path = os.getenv("AGENTOS_WORKFLOW_DB_PATH", "").strip()
    workflow_store: WorkflowStore
    if not db_path:
        raise RuntimeError("Workflow database path is required outside test mode.")
    workflow_store = SQLiteWorkflowStore(db_path)

    runtime = ExecutionRuntime(
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


# 兼容既有 API 与第三方导入；新代码使用 ExecutionRuntime 明确唯一执行内核。
RuntimeRunRecordtime = ExecutionRuntime


__all__ = ["ExecutionRuntime", "RuntimeRunRecordtime", "build_default_runtime"]
