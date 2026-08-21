"""IdentityResolver 返回的完整执行来源快照。"""

from pydantic import Field

from domain.models import AcgBlueprint, Attempt, DomainModel, StepExecution, TaskNode, UserTask, WorkflowRun

from .bindings import ExecutionBinding, TaskNodeBinding


class ExecutionOrigin(DomainModel):
    user_task: UserTask = Field(alias="userTask")
    task_node: TaskNode = Field(alias="taskNode")
    blueprint: AcgBlueprint
    run: WorkflowRun
    attempt: Attempt
    step_execution: StepExecution = Field(alias="stepExecution")
    task_node_binding: TaskNodeBinding = Field(alias="taskNodeBinding")
    execution_binding: ExecutionBinding = Field(alias="executionBinding")


__all__ = ["ExecutionOrigin"]
