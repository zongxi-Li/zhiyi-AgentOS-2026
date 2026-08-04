"""资源画像、快照、租约与调度决策的共享合同。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResourceProfile(BaseModel):
    """可参与调度的资源静态画像；至少声明一项能力。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_id: StrictStr = Field(alias="resourceId", min_length=1, description="资源唯一标识。")
    capabilities: list[StrictStr] = Field(min_length=1, description="资源可提供的能力，不能为空。")
    labels: dict[str, str] = Field(default_factory=dict, description="用于筛选的稳定键值标签。")
    capacity: int = Field(default=1, ge=1, description="该资源可并发承接的最大工作数。")
    enabled: bool = Field(default=True, description="资源是否可接受新调度。")


class ResourceSnapshot(BaseModel):
    """资源某一时刻的可用性和负载观测值。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_id: StrictStr = Field(alias="resourceId", min_length=1, description="被观测资源标识。")
    observed_at: datetime = Field(default_factory=_utc_now, alias="observedAt", description="观测发生的 UTC 时间。")
    available_slots: int = Field(ge=0, alias="availableSlots", description="当前可供分配的空闲槽位数。")
    utilization: float = Field(ge=0.0, le=1.0, description="资源利用率，范围为 0 到 1。")
    metrics: dict[str, float] = Field(default_factory=dict, description="可扩展的数值型资源指标。")


class ResourceLease(BaseModel):
    """调度器授予某资源的一段有界使用权。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    lease_id: StrictStr = Field(alias="leaseId", min_length=1, description="租约唯一标识。")
    resource_id: StrictStr = Field(alias="resourceId", min_length=1, description="被租用资源标识。")
    owner_id: StrictStr | None = Field(default=None, alias="ownerId", description="获得使用权的任务或执行标识。")
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt", description="租约创建的 UTC 时间。")
    expires_at: datetime = Field(alias="expiresAt", description="租约失效的 UTC 时间，必须晚于创建时间。")

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
