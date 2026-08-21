"""面向产品 API 的 AgentOS 身份查询模型。"""

from __future__ import annotations

from pydantic import Field

from domain.identity_graph import ExecutionBinding, ProvenanceLink
from domain.identity_graph.contracts import ExecutionOrigin
from domain.models import AcgBlueprint, Attempt, DomainModel, StepExecution, TaskNode, UserTask, WorkflowRun


class TaskDetail(DomainModel):
    task: UserTask
    task_nodes: list[TaskNode] = Field(alias="taskNodes")
    blueprints: list[AcgBlueprint]
    runs: list[WorkflowRun]


class TaskRunHistory(DomainModel):
    task_id: str = Field(alias="taskId")
    runs: list[WorkflowRun]


class AttemptDetail(DomainModel):
    attempt: Attempt
    execution_binding: ExecutionBinding | None = Field(
        default=None,
        alias="executionBinding",
    )
    executions: list[StepExecution]


class AttemptHistory(DomainModel):
    run_id: str = Field(alias="runId")
    node_id: str | None = Field(default=None, alias="nodeId")
    attempts: list[AttemptDetail]


class RunExecutionNode(DomainModel):
    task_node: TaskNode = Field(alias="taskNode")
    acg_node_id: str | None = Field(default=None, alias="acgNodeId")
    attempts: list[AttemptDetail]


class RunExecutionTree(DomainModel):
    run: WorkflowRun
    blueprint: AcgBlueprint
    nodes: list[RunExecutionNode]


class StepExecutionDetail(DomainModel):
    origin: ExecutionOrigin
    provenance_links: list[ProvenanceLink] = Field(alias="provenanceLinks")


class ExecutionProvenance(DomainModel):
    step_execution_id: str = Field(alias="stepExecutionId")
    outgoing: list[ProvenanceLink]
    incoming: list[ProvenanceLink]


__all__ = [
    "AttemptDetail",
    "AttemptHistory",
    "ExecutionProvenance",
    "RunExecutionNode",
    "RunExecutionTree",
    "StepExecutionDetail",
    "TaskDetail",
    "TaskRunHistory",
]
