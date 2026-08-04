"""ACG 动态规划层的数据合同。

这些模型仅定义可序列化结构；调度、持久化和恢复行为仍由既有 RuntimeGraph
与 WorkflowRun 负责。
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
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class AgentInstanceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class CheckpointType(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ACGRuntimeModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ACGTask(ACGRuntimeModel):
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
    evidence_record_id: str = Field(default_factory=lambda: _new_id("evidence_record"), alias="evidenceRecordId")
    evidence_id: str = Field(alias="evidenceId")
    task_id: str = Field(alias="taskId")
    producer_execution_id: Optional[str] = Field(default=None, alias="producerExecutionId")
    content: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    created_time: datetime = Field(default_factory=_utc_now, alias="createdTime")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemorySnapshot(ACGRuntimeModel):
    snapshot_id: str = Field(default_factory=lambda: _new_id("memory_snapshot"), alias="snapshotId")
    task_id: str = Field(alias="taskId")
    memory_id: str = Field(alias="memoryId")
    version: int = 1
    content: Dict[str, Any] = Field(default_factory=dict)
    created_time: datetime = Field(default_factory=_utc_now, alias="createdTime")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ACGCheckpoint(ACGRuntimeModel):
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
