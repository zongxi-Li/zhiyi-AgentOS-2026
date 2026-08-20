"""新运行链路在一次 Run 中传递的最小身份上下文。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from contracts.identity import AttemptId, BlueprintId, RunId, StepExecutionId, UserTaskId


class ExecutionContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", validate_assignment=True)

    run_id: RunId = Field(alias="runId")
    task_id: UserTaskId = Field(alias="taskId")
    blueprint_id: BlueprintId = Field(alias="blueprintId")
    current_attempt: AttemptId | None = Field(default=None, alias="currentAttempt")
    active_executions: list[StepExecutionId] = Field(default_factory=list, alias="activeExecutions")


__all__ = ["ExecutionContext"]
