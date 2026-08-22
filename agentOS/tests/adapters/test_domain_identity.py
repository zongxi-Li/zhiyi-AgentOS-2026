from __future__ import annotations

from adapters.domain_identity import (
    acg_blueprint_to_domain,
    mission_record_to_domain,
    runtime_run_to_domain,
    workflow_step_to_attempt,
    workflow_step_to_execution,
)
from contracts.execution import StepStatus
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowStatus, WorkflowStep
from domain.models import AttemptStatus, RunStatus, StepExecutionStatus, MissionStatus
from support.acg.models import ACGBlueprint


def test_agent_task_adapter_does_not_turn_failed_run_state_into_failed_user_goal() -> None:
    legacy = RuntimeMissionRecord(
        missionId="mission_0123456789ab",
        title="合同审查",
        input={"authenticatedUserId": "user-1", "taskGoal": "审查软件开发合同"},
        status=WorkflowStatus.FAILED,
    )

    projected = mission_record_to_domain(legacy)

    assert projected.mission_id == legacy.mission_id
    assert projected.goal == "审查软件开发合同"
    assert projected.status is MissionStatus.RUNNING


def test_blueprint_adapter_keeps_blueprint_and_runtime_graph_id_separate() -> None:
    legacy = ACGBlueprint(
        graphId="acg_runtime_graph_1",
        missionId="mission_0123456789ab",
        nodes=[],
        edges=[],
    )

    projected = acg_blueprint_to_domain(
        legacy,
        blueprint_id="blueprint_0123456789ab",
    )

    assert projected.blueprint_id == "blueprint_0123456789ab"
    assert projected.graph_id == "acg_runtime_graph_1"
    assert projected.graph["graphId"] == "acg_runtime_graph_1"


def test_workflow_run_adapter_requires_explicit_blueprint_identity() -> None:
    legacy = RuntimeRunRecord(
        runId="run_0123456789ab",
        missionId="mission_0123456789ab",
        workflowId="legacy-workflow",
        domain="general",
        runtimeEngine="acg",
        status=WorkflowStatus.COMPLETED,
        executionState={"graphVersion": 3},
    )

    projected = runtime_run_to_domain(
        legacy,
        blueprint_id="blueprint_0123456789ab",
    )

    assert projected.run_id == legacy.run_id
    assert projected.blueprint_id == "blueprint_0123456789ab"
    assert projected.graph_version == 3
    assert projected.status is RunStatus.SUCCEEDED


def test_workflow_step_adapter_creates_attempt_and_step_execution_identities() -> None:
    legacy = WorkflowStep(
        stepId="legacy-step",
        name="风险识别",
        agentName="risk-agent",
        status=StepStatus.COMPLETED,
        attempt=1,
        resolvedInput={"contract": "..."},
        output={"risks": ["risk-1"]},
    )
    kwargs = {
        "run_id": "run_0123456789ab",
        "task_id": "task_0123456789ab",
        "attempt_id": "attempt_0123456789ab",
    }

    attempt = workflow_step_to_attempt(legacy, **kwargs)
    execution = workflow_step_to_execution(legacy, **kwargs)

    assert attempt.status is AttemptStatus.SUCCEEDED
    assert attempt.attempt_number == 2
    assert execution.status is StepExecutionStatus.SUCCEEDED
    assert execution.step_execution_id.startswith("step_execution_")
    assert execution.task_id == kwargs["task_id"]
    assert execution.attempt_id == kwargs["attempt_id"]
