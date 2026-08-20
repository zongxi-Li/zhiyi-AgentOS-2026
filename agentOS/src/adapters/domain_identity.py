"""把旧 Runtime 合同只读投影到未来真源领域模型。"""

from __future__ import annotations

from typing import Any

from contracts.identity import AttemptId, BlueprintId, RunId, TaskNodeId
from contracts.workflow import AgentTask as LegacyAgentTask
from contracts.workflow import WorkflowRun as LegacyWorkflowRun
from contracts.workflow import WorkflowStep as LegacyWorkflowStep
from domain.models import (
    AcgBlueprint,
    Attempt,
    AttemptStatus,
    RunStatus,
    StepExecution,
    StepExecutionStatus,
    UserTask,
    UserTaskStatus,
    WorkflowRun,
)
from support.acg.models import ACGBlueprint as LegacyACGBlueprint


def _legacy_status(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


def _user_task_status(value: Any) -> UserTaskStatus:
    status = _legacy_status(value)
    if status == "pending":
        return UserTaskStatus.CREATED
    if status == "completed":
        return UserTaskStatus.COMPLETED
    if status == "cancelled":
        return UserTaskStatus.ARCHIVED
    # 一次 Run 失败不意味着用户目标失败，目标仍可通过新 Run 继续完成。
    return UserTaskStatus.RUNNING


def _run_status(value: Any) -> RunStatus:
    status = _legacy_status(value)
    aliases = {
        "planning": "pending",
        "retrying": "running",
        "waiting_review": "running",
        "completed": "succeeded",
    }
    return RunStatus(aliases.get(status, status))


def _attempt_status(value: Any) -> AttemptStatus:
    status = _legacy_status(value)
    aliases = {
        "completed": "succeeded",
        "success": "succeeded",
        "retrying": "running",
        "waiting_review": "running",
        "skipped_by_condition": "cancelled",
    }
    return AttemptStatus(aliases.get(status, status))


def _step_execution_status(value: Any) -> StepExecutionStatus:
    return StepExecutionStatus(_attempt_status(value).value)


def agent_task_to_user_task(task: LegacyAgentTask, *, user_id: str | None = None) -> UserTask:
    """投影 AgentTask；用户身份必须来自可信参数或已认证旧输入。"""
    resolved_user_id = str(user_id or task.input.get("authenticatedUserId") or "").strip()
    if not resolved_user_id:
        raise ValueError("legacy AgentTask has no trusted user identity")
    goal = str(
        task.input.get("taskGoal")
        or task.input.get("userIntent")
        or task.title
    ).strip()
    return UserTask(
        taskId=task.task_id,
        userId=resolved_user_id,
        goal=goal,
        description=str(task.input.get("description") or ""),
        metadata={
            "legacy": {
                "domain": task.domain,
                "intent": task.intent,
                "securityLevel": task.security_level,
                "priority": task.priority,
                "recommendedWorkflow": task.recommended_workflow,
                "enabledPluginIds": task.enabled_plugin_ids,
            }
        },
        createdAt=task.created_at,
        updatedAt=task.updated_at,
        status=_user_task_status(task.status),
    )


def acg_blueprint_to_domain(
    blueprint: LegacyACGBlueprint,
    *,
    blueprint_id: BlueprintId,
) -> AcgBlueprint:
    """保留旧 graphId 作为 Runtime Graph 身份，并显式注入 Blueprint 身份。"""
    if blueprint.task_id is None:
        raise ValueError("legacy ACGBlueprint has no taskId")
    graph = blueprint.model_dump(by_alias=True, mode="json")
    return AcgBlueprint(
        blueprintId=blueprint_id,
        taskId=blueprint.task_id,
        version=blueprint.version,
        graphId=blueprint.graph_id,
        graph=graph,
        createdAt=blueprint.created_at,
        metadata={"legacyUpdatedAt": blueprint.updated_at.isoformat()},
    )


def workflow_run_to_domain(
    run: LegacyWorkflowRun,
    *,
    blueprint_id: BlueprintId,
) -> WorkflowRun:
    """投影旧 WorkflowRun；blueprintId 由迁移边界显式提供，禁止猜测。"""
    graph_version = int(run.execution_state.get("graphVersion") or 1)
    checkpoint = None
    if run.checkpoints:
        checkpoint = run.checkpoints[-1].model_dump(by_alias=True, mode="json")
    return WorkflowRun(
        runId=run.run_id,
        taskId=run.task_id,
        blueprintId=blueprint_id,
        status=_run_status(run.status),
        graphVersion=graph_version,
        checkpoint=checkpoint,
        createdAt=run.created_at,
        updatedAt=run.updated_at,
        metadata={
            "legacyWorkflowId": run.workflow_id,
            "runtimeEngine": run.runtime_engine,
        },
    )


def workflow_step_to_attempt(
    step: LegacyWorkflowStep,
    *,
    run_id: RunId,
    node_id: TaskNodeId,
    attempt_id: AttemptId,
    resource_binding: dict[str, Any] | None = None,
) -> Attempt:
    """把旧步骤的当前尝试投影为独立 Attempt。"""
    return Attempt(
        attemptId=attempt_id,
        runId=run_id,
        nodeId=node_id,
        status=_attempt_status(step.status),
        attemptNumber=max(step.attempt, 0) + 1,
        startedAt=step.started_at,
        finishedAt=step.completed_at,
        failureReason=step.error,
        resourceBinding=resource_binding,
    )


def workflow_step_to_execution(
    step: LegacyWorkflowStep,
    *,
    run_id: RunId,
    node_id: TaskNodeId,
    attempt_id: AttemptId,
) -> StepExecution:
    """把旧可变 WorkflowStep 投影为一次 StepExecution 快照。"""
    return StepExecution(
        runId=run_id,
        nodeId=node_id,
        attemptId=attempt_id,
        status=_step_execution_status(step.status),
        input=dict(step.resolved_input or step.input),
        output=dict(step.output),
        startedAt=step.started_at,
        finishedAt=step.completed_at,
    )


__all__ = [
    "acg_blueprint_to_domain",
    "agent_task_to_user_task",
    "workflow_run_to_domain",
    "workflow_step_to_attempt",
    "workflow_step_to_execution",
]
