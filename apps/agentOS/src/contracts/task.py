"""Serializable contracts used by ACG planning.

Scheduling, persistence, and recovery remain responsibilities of the single
execution graph and ``ExecutionRuntime``; this module defines data shapes only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictStr


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ACGTaskStatus(str, Enum):
    """ACG 任务的生命周期状态；终态为 ``SUCCESS``、``FAILED`` 与 ``CANCELLED``。"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepExecutionStatus(str, Enum):
    """单次步骤执行的状态；重试次数由所属 ``StepExecution`` 的 ``attempt`` 表示。"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class AgentInstanceStatus(str, Enum):
    """任务内智能体实例的状态，不替代步骤或任务本身的状态。"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class CheckpointType(str, Enum):
    """检查点来源：运行时自动创建或调用方显式请求创建。"""
    AUTO = "auto"
    MANUAL = "manual"


class ACGRuntimeModel(BaseModel):
    """ACG 运行时合同基类；接受字段别名并拒绝未声明字段以固定序列化边界。"""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ACGTask(ACGRuntimeModel):
    """ACG 任务聚合根。

    ``task_id`` 是稳定任务标识，``graph_id`` 指向规划图；时间与 ``current_step_id``
    随执行推进更新，``metadata`` 只承载可扩展的非核心信息。
    """
    task_id: str = Field(default_factory=lambda: _new_id("task"), alias="taskId")
    task_name: str = Field(default="", alias="taskName")
    user_query: str = Field(default="", alias="userQuery")
    graph_id: str = Field(default="", alias="graphId")
    status: ACGTaskStatus = ACGTaskStatus.PENDING
    start_time: Optional[datetime] = Field(default=None, alias="startTime")
    end_time: Optional[datetime] = Field(default=None, alias="endTime")
    current_step_id: Optional[str] = Field(default=None, alias="currentStepId")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StepExecution(ACGRuntimeModel):
    """步骤的一次可审计执行尝试。

    ``task_id`` 与 ``step_id`` 锚定归属，``attempt`` 区分重试；输入、输出、证据和
    检查点只记录该尝试的快照，状态时间须与执行状态一致。
    """
    step_execution_id: str = Field(default_factory=lambda: _new_id("step_exec"), alias="stepExecutionId")
    task_id: str = Field(alias="taskId")
    step_id: str = Field(alias="stepId")
    parent_execution_id: Optional[str] = Field(default=None, alias="parentExecutionId")
    attempt: int = 0
    status: StepExecutionStatus = StepExecutionStatus.PENDING
    start_time: Optional[datetime] = Field(default=None, alias="startTime")
    end_time: Optional[datetime] = Field(default=None, alias="endTime")
    agent_instance_id: Optional[str] = Field(default=None, alias="agentInstanceId")
    checkpoint_id: Optional[str] = Field(default=None, alias="checkpointId")
    input_data: Dict[str, Any] = Field(default_factory=dict, alias="inputData")
    output_data: Dict[str, Any] = Field(default_factory=dict, alias="outputData")
    evidence_ids: List[str] = Field(default_factory=list, alias="evidenceIds")
    error_message: Optional[str] = Field(default=None, alias="errorMessage")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentInstance(ACGRuntimeModel):
    """任务内被实例化的智能体运行记录。

    ``agent_id`` 是定义侧标识，``agent_instance_id`` 是本次运行标识；令牌与执行计数
    为累计观测值，不应作为配额决策的唯一事实来源。
    """
    agent_instance_id: str = Field(default_factory=lambda: _new_id("agent_instance"), alias="agentInstanceId")
    task_id: str = Field(alias="taskId")
    agent_id: str = Field(alias="agentId")
    status: AgentInstanceStatus = AgentInstanceStatus.PENDING
    start_time: Optional[datetime] = Field(default=None, alias="startTime")
    end_time: Optional[datetime] = Field(default=None, alias="endTime")
    model_name: str = Field(default="", alias="modelName")
    token_usage: int = Field(default=0, alias="tokenUsage")
    execution_count: int = Field(default=0, alias="executionCount")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceRecord(ACGRuntimeModel):
    """由步骤执行产出的证据记录。

    ``evidence_id`` 连接图中的证据节点，``producer_execution_id`` 可为空以兼容外部
    证据；``content`` 与置信度为创建时快照。
    """
    evidence_record_id: str = Field(default_factory=lambda: _new_id("evidence_record"), alias="evidenceRecordId")
    evidence_id: str = Field(alias="evidenceId")
    task_id: str = Field(alias="taskId")
    producer_execution_id: Optional[str] = Field(default=None, alias="producerExecutionId")
    content: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    created_time: datetime = Field(default_factory=_utc_now, alias="createdTime")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemorySnapshot(ACGRuntimeModel):
    """指定任务记忆的版本化快照。

    ``version`` 从 1 开始，由写入方递增；相同 ``snapshot_id`` 的内容在持久化后应
    视为不可变。
    """
    snapshot_id: str = Field(default_factory=lambda: _new_id("memory_snapshot"), alias="snapshotId")
    task_id: str = Field(alias="taskId")
    memory_id: str = Field(alias="memoryId")
    version: int = 1
    content: Dict[str, Any] = Field(default_factory=dict)
    created_time: datetime = Field(default_factory=_utc_now, alias="createdTime")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ACGCheckpoint(ACGRuntimeModel):
    """步骤执行后的可恢复状态快照。

    ``step_execution_id`` 将检查点绑定到单次尝试，``state_data`` 是恢复输入快照；
    检查点类型仅描述来源，不改变恢复语义。
    """
    checkpoint_id: str = Field(default_factory=lambda: _new_id("checkpoint"), alias="checkpointId")
    task_id: str = Field(alias="taskId")
    step_execution_id: str = Field(alias="stepExecutionId")
    checkpoint_type: CheckpointType = Field(default=CheckpointType.AUTO, alias="checkpointType")
    state_data: Dict[str, Any] = Field(default_factory=dict, alias="stateData")
    created_time: datetime = Field(default_factory=_utc_now, alias="createdTime")
    metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ACGTaskStatus", "StepExecutionStatus", "AgentInstanceStatus", "CheckpointType",
    "ACGTask", "StepExecution", "AgentInstance", "EvidenceRecord", "MemorySnapshot", "ACGCheckpoint",
]


class TaskConstraint(ACGRuntimeModel):
    """任务的声明式跨部件约束。"""

    constraint_id: StrictStr = Field(alias="constraintId", min_length=1)
    kind: StrictStr = Field(min_length=1)
    expression: StrictStr = Field(min_length=1)
    required: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskLifecycleEvent(ACGRuntimeModel):
    """任务状态变化的不可变审计事实。"""

    event_id: StrictStr = Field(alias="eventId", min_length=1)
    task_id: StrictStr = Field(alias="taskId", min_length=1)
    event_type: Literal["created", "planned", "started", "completed", "failed", "cancelled"] = Field(alias="eventType")
    occurred_at: datetime = Field(default_factory=_utc_now, alias="occurredAt")
    previous_state: StrictStr | None = Field(default=None, alias="previousState")
    current_state: StrictStr = Field(alias="currentState", min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)


__all__.extend(["TaskConstraint", "TaskLifecycleEvent"])
