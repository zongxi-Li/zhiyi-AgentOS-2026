"""任务部件与其他部件交换的稳定合同。

这里的模型只描述任务约束和生命周期事实，不承载任务管理器的业务规则。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


def _utc_now() -> datetime:
    """生成带时区的 UTC 时间，避免部件间传递朴素时间。"""
    return datetime.now(timezone.utc)


class TaskConstraint(BaseModel):
    """任务在规划和执行前必须满足的一条声明式约束。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    constraint_id: StrictStr = Field(alias="constraintId", min_length=1, description="约束的稳定标识。")
    kind: StrictStr = Field(min_length=1, description="约束类别，例如 capability、deadline 或 policy。")
    expression: StrictStr = Field(min_length=1, description="由消费者解释的声明式约束表达式。")
    required: bool = Field(default=True, description="是否为不满足即拒绝的硬约束。")
    metadata: dict[str, Any] = Field(default_factory=dict, description="可扩展的无业务语义附加信息。")


class TaskLifecycleEvent(BaseModel):
    """任务状态变化的不可变事实，供审计和事件订阅方消费。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event_id: StrictStr = Field(alias="eventId", min_length=1, description="生命周期事件的唯一标识。")
    task_id: StrictStr = Field(alias="taskId", min_length=1, description="发生变化的任务标识。")
    event_type: Literal["created", "planned", "started", "completed", "failed", "cancelled"] = Field(
        alias="eventType", description="标准化的任务生命周期事件类型。"
    )
    occurred_at: datetime = Field(default_factory=_utc_now, alias="occurredAt", description="事件发生的 UTC 时间。")
    previous_state: StrictStr | None = Field(default=None, alias="previousState", description="变化前状态；创建事件可为空。")
    current_state: StrictStr = Field(alias="currentState", min_length=1, description="变化后的任务状态。")
    payload: dict[str, Any] = Field(default_factory=dict, description="事件携带的无业务耦合上下文。")
