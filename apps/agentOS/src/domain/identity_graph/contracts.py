"""IdentityResolver 返回的完整执行来源快照。"""

from pydantic import Field

from domain.models import AcgBlueprint, Attempt, DomainModel, StepExecution, SemanticTask, Mission, WorkflowRun

from .bindings import ExecutionBinding, TaskBinding


class ExecutionOrigin(DomainModel):
    mission: Mission
    semantic_task: SemanticTask = Field(alias="task")
    blueprint: AcgBlueprint
    run: WorkflowRun
    attempt: Attempt
    step_execution: StepExecution = Field(alias="stepExecution")
    task_binding: TaskBinding = Field(alias="taskBinding")
    execution_binding: ExecutionBinding = Field(alias="executionBinding")


__all__ = ["ExecutionOrigin"]
