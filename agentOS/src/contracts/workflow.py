"""AgentOS Core 的 types 模块，提供运行时控制、状态、Trace、审核或治理能力。"""


from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from contracts.execution import StepStatus, WorkflowProgressPhase


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间，作为合同默认时间戳的统一时钟来源。"""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """以给定前缀生成短 UUID 标识；仅提供唯一性，不表达排序或时间语义。"""
    return f"{prefix}_{uuid4().hex[:12]}"


class CoreModel(BaseModel):
    """核心合同基类；支持别名输入，并忽略未知字段以兼容历史载荷。"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


ContributionSource = Literal["native", "plugin"]


class PluginSnapshot(CoreModel):
    """冻结在一次工作流运行中的插件安装包身份。

    ``plugin_id``、版本、清单哈希和贡献修订共同固定解析结果；模型不可变，防止运行期间
    因插件升级漂移。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    plugin_id: str = Field(alias="pluginId")
    version: str
    manifest_hash: str = Field(alias="manifestHash")
    contribution_revision: str = Field(alias="contributionRevision")


class RunExecutionScope(CoreModel):
    """一次工作流运行全程使用的不可变可见性边界。

    插件、能力、智能体和工作流标识以及插件快照必须来自同一解析时点；目录修订用于检测
    计划与执行之间的版本漂移。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    enabled_plugin_ids: tuple[str, ...] = Field(
        default_factory=tuple, alias="enabledPluginIds"
    )
    capability_ids: tuple[str, ...] = Field(default_factory=tuple, alias="capabilityIds")
    agent_ids: tuple[str, ...] = Field(default_factory=tuple, alias="agentIds")
    workflow_ids: tuple[str, ...] = Field(default_factory=tuple, alias="workflowIds")
    plugin_snapshots: tuple[PluginSnapshot, ...] = Field(
        default_factory=tuple, alias="pluginSnapshots"
    )
    capability_catalog_revision: str = Field(alias="capabilityCatalogRevision")


class WorkflowStatus(str, Enum):
    """工作流/任务的生命周期状态；完成、失败和取消为不可继续推进的终态。"""
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    RETRYING = "retrying"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkflowDefinitionType(str, Enum):
    """区分可执行模板与规划器引导定义；两者的注册身份相同但运行入口不同。"""

    TEMPLATE = "template"
    NATIVE_BOOTSTRAP = "native_bootstrap"


class TraceEventType(str, Enum):
    """运行轨迹事件的受控类型词表，用于审计而非驱动状态迁移。"""
    TASK_CREATED = "task_created"
    TASK_STATUS_CHANGED = "task_status_changed"
    TASK_ERROR = "task_error"
    RUN_STARTED = "run_started"
    STEP_SCHEDULED = "step_scheduled"
    STEP_STARTED = "step_started"
    AGENT_CALLED = "agent_called"
    MODEL_CALLED = "model_called"
    STEP_SUCCEEDED = "step_succeeded"
    TOOL_CALLED = "tool_called"
    DATA_PRODUCED = "data_produced"
    DATA_CONSUMED = "data_consumed"
    CONTRACT_VIOLATION = "contract_violation"
    CHECKPOINT_CREATED = "checkpoint_created"
    RUNTIME_PATCH_APPLIED = "runtime_patch_applied"
    GRAPH_PATCH_APPLIED = "graph_patch_applied"
    RUNTIME_EVENT_CLASSIFIED = "runtime_event_classified"
    RUNTIME_EVENT_IGNORED = "runtime_event_ignored"
    GRAPH_CHANGE_PROPOSED = "graph_change_proposed"
    GRAPH_PATCH_REJECTED = "graph_patch_rejected"
    GRAPH_VERSION_CONFLICT = "graph_version_conflict"
    RUNTIME_RECIPE_SELECTED = "runtime_recipe_selected"
    RUNTIME_RECIPE_REAPPLICATION_BLOCKED = "runtime_recipe_reapplication_blocked"
    REVIEW_REQUIRED = "review_required"
    REVIEW_DECIDED = "review_decided"
    STEP_FAILED = "step_failed"
    RUN_FAILED = "run_failed"
    RUN_RECOVERED = "run_recovered"
    # Persisted migration runs and the Milan trace UI already expose this
    # audit-only terminal event. Keep it readable even though it never drives
    # runtime state transitions.
    RUN_DEGRADED = "run_degraded"
    RUN_COMPLETED = "run_completed"
    RUN_CANCELLED = "run_cancelled"
    STOCHASTIC_PLANNING_FALLBACK = "stochastic_planning_fallback"


class ReviewDecisionType(str, Enum):
    """人工或系统审核可作出的决定类型。"""
    APPROVED = "approved"
    REJECTED = "rejected"
    NEED_MORE_INFO = "need_more_info"
    RERUN = "rerun"
    CANCELLED = "cancelled"


class AgentTask(CoreModel):
    """用户请求对应的任务合同。

    ``task_id`` 全局标识任务；领域、意图、优先级与安全级别用于规划，
    ``recommended_workflow`` 仅是推荐而非已绑定的工作流。
    """
    task_id: str = Field(default_factory=lambda: new_id("task"), alias="taskId")
    title: str
    domain: str = "general"
    intent: str = "general"
    input: Dict[str, Any] = Field(default_factory=dict)
    security_level: str = Field(default="internal", alias="securityLevel")
    priority: str = "normal"
    status: WorkflowStatus = WorkflowStatus.PENDING
    recommended_workflow: Optional[str] = Field(default=None, alias="recommendedWorkflow")
    enabled_plugin_ids: Optional[List[str]] = Field(default=None, alias="enabledPluginIds")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")


class WorkflowStepDefinition(CoreModel):
    """工作流模板中不可执行的步骤定义。

    ``input``/``output_spec`` 为声明式合同，重试、超时与优先级是执行建议；
    ``next_step_id`` 仅表达线性后继，图执行关系由运行图补充。
    """
    step_id: str = Field(alias="stepId")
    name: str
    agent_name: str = Field(alias="agentName")
    capability: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    output_spec: Dict[str, Any] = Field(default_factory=dict, alias="outputSpec")
    review_required: bool = Field(default=False, alias="reviewRequired")
    next_step_id: Optional[str] = Field(default=None, alias="nextStepId")
    max_retries: int = Field(default=0, alias="maxRetries")
    timeout: int = 0
    priority: int = 0


class WorkflowDefinition(CoreModel):
    """可注册工作流的版本化定义。

    ``workflow_id`` 与历史 ``id`` 在校验时归一为同一标识；运行引擎、实现标识、
    来源插件和步骤定义共同构成可执行选择边界。
    """
    workflow_id: str = Field(alias="workflowId")
    id: Optional[str] = None
    name: str
    domain: str
    intent: str = "general"
    version: str = "1.0.0"
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    runtime_engine: str = Field(alias="runtimeEngine")
    definition_type: WorkflowDefinitionType = Field(
        default=WorkflowDefinitionType.TEMPLATE,
        alias="definitionType",
    )
    executor_type: Optional[str] = Field(default=None, alias="executorType")
    implementation_id: Optional[str] = Field(default=None, alias="implementationId")
    aliases: List[str] = Field(default_factory=list)
    artifacts: Dict[str, str] = Field(default_factory=dict)
    steps: List[WorkflowStepDefinition] = Field(default_factory=list)
    source: ContributionSource = "native"
    plugin_id: Optional[str] = Field(default=None, alias="pluginId")
    plugin_version: Optional[str] = Field(default=None, alias="pluginVersion")
    contribution_id: Optional[str] = Field(default=None, alias="contributionId")

    @model_validator(mode="before")
    @classmethod
    def normalize_identifier_fields(cls, data: Any) -> Any:
        """归一 ``id`` 与 ``workflowId``，保持历史载荷与当前标识不变量兼容。"""
        if isinstance(data, dict):
            if "workflowId" not in data and "workflow_id" not in data and "id" in data:
                data["workflowId"] = data["id"]
            if "id" not in data and ("workflowId" in data or "workflow_id" in data):
                data["id"] = data.get("workflowId") or data.get("workflow_id")
        return data

    @property
    def effective_runtime_engine(self) -> str:
        """返回去除空白并小写化的运行引擎标识，供分派比较使用。"""
        return self.runtime_engine.strip().lower()

    @property
    def effective_implementation_id(self) -> str:
        """返回显式实现标识，缺失时回退到 ``workflow_id``。"""
        return (self.implementation_id or self.workflow_id).strip()

    @property
    def is_native_bootstrap(self) -> bool:
        """判断定义是否为 ACG 原生规划引导项，而非可复用模板。"""
        return (
            self.effective_runtime_engine == "acg"
            and self.definition_type == WorkflowDefinitionType.NATIVE_BOOTSTRAP
        )

    def first_step_id(self) -> Optional[str]:
        """返回声明顺序中的首步骤标识；空定义时返回 ``None``。"""
        return self.steps[0].step_id if self.steps else None

    def get_step_definition(self, step_id: str) -> WorkflowStepDefinition:
        """按标识查找步骤定义；保持声明顺序扫描，未找到时抛出 ``KeyError``。"""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(f"workflow step not found: {step_id}")

class WorkflowStep(CoreModel):
    """一次工作流运行中的可变步骤状态。

    从定义复制的输入、输出约束和执行参数固定本次运行边界；``resolved_input``、
    ``output``、状态及时间字段由执行器推进。
    """
    step_id: str = Field(alias="stepId")
    name: str
    agent_name: str = Field(alias="agentName")
    capability: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    input: Dict[str, Any] = Field(default_factory=dict)
    output_spec: Dict[str, Any] = Field(default_factory=dict, alias="outputSpec")
    resolved_input: Dict[str, Any] = Field(default_factory=dict, alias="resolvedInput")
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    retry_count: int = Field(default=0, alias="retryCount")
    attempt: int = 0
    max_retries: int = Field(default=0, alias="maxRetries")
    timeout: int = 0
    priority: int = 0
    requires_review: bool = Field(default=False, alias="reviewRequired")
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    completed_at: Optional[datetime] = Field(default=None, alias="completedAt")

    @classmethod
    def from_definition(cls, definition: WorkflowStepDefinition) -> "WorkflowStep":
        """从模板定义创建待执行步骤，并复制可变字典以隔离后续运行时修改。"""
        return cls(
            stepId=definition.step_id,
            name=definition.name,
            agentName=definition.agent_name,
            capability=definition.capability,
            input=dict(definition.input),
            outputSpec=dict(definition.output_spec),
            reviewRequired=definition.review_required,
            maxRetries=definition.max_retries,
            timeout=definition.timeout,
            priority=definition.priority,
        )


class TraceEvent(CoreModel):
    """运行过程中的追加式审计事件。

    事件可关联运行、步骤和智能体；``payload`` 保存结构化上下文，``duration_ms`` 是
    观测值而非调度时限。
    """
    event_id: str = Field(default_factory=lambda: new_id("trace"), alias="eventId")
    run_id: Optional[str] = Field(default=None, alias="runId")
    step_id: Optional[str] = Field(default=None, alias="stepId")
    agent_name: Optional[str] = Field(default=None, alias="agentName")
    event_type: TraceEventType = Field(alias="eventType")
    observation: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, alias="durationMs")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class Checkpoint(CoreModel):
    """单个执行屏障的不可变恢复点。

    ``stepId`` 保留历史主步骤标识；``stepIds`` 记录同一屏障提交的全部节点，避免并行
    结果生成重复快照。快照版本和哈希由创建方维护，持久化后不应原地修改。
    """

    checkpoint_id: str = Field(default_factory=lambda: new_id("ckpt"), alias="checkpointId")
    run_id: str = Field(alias="runId")
    step_id: str = Field(alias="stepId")
    step_ids: List[str] = Field(default_factory=list, alias="stepIds")
    snapshot_version: int = Field(default=1, alias="snapshotVersion")
    snapshot_hash: Optional[str] = Field(default=None, alias="snapshotHash")
    state_snapshot: Dict[str, Any] = Field(default_factory=dict, alias="stateSnapshot")
    output_snapshot: Dict[str, Any] = Field(default_factory=dict, alias="outputSnapshot")
    can_resume: bool = Field(default=True, alias="canResume")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class WorkflowRun(CoreModel):
    """一个任务对某工作流的一次执行聚合。

    任务、工作流、引擎与插件/能力快照共同固定可见性边界；步骤、检查点、轨迹、
    运行图与执行状态是可持久化快照，``updated_at`` 应随任何状态性修改更新。
    """
    run_id: str = Field(default_factory=lambda: new_id("run"), alias="runId")
    task_id: str = Field(alias="taskId")
    workflow_id: str = Field(alias="workflowId")
    domain: str
    runtime_engine: str = Field(alias="runtimeEngine")
    implementation_id: Optional[str] = Field(default=None, alias="implementationId")
    status: WorkflowStatus = WorkflowStatus.PENDING
    lifecycle_phase: Optional[WorkflowProgressPhase] = Field(default=None, alias="lifecyclePhase")
    lifecycle_message: Optional[str] = Field(default=None, alias="lifecycleMessage")
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    idempotency_key: Optional[str] = Field(default=None, alias="idempotencyKey")
    idempotency_fingerprint: Optional[str] = Field(default=None, alias="idempotencyFingerprint")
    current_step_id: Optional[str] = Field(default=None, alias="currentStepId")
    review_mode: str = Field(default="auto", alias="reviewMode")
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    steps: List[WorkflowStep] = Field(default_factory=list)
    checkpoints: List[Checkpoint] = Field(default_factory=list)
    trace: List[TraceEvent] = Field(default_factory=list)
    error: Optional[str | Dict[str, Any]] = None
    recovery_count: int = Field(default=0, alias="recoveryCount")
    enabled_plugin_ids: List[str] = Field(default_factory=list, alias="enabledPluginIds")
    resolved_enabled_plugin_ids: List[str] = Field(
        default_factory=list, alias="resolvedEnabledPluginIds"
    )
    plugin_snapshot: List[PluginSnapshot] = Field(default_factory=list, alias="pluginSnapshot")
    capability_catalog_revision: Optional[str] = Field(
        default=None, alias="capabilityCatalogRevision"
    )
    planning_diversity: Literal["stable", "balanced", "exploratory"] = Field(
        default="stable", alias="planningDiversity"
    )
    planning_seed: Optional[int] = Field(
        default=None, alias="planningSeed", ge=0, le=2**53 - 1
    )
    planner_algorithm_version: Optional[str] = Field(
        default=None, alias="plannerAlgorithmVersion"
    )
    planning_candidate_count: int = Field(default=1, alias="planningCandidateCount", ge=1)
    selected_planning_variant_id: Optional[str] = Field(
        default=None, alias="selectedPlanningVariantId"
    )
    execution_scope: Optional[RunExecutionScope] = Field(default=None, alias="executionScope")
    legacy_plugin_scope: bool = Field(default=False, alias="legacyPluginScope")
    # ACG 执行路径承载字段（可选，仅 runtimeEngine=acg 时填充）。
    # acg_blueprint 存规划器产物 / 升格结果；completed_step_ids 记录就绪集调度
    # 已完成的 StepNode，用于并行调度时计算下一批就绪集，不影响线性路径。
    acg_blueprint: Optional[Dict[str, Any]] = Field(default=None, alias="acgBlueprint")
    # Stage one: authoritative runtime structure/version/patch history.  WorkflowStep
    # remains the execution-state authority until the executor is migrated.
    # 运行图由 executor 持有；合同仅保存可序列化快照，避免 contracts 反向依赖实现部件。
    runtime_graph: Optional[Any] = Field(default=None, alias="runtimeGraph")
    completed_step_ids: List[str] = Field(default_factory=list, alias="completedStepIds")
    active_step_ids: List[str] = Field(default_factory=list, alias="activeStepIds")
    # 数据血缘图（低熵通信审计产物，ACG 路径填充）：生产/消费事件，供前端血缘面板。
    provenance: Optional[Dict[str, Any]] = Field(default=None)
    execution_state: Dict[str, Any] = Field(default_factory=dict, alias="executionState")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")

    @model_validator(mode="before")
    @classmethod
    def mark_legacy_plugin_scope(cls, data: Any) -> Any:
        """为未携带插件范围字段的历史载荷标注兼容路径，不写入外部状态。"""
        if isinstance(data, dict):
            data = dict(data)
            has_scope = "executionScope" in data or "execution_scope" in data
            has_plugins = "enabledPluginIds" in data or "enabled_plugin_ids" in data
            if not has_scope and not has_plugins:
                data.setdefault("legacyPluginScope", True)
        return data

    def get_step(self, step_id: str) -> WorkflowStep:
        """按标识获取本次运行步骤；顺序扫描并在缺失时抛出 ``KeyError``。"""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(f"workflow run step not found: {step_id}")


class ReviewDecision(CoreModel):
    """提交给运行时的审核命令。

    ``operation_id`` 和期望版本/状态字段用于并发保护；决定本身不包含执行副作用。
    """
    run_id: str = Field(alias="runId")
    step_id: str = Field(alias="stepId")
    decision: ReviewDecisionType
    reviewer: str = "system"
    comment: str = ""
    operation_id: Optional[str] = Field(default=None, alias="operationId")
    expected_run_updated_at: Optional[datetime] = Field(default=None, alias="expectedRunUpdatedAt")
    expected_step_status: Optional[StepStatus] = Field(default=None, alias="expectedStepStatus")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class ReviewRecord(CoreModel):
    """已处理审核决定的不可变审计记录，关联原操作与产生的轨迹事件。"""
    review_id: str = Field(default_factory=lambda: new_id("review"), alias="reviewId")
    run_id: str = Field(alias="runId")
    step_id: str = Field(alias="stepId")
    decision: ReviewDecisionType
    reviewer: str = "system"
    comment: str = ""
    operation_id: Optional[str] = Field(default=None, alias="operationId")
    trace_event_id: Optional[str] = Field(default=None, alias="traceEventId")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class WorkflowMetric(CoreModel):
    """按筛选范围汇总的运行指标。

    计数与状态拆分以同一批运行计算；比率为派生快照，在样本为空时由调用方定义为零。
    """
    total_runs: int = Field(default=0, alias="totalRuns")
    completed_runs: int = Field(default=0, alias="completedRuns")
    failed_runs: int = Field(default=0, alias="failedRuns")
    cancelled_runs: int = Field(default=0, alias="cancelledRuns")
    waiting_review_runs: int = Field(default=0, alias="waitingReviewRuns")
    retrying_runs: int = Field(default=0, alias="retryingRuns")
    completion_rate: float = Field(default=0.0, alias="completionRate")
    failure_rate: float = Field(default=0.0, alias="failureRate")
    recovery_success_rate: float = Field(default=0.0, alias="recoverySuccessRate")
    average_recovery_count: float = Field(default=0.0, alias="averageRecoveryCount")
    average_trace_events: float = Field(default=0.0, alias="averageTraceEvents")
    review_count: int = Field(default=0, alias="reviewCount")
    status_breakdown: Dict[str, int] = Field(default_factory=dict, alias="statusBreakdown")


class EvaluationRun(CoreModel):
    """一次运行评估的可序列化结果，记录筛选维度、指标快照和生成时间。"""
    evaluation_id: str = Field(default_factory=lambda: new_id("eval"), alias="evaluationId")
    domain: Optional[str] = None
    workflow_id: Optional[str] = Field(default=None, alias="workflowId")
    source: Optional[str] = None
    metrics: WorkflowMetric
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")


class SkillRequest(CoreModel):
    """向技能执行边界传递的请求；会话、文本、动作输入和记忆均为调用时快照。"""
    session_id: str = Field(alias="sessionId")
    text: str
    action_input: Dict[str, Any] = Field(default_factory=dict, alias="actionInput")
    memory: Dict[str, Any] = Field(default_factory=dict)


class SkillResult(CoreModel):
    """技能执行结果；``success`` 决定 ``output`` 是否可被下游当作有效产物消费。"""
    skill_name: str = Field(alias="skillName")
    success: bool = True
    output: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class GraphRef(CoreModel):
    """跨部件传递的工作流图版本引用。"""

    graph_id: StrictStr = Field(alias="graphId", min_length=1)
    version: StrictStr = Field(min_length=1)
    checksum: StrictStr | None = Field(default=None, min_length=1)


class GraphNodeRef(CoreModel):
    """图节点的稳定引用，不泄漏规划器或执行器对象。"""

    graph: GraphRef
    node_id: StrictStr = Field(alias="nodeId", min_length=1)
    node_type: StrictStr = Field(alias="nodeType", min_length=1)
    label: StrictStr | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphEdgeRef(CoreModel):
    """工作流图中两个节点之间的有向关系。"""

    graph: GraphRef
    edge_id: StrictStr = Field(alias="edgeId", min_length=1)
    source_node_id: StrictStr = Field(alias="sourceNodeId", min_length=1)
    target_node_id: StrictStr = Field(alias="targetNodeId", min_length=1)
    relation: Literal["sequence", "condition", "data", "control"] = "sequence"
