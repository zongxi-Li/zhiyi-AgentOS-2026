"""资源画像、快照、租约与调度决策的共享合同。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResourceType(str, Enum):
    """Stable kinds handled by the single resource service."""

    AGENT = "agent"
    MODEL = "model"
    EMBEDDING = "embedding"
    TOOL = "tool"
    WORKER = "worker"
    SKILL = "skill"
    MCP = "mcp"


class DeploymentTier(str, Enum):
    """资源实际部署位置；LOCAL 保留给现有进程内 Agent。"""

    LOCAL = "local"
    TERMINAL = "terminal"
    EDGE = "edge"
    CLOUD = "cloud"


class ResourceEndpoint(BaseModel):
    """远程资源的可调用地址；只保存凭据引用，不保存凭据内容。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    protocol: Literal["local", "http", "https", "grpc"] = "local"
    address: StrictStr = Field(min_length=1)
    auth_reference: StrictStr | None = Field(default=None, alias="authReference")

    @field_validator("address")
    @classmethod
    def reject_inline_credentials(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("resource endpoint must not contain inline credentials")
        return value


class ComputeCapacity(BaseModel):
    """可用于放置决策的资源算力摘要，不代表完整监控指标。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    cpu_cores: float = Field(default=0.0, ge=0.0, alias="cpuCores")
    memory_mb: int = Field(default=0, ge=0, alias="memoryMb")
    gpu_type: StrictStr | None = Field(default=None, alias="gpuType")
    gpu_memory_mb: int = Field(default=0, ge=0, alias="gpuMemoryMb")
    bandwidth_mbps: float = Field(default=0.0, ge=0.0, alias="bandwidthMbps")


class ResourceHealthStatus(str, Enum):
    """Persistable health projection; UNKNOWN is the safe restart state."""

    UNKNOWN = "unknown"
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class ResourceProfile(BaseModel):
    """可参与调度的资源静态画像；至少声明一项能力。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_id: StrictStr = Field(alias="resourceId", min_length=1, description="资源唯一标识。")
    resource_type: ResourceType = Field(default=ResourceType.AGENT, alias="resourceType")
    deployment_tier: DeploymentTier = Field(default=DeploymentTier.LOCAL, alias="deploymentTier")
    capabilities: list[StrictStr] = Field(min_length=1, description="资源可提供的能力，不能为空。")
    domains: list[StrictStr] = Field(default_factory=list, description="资源可服务的稳定领域。")
    labels: dict[str, str] = Field(default_factory=dict, description="用于筛选的稳定键值标签。")
    location: StrictStr | None = Field(default=None, description="资源位置或部署区域。")
    data_zone: StrictStr | None = Field(default=None, alias="dataZone", description="数据驻留区域。")
    cost_metadata: dict[str, float] = Field(default_factory=dict, alias="costMetadata")
    capacity: int = Field(default=1, ge=1, description="该资源可并发承接的最大工作数。")
    owner_scope: StrictStr | None = Field(default=None, alias="ownerScope")
    privacy_level: StrictStr = Field(default="internal", alias="privacyLevel")
    execution_endpoint: ResourceEndpoint | None = Field(default=None, alias="executionEndpoint")
    compute_capacity: ComputeCapacity = Field(default_factory=ComputeCapacity, alias="computeCapacity")
    model_ids: list[StrictStr] = Field(default_factory=list, alias="modelIds")
    enabled: bool = Field(default=True, description="资源是否可接受新调度。")
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)


class ResourceSnapshot(BaseModel):
    """资源某一时刻的可用性和负载观测值。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_id: StrictStr = Field(alias="resourceId", min_length=1, description="被观测资源标识。")
    observation_sequence: int = Field(default=0, ge=0, alias="observationSequence", description="资源节点单调递增的观测序号。")
    observed_at: datetime = Field(default_factory=_utc_now, alias="observedAt", description="观测发生的 UTC 时间。")
    available_slots: int = Field(ge=0, alias="availableSlots", description="当前可供分配的空闲槽位数。")
    utilization: float = Field(ge=0.0, le=1.0, description="资源利用率，范围为 0 到 1。")
    health_status: ResourceHealthStatus = Field(default=ResourceHealthStatus.UNKNOWN, alias="healthStatus")
    reliability: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: float | None = Field(default=None, ge=0.0, alias="latencyMs")
    metrics: dict[str, float] = Field(default_factory=dict, description="可扩展的数值型资源指标。")


class BindingRequirement(BaseModel):
    """Frozen Run/Step policy describing what may execute a future attempt."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    required_capabilities: list[StrictStr] = Field(alias="requiredCapabilities", min_length=1)
    domain: StrictStr | None = None
    resource_types: list[ResourceType] = Field(default_factory=list, alias="resourceTypes")
    allowed_deployment_tiers: list[DeploymentTier] = Field(default_factory=list, alias="allowedDeploymentTiers")
    allowed_resource_ids: list[StrictStr] = Field(default_factory=list, alias="allowedResourceIds")
    excluded_resource_ids: list[StrictStr] = Field(default_factory=list, alias="excludedResourceIds")
    data_zone: StrictStr | None = Field(default=None, alias="dataZone")
    owner_scope: StrictStr | None = Field(default=None, alias="ownerScope")
    labels: dict[str, str] = Field(default_factory=dict)
    max_cost: float | None = Field(default=None, alias="maxCost", ge=0.0)
    max_latency_ms: float | None = Field(default=None, alias="maxLatencyMs", ge=0.0)
    privacy_level: StrictStr = Field(default="internal", alias="privacyLevel")
    required_model_ids: list[StrictStr] = Field(default_factory=list, alias="requiredModelIds")
    min_gpu_memory_mb: int = Field(default=0, alias="minGpuMemoryMb", ge=0)
    allow_remote_execution: bool = Field(default=True, alias="allowRemoteExecution")
    preferences: dict[str, Any] = Field(default_factory=dict)
    policy_metadata: dict[str, Any] = Field(default_factory=dict, alias="policyMetadata")


class ExecutionBinding(BaseModel):
    """The concrete resource selected for one immutable execution attempt."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    binding_id: StrictStr = Field(alias="bindingId", min_length=1)
    run_id: StrictStr = Field(alias="runId", min_length=1)
    step_id: StrictStr = Field(alias="stepId", min_length=1)
    attempt_id: StrictStr = Field(alias="attemptId", min_length=1)
    resource_id: StrictStr = Field(alias="resourceId", min_length=1)
    resource_type: ResourceType = Field(alias="resourceType")
    snapshot_version: int = Field(alias="snapshotVersion", ge=1)
    bound_at: datetime = Field(default_factory=_utc_now, alias="boundAt")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceLease(BaseModel):
    """调度器授予某资源的一段有界使用权。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    lease_id: StrictStr = Field(alias="leaseId", min_length=1, description="租约唯一标识。")
    resource_id: StrictStr = Field(alias="resourceId", min_length=1, description="被租用资源标识。")
    agent_id: StrictStr | None = Field(default=None, alias="agentId", description="新账本中被租用的 Agent。")
    node_id: StrictStr | None = Field(default=None, alias="nodeId", description="新账本中承载执行的 Node。")
    owner_id: StrictStr | None = Field(default=None, alias="ownerId", description="获得使用权的任务或执行标识。")
    run_id: StrictStr | None = Field(default=None, alias="runId")
    step_id: StrictStr | None = Field(default=None, alias="stepId")
    attempt_id: StrictStr | None = Field(default=None, alias="attemptId")
    slot_count: int = Field(default=1, alias="slotCount", ge=1)
    status: Literal["active", "released", "expired"] = "active"
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt", description="租约创建的 UTC 时间。")
    expires_at: datetime = Field(alias="expiresAt", description="租约失效的 UTC 时间，必须晚于创建时间。")

    @field_validator("created_at", "expires_at")
    @classmethod
    def normalize_aware_time(cls, value: datetime) -> datetime:
        """拒绝歧义的朴素时间，并统一租约边界到 UTC。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("lease timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def expiry_follows_creation(self) -> "ResourceLease":
        """拒绝零时长和逆时序租约。"""
        if self.expires_at <= self.created_at:
            raise ValueError("expiresAt must be later than createdAt")
        return self


class SchedulingRequest(BaseModel):
    """执行部件向调度部件提出的资源选择请求。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    request_id: StrictStr = Field(alias="requestId", min_length=1, description="调度请求唯一标识。")
    workload_id: StrictStr = Field(alias="workloadId", min_length=1, description="待安排的工作负载标识。")
    required_capabilities: list[StrictStr] = Field(alias="requiredCapabilities", min_length=1, description="资源必须具备的能力集合。")
    priority: int = Field(default=0, ge=0, le=100, description="调度优先级，数值越大越优先。")
    requested_at: datetime = Field(default_factory=_utc_now, alias="requestedAt", description="请求创建的 UTC 时间。")
    constraints: dict[str, Any] = Field(default_factory=dict, description="不绑定调度算法的附加约束。")


class SchedulingDecision(BaseModel):
    """调度部件对一次请求给出的可审计决定。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    request_id: StrictStr = Field(alias="requestId", min_length=1, description="对应的调度请求标识。")
    decision: Literal["allocated", "queued", "rejected"] = Field(description="标准化调度决定。")
    resource_id: StrictStr | None = Field(default=None, alias="resourceId", description="已分配时的资源标识。")
    lease: ResourceLease | None = Field(default=None, description="已分配时产生的资源租约。")
    reason: StrictStr | None = Field(default=None, description="排队或拒绝时的可读原因。")
    decided_at: datetime = Field(default_factory=_utc_now, alias="decidedAt", description="决定产生的 UTC 时间。")

    @model_validator(mode="after")
    def validate_allocation_fields(self) -> "SchedulingDecision":
        """确保分配状态与资源、租约字段构成无歧义组合。"""
        if self.decision == "allocated":
            if self.resource_id is None or self.lease is None:
                raise ValueError("allocated decision requires resourceId and lease")
            if self.lease.resource_id != self.resource_id:
                raise ValueError("resourceId must match lease.resourceId")
        elif self.resource_id is not None or self.lease is not None:
            raise ValueError("queued/rejected decisions must not include allocation fields")
        return self


class NodeType(str, Enum):
    """节点资源表记录的服务/算力节点类型。"""

    WORKER = "worker"
    MODEL = "model"
    EMBEDDING = "embedding"
    TOOL = "tool"
    MCP = "mcp"


class NodeHealthStatus(str, Enum):
    """节点健康分级：在线、忙碌、过载、陈旧、离线。"""

    ONLINE = "online"
    BUSY = "busy"
    OVERLOADED = "overloaded"
    STALE = "stale"
    OFFLINE = "offline"


class NodeProfile(BaseModel):
    """节点资源表：可参与计算的设备或服务节点的静态能力。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    node_id: StrictStr = Field(alias="nodeId", min_length=1, description="节点唯一标识。")
    node_type: NodeType = Field(default=NodeType.WORKER, alias="nodeType")
    deployment_tier: DeploymentTier = Field(default=DeploymentTier.LOCAL, alias="deploymentTier")
    cpu_cores: float = Field(default=0.0, ge=0.0, alias="cpuCores")
    gpu_type: StrictStr | None = Field(default=None, alias="gpuType")
    gpu_memory_mb: int = Field(default=0, ge=0, alias="gpuMemoryMb")
    memory_mb: int = Field(default=0, ge=0, alias="memoryMb")
    max_model_params: StrictStr | None = Field(default=None, alias="maxModelParams", description="能承载的最大模型参数量。")
    model_ids: list[StrictStr] = Field(default_factory=list, alias="modelIds", description="节点可承载或直连的模型。")
    privacy_level: StrictStr = Field(default="internal", alias="privacyLevel")
    data_zone: StrictStr | None = Field(default=None, alias="dataZone", description="所属隐私区域。")
    cost_per_unit: float = Field(default=0.0, ge=0.0, alias="costPerUnit", description="单位时间成本。")
    owner_scope: StrictStr | None = Field(default=None, alias="ownerScope")
    execution_endpoint: ResourceEndpoint | None = Field(default=None, alias="executionEndpoint")
    labels: dict[str, str] = Field(default_factory=dict)
    location: StrictStr | None = Field(default=None)
    enabled: bool = Field(default=True)
    metadata: dict[str, Any] = Field(default_factory=dict, description="荣耀生态专属字段等。")
    version: int = Field(default=1, ge=1)


class NodeSnapshot(BaseModel):
    """节点资源表：由心跳实时刷新的动态状态。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    node_id: StrictStr = Field(alias="nodeId", min_length=1)
    observation_sequence: int = Field(default=0, ge=0, alias="observationSequence")
    observed_at: datetime = Field(default_factory=_utc_now, alias="observedAt")
    cpu_utilization: float = Field(default=0.0, ge=0.0, le=1.0, alias="cpuUtilization")
    gpu_utilization: float = Field(default=0.0, ge=0.0, le=1.0, alias="gpuUtilization")
    available_memory_mb: int = Field(default=0, ge=0, alias="availableMemoryMb")
    queued_tasks: int = Field(default=0, ge=0, alias="queuedTasks")
    latency_ms: float | None = Field(default=None, ge=0.0, alias="latencyMs", description="预估网络延迟。")
    health_status: NodeHealthStatus = Field(default=NodeHealthStatus.ONLINE, alias="healthStatus")
    last_heartbeat: datetime | None = Field(default=None, alias="lastHeartbeat")
    consecutive_failures: int = Field(default=0, ge=0, alias="consecutiveFailures")
    metrics: dict[str, float] = Field(default_factory=dict)


class AgentState(str, Enum):
    """Agent 忙闲状态。"""

    IDLE = "idle"
    BUSY = "busy"


class AgentProfile(BaseModel):
    """Agent 注册表：每一个 Agent 的静态属性。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    agent_id: StrictStr = Field(alias="agentId", min_length=1)
    capabilities: list[StrictStr] = Field(min_length=1, description="能力标签（含 skill）。")
    required_model_ids: list[StrictStr] = Field(default_factory=list, alias="requiredModelIds", description="所需模型。")
    required_gpu_memory_mb: int = Field(default=0, ge=0, alias="requiredGpuMemoryMb", description="所需显存。")
    min_privacy_level: StrictStr = Field(default="internal", alias="minPrivacyLevel", description="最低允许运行的隐私等级。")
    allowed_node_ids: list[StrictStr] = Field(default_factory=list, alias="allowedNodeIds", description="可部署的节点白名单。")
    labels: dict[str, str] = Field(default_factory=dict)
    enabled: bool = Field(default=True)
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)


class AgentSnapshot(BaseModel):
    """Agent 注册表：由事件驱动心跳刷新的动态状态。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    agent_id: StrictStr = Field(alias="agentId", min_length=1)
    observation_sequence: int = Field(default=0, ge=0, alias="observationSequence")
    observed_at: datetime = Field(default_factory=_utc_now, alias="observedAt")
    state: AgentState = Field(default=AgentState.IDLE)
    node_id: StrictStr | None = Field(default=None, alias="nodeId", description="当前运行节点。")
    current_step_id: StrictStr | None = Field(default=None, alias="currentStepId", description="正在执行的 Step。")
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0, alias="successRate", description="历史成功率。")
    avg_latency_ms: float = Field(default=0.0, ge=0.0, alias="avgLatencyMs", description="平均耗时。")
    avg_tokens: float = Field(default=0.0, ge=0.0, alias="avgTokens", description="平均 Token 消耗。")
    health_status: ResourceHealthStatus = Field(default=ResourceHealthStatus.UNKNOWN, alias="healthStatus")
    metrics: dict[str, float] = Field(default_factory=dict)
