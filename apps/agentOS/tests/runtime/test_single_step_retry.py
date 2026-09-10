from __future__ import annotations

import asyncio

import pytest

from components.content import SQLiteContentManifestStore
from components.executor import InMemoryExecutionValueStore
from components.mission_manager.store import WorkflowRegistry
from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan
from contracts.workflow import StepStatus, WorkflowDefinition, WorkflowStatus, WorkflowStepDefinition
from domain.models import AttemptStatus, RunStatus
from runtime.workflow_runtime import ExecutionRuntime
from runtime.v2 import AcgIdentityLifecycleService, IdentityProjectionBridge
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _RetryAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(
            agentName="retry-agent",
            domain="general",
            capabilities=["analysis", "artifact_generation"],
        ))
        self.final_calls = 0
        self.source_calls = 0

    async def run(self, context):
        if context.step.step_id == "final":
            self.final_calls += 1
            if self.final_calls == 1:
                raise RuntimeError("planned final-node failure")
            return AgentOutput(
                output={
                    "artifacts": [{
                        "title": "Recovered deliverable",
                        "content": "# Recovered deliverable\n",
                    }],
                },
                summary="recovered final deliverable",
            )
        self.source_calls += 1
        return AgentOutput(output={"source": "verified upstream"}, summary="upstream ready")


class _CheckpointResumeAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(
            agentName="checkpoint-agent",
            domain="general",
            capabilities=["analysis"],
        ))
        self.calls = {"source": 0, "design": 0, "final": 0}

    async def run(self, context):
        step_id = context.step.step_id
        self.calls[step_id] += 1
        if step_id == "design" and self.calls[step_id] == 1:
            raise RuntimeError("planned middle-node failure")
        return AgentOutput(output={step_id: f"{step_id}-output"}, summary=f"{step_id} ready")


def _retry_runtime(
    tmp_path,
    agent: _RetryAgent,
    *,
    with_identity: bool = False,
) -> tuple[ExecutionRuntime, ACGBlueprint]:
    agents = AgentRegistry()
    agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="single-step-retry",
        name="single-step retry",
        domain="general",
        runtimeEngine="acg",
        steps=[WorkflowStepDefinition(
            stepId="placeholder",
            name="placeholder",
            agentName="retry-agent",
        )],
    ))
    blueprint = ACGBlueprint(
        graphId="single-step-retry-graph",
        nodes=[
            StepNode(
                nodeId="source",
                name="source",
                agentName="retry-agent",
                capability="analysis",
                outputSpec={
                    "type": "object",
                    "required": ["source"],
                    "properties": {"source": {"type": "string"}},
                },
            ),
            StepNode(
                nodeId="final",
                name="final",
                agentName="retry-agent",
                capability="artifact_generation",
                logicalRole="finalization",
                inputSpec={"from": {"source": ["source"]}},
                outputSpec={
                    "type": "object",
                    "required": ["artifacts"],
                    "properties": {"artifacts": {"type": "array"}},
                },
            ),
        ],
        edges=[ACGEdge(sourceId="source", targetId="final", edgeType=EdgeType.DEPENDENCY)],
    )
    content_manifest_store = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    identity_lifecycle = None
    if with_identity:
        identity_service = AcgIdentityLifecycleService(
            SQLiteV2Repositories(SQLiteV2Storage(":memory:"))
        )
        identity_lifecycle = IdentityProjectionBridge(
            identity_service,
            identity_service.repositories,
            content_manifest_store,
        )
    return ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        execution_value_store=InMemoryExecutionValueStore(),
        content_manifest_store=content_manifest_store,
        identity_lifecycle=identity_lifecycle,
    ), blueprint


@pytest.mark.parametrize("with_identity", [False, True])
def test_single_step_retry_reuses_committed_upstream_and_runs_only_final(
    tmp_path,
    with_identity: bool,
) -> None:
    agent = _RetryAgent()
    runtime, blueprint = _retry_runtime(tmp_path, agent, with_identity=with_identity)
    try:
        mission = runtime.create_mission("single-step retry", workflow_id="single-step-retry")
        plan = TaskPlan(
            missionId=mission.mission_id,
            nodes=tuple(
                PlannedTask(
                    key=f"step:{node.node_id}",
                    title=node.name or node.node_id,
                    objective=node.goal or node.node_id,
                    capabilityRequirements=(node.capability,) if node.capability else (),
                    logicalRole=node.logical_role,
                )
                for node in blueprint.step_nodes()
            ),
        )
        mission.input.update({
            "acgBlueprint": blueprint.model_dump(by_alias=True, mode="json"),
            "taskPlan": plan.model_dump(by_alias=True, mode="json"),
            "taskBindings": [
                TaskImplementationBinding(
                    planNodeKey=f"step:{node.node_id}",
                    acgNodeId=node.node_id,
                ).model_dump(by_alias=True, mode="json")
                for node in blueprint.step_nodes()
            ],
        })
        runtime.workflow_store.save_mission(mission)
        _, source = runtime.prepare_run(mission.mission_id)

        with pytest.raises(RuntimeError, match="ACG superstep failed"):
            asyncio.run(runtime.execute_prepared_run(source.run_id))

        failed = runtime.get_status(source.run_id)
        assert failed.status is WorkflowStatus.FAILED
        assert failed.get_step("source").status is StepStatus.COMPLETED
        assert failed.get_step("final").status is StepStatus.FAILED
        source_ref = failed.execution_state["outputRefs"]["source"]
        assert failed.active_step_ids == []
        failed.execution_state["activeStepIds"] = ["final"]
        runtime.workflow_store.save_run(failed)

        retry = runtime.prepare_single_step_retry(
            failed.run_id,
            "final",
            reason="retry the failed final node",
            expected_runtime_revision=failed.runtime_revision,
            idempotency_key="single-step-retry-request",
            idempotency_fingerprint="single-step-retry-fingerprint",
        )

        assert retry.run_id != failed.run_id
        assert retry.status is WorkflowStatus.PENDING
        assert retry.current_step_id == "final"
        assert retry.completed_step_ids == ["source"]
        assert retry.get_step("source").status is StepStatus.COMPLETED
        assert retry.get_step("final").status is StepStatus.PENDING
        assert retry.execution_state["singleStepRetry"] == {
            "sourceRunId": failed.run_id,
            "targetStepId": "final",
            "reason": "retry the failed final node",
            "reusedStepIds": ["source"],
        }
        retry_ref = retry.execution_state["outputRefs"]["source"]
        assert retry_ref != source_ref
        assert runtime.execution_value_store.get_output(
            run_id=retry.run_id,
            output_ref=retry_ref,
        ) == runtime.execution_value_store.get_output(
            run_id=failed.run_id,
            output_ref=source_ref,
        )
        assert failed.execution_state["outputRefs"]["source"] == source_ref

        repeated = runtime.prepare_single_step_retry(
            failed.run_id,
            "final",
            idempotency_key="single-step-retry-request",
            idempotency_fingerprint="single-step-retry-fingerprint",
        )
        assert repeated.run_id == retry.run_id

        result = asyncio.run(runtime.execute_prepared_run(retry.run_id))
        assert result.status is WorkflowStatus.COMPLETED
        assert result.completed_step_ids == ["source", "final"]
        assert agent.source_calls == 1
        assert agent.final_calls == 2
        assert result.output["outputRef"] == result.execution_state["outputRefs"]["final"]
        assert result.execution_state["reusedStepIds"] == ["source"]
    finally:
        if runtime.identity_lifecycle is not None:
            runtime.identity_lifecycle.lifecycle_service.close()


@pytest.mark.parametrize("with_identity", [False, True])
def test_checkpoint_resume_can_retry_failed_step_in_the_same_run(
    tmp_path,
    with_identity: bool,
) -> None:
    agent = _CheckpointResumeAgent()
    agents = AgentRegistry()
    agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="checkpoint-resume",
        name="checkpoint resume",
        domain="general",
        runtimeEngine="acg",
        steps=[WorkflowStepDefinition(
            stepId="placeholder",
            name="placeholder",
            agentName="checkpoint-agent",
        )],
    ))
    blueprint = ACGBlueprint(
        graphId="checkpoint-resume-graph",
        nodes=[
            StepNode(
                nodeId=step_id,
                name=step_id,
                agentName="checkpoint-agent",
                capability="analysis",
                outputSpec={
                    "type": "object",
                    "required": [step_id],
                    "properties": {step_id: {"type": "string"}},
                },
            )
            for step_id in ("source", "design", "final")
        ],
        edges=[
            ACGEdge(sourceId="source", targetId="design", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(sourceId="design", targetId="final", edgeType=EdgeType.DEPENDENCY),
        ],
    )
    identity_service = (
        AcgIdentityLifecycleService(SQLiteV2Repositories(SQLiteV2Storage(":memory:")))
        if with_identity
        else None
    )
    content_manifest_store = SQLiteContentManifestStore(tmp_path / "checkpoint-content.sqlite3")
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        execution_value_store=InMemoryExecutionValueStore(),
        content_manifest_store=content_manifest_store,
        identity_lifecycle=(
            IdentityProjectionBridge(
                identity_service,
                identity_service.repositories,
                content_manifest_store,
            )
            if identity_service is not None
            else None
        ),
    )
    mission = runtime.create_mission("checkpoint resume", workflow_id="checkpoint-resume")
    plan = TaskPlan(
        missionId=mission.mission_id,
        nodes=tuple(
            PlannedTask(
                key=f"step:{node.node_id}",
                title=node.name or node.node_id,
                objective=node.goal or node.node_id,
                capabilityRequirements=(node.capability,) if node.capability else (),
                logicalRole=node.logical_role,
            )
            for node in blueprint.step_nodes()
        ),
    )
    mission.input.update({
        "acgBlueprint": blueprint.model_dump(by_alias=True, mode="json"),
        "taskPlan": plan.model_dump(by_alias=True, mode="json"),
        "taskBindings": [
            TaskImplementationBinding(
                planNodeKey=f"step:{node.node_id}",
                acgNodeId=node.node_id,
            ).model_dump(by_alias=True, mode="json")
            for node in blueprint.step_nodes()
        ],
    })
    runtime.workflow_store.save_mission(mission)
    _, source = runtime.prepare_run(mission.mission_id)

    with pytest.raises(RuntimeError, match="ACG superstep failed"):
        asyncio.run(runtime.execute_prepared_run(source.run_id))

    failed = runtime.get_status(source.run_id)
    assert failed.get_step("source").status is StepStatus.COMPLETED
    assert failed.get_step("design").status is StepStatus.FAILED
    assert failed.get_step("final").status is StepStatus.PENDING

    retry = runtime.prepare_single_step_retry(
        failed.run_id,
        "design",
        reason="resume from the failed design step",
        idempotency_key="same-run-retry",
        idempotency_fingerprint="same-run-retry-fingerprint",
        reuse_source_run=True,
    )

    assert retry.run_id == failed.run_id
    assert retry.status is WorkflowStatus.RETRYING
    assert retry.execution_state["checkpointResume"] == {
        "sourceRunId": failed.run_id,
        "failedStepId": "design",
        "reason": "resume from the failed design step",
        "reusedStepIds": ["source"],
        "resumeStepIds": ["design", "final"],
        "mode": "current_run",
    }
    assert retry.get_step("source").status is StepStatus.COMPLETED
    assert retry.get_step("design").status is StepStatus.PENDING
    assert retry.get_step("final").status is StepStatus.PENDING
    if identity_service is not None:
        identity_run = identity_service.repositories.runs.get(retry.run_id)
        assert identity_run is not None
        assert identity_run.status is RunStatus.PENDING
        assert identity_run.finished_at is None
        assert retry.get_step("design").attempt == 1
        assert retry.get_step("final").attempt == 0

    result = asyncio.run(runtime.execute_prepared_run(retry.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.completed_step_ids == ["source", "design", "final"]
    assert agent.calls == {"source": 1, "design": 2, "final": 1}
    if identity_service is not None:
        assert identity_service.repositories.runs.get(result.run_id).status is RunStatus.SUCCEEDED
        identity_service.close()


class _TwiceFailingDesignAgent(BaseAgent):
    """design fails on its first two executions, then succeeds."""

    def __init__(self) -> None:
        super().__init__(AgentProfile(
            agentName="checkpoint-agent",
            domain="general",
            capabilities=["analysis"],
        ))
        self.calls = {"source": 0, "design": 0, "final": 0}

    async def run(self, context):
        step_id = context.step.step_id
        self.calls[step_id] += 1
        if step_id == "design" and self.calls[step_id] <= 2:
            raise RuntimeError(f"planned design failure #{self.calls[step_id]}")
        return AgentOutput(output={step_id: f"{step_id}-output"}, summary=f"{step_id} ready")


def _twice_failure_runtime(tmp_path):
    agent = _TwiceFailingDesignAgent()
    agents = AgentRegistry()
    agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="checkpoint-resume",
        name="checkpoint resume",
        domain="general",
        runtimeEngine="acg",
        steps=[WorkflowStepDefinition(
            stepId="placeholder",
            name="placeholder",
            agentName="checkpoint-agent",
        )],
    ))
    blueprint = ACGBlueprint(
        graphId="checkpoint-resume-graph",
        nodes=[
            StepNode(
                nodeId=step_id,
                name=step_id,
                agentName="checkpoint-agent",
                capability="analysis",
                outputSpec={
                    "type": "object",
                    "required": [step_id],
                    "properties": {step_id: {"type": "string"}},
                },
            )
            for step_id in ("source", "design", "final")
        ],
        edges=[
            ACGEdge(sourceId="source", targetId="design", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(sourceId="design", targetId="final", edgeType=EdgeType.DEPENDENCY),
        ],
    )
    identity_service = AcgIdentityLifecycleService(
        SQLiteV2Repositories(SQLiteV2Storage(":memory:"))
    )
    content_manifest_store = SQLiteContentManifestStore(tmp_path / "twice-failure-content.sqlite3")
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        execution_value_store=InMemoryExecutionValueStore(),
        content_manifest_store=content_manifest_store,
        identity_lifecycle=IdentityProjectionBridge(
            identity_service,
            identity_service.repositories,
            content_manifest_store,
        ),
    )
    mission = runtime.create_mission("second checkpoint resume", workflow_id="checkpoint-resume")
    plan = TaskPlan(
        missionId=mission.mission_id,
        nodes=tuple(
            PlannedTask(
                key=f"step:{node.node_id}",
                title=node.name or node.node_id,
                objective=node.goal or node.node_id,
                capabilityRequirements=(node.capability,) if node.capability else (),
                logicalRole=node.logical_role,
            )
            for node in blueprint.step_nodes()
        ),
    )
    mission.input.update({
        "acgBlueprint": blueprint.model_dump(by_alias=True, mode="json"),
        "taskPlan": plan.model_dump(by_alias=True, mode="json"),
        "taskBindings": [
            TaskImplementationBinding(
                planNodeKey=f"step:{node.node_id}",
                acgNodeId=node.node_id,
            ).model_dump(by_alias=True, mode="json")
            for node in blueprint.step_nodes()
        ],
    })
    runtime.workflow_store.save_mission(mission)
    return runtime, identity_service, mission, agent


def test_second_in_place_resume_keeps_attempt_numbering_contiguous(tmp_path) -> None:
    """同一 Run 的第二次原地断点恢复不得毒化身份编号（2026-09-10 16:26 事故回归）。

    对"投影里已有 attempt 历史"的 step 再次发起断点恢复时，发射侧编号与投影
    既有行数必然错位；投影必须以 attemptId 为幂等锚点自动衔接编号，恢复链路
    才能继续复用已完成的 source 节点。
    """
    runtime, identity_service, mission, agent = _twice_failure_runtime(tmp_path)
    try:
        _, source = runtime.prepare_run(mission.mission_id)
        with pytest.raises(RuntimeError, match="ACG superstep failed"):
            asyncio.run(runtime.execute_prepared_run(source.run_id))

        first_retry = runtime.prepare_single_step_retry(
            source.run_id,
            "design",
            reason="first in-place resume",
            idempotency_key="same-run-retry-1",
            idempotency_fingerprint="same-run-retry-1-fingerprint",
            reuse_source_run=True,
        )
        assert first_retry.run_id == source.run_id
        assert first_retry.get_step("design").attempt == 1
        with pytest.raises(RuntimeError, match="ACG superstep failed"):
            asyncio.run(runtime.execute_prepared_run(first_retry.run_id))

        second_retry = runtime.prepare_single_step_retry(
            source.run_id,
            "design",
            reason="second in-place resume",
            idempotency_key="same-run-retry-2",
            idempotency_fingerprint="same-run-retry-2-fingerprint",
            reuse_source_run=True,
        )

        assert second_retry.run_id == source.run_id
        assert second_retry.status is WorkflowStatus.RETRYING
        assert second_retry.get_step("source").status is StepStatus.COMPLETED
        assert second_retry.get_step("design").attempt == 2

        result = asyncio.run(runtime.execute_prepared_run(second_retry.run_id))

        assert result.status is WorkflowStatus.COMPLETED
        assert result.completed_step_ids == ["source", "design", "final"]
        assert agent.calls == {"source": 1, "design": 3, "final": 1}

        repositories = identity_service.repositories
        assert repositories.runs.get(result.run_id).status is RunStatus.SUCCEEDED
        domain_run = repositories.runs.get(result.run_id)
        design_task = runtime.identity_lifecycle._resolve_semantic_task(
            domain_run.blueprint_id, "design"
        )
        design_attempts = sorted(
            (
                attempt
                for attempt in repositories.attempts.list_for_run(result.run_id)
                if attempt.task_id == design_task.task_id
            ),
            key=lambda attempt: attempt.attempt_number,
        )
        assert [attempt.attempt_number for attempt in design_attempts] == [1, 2, 3]
        assert design_attempts[-1].status is AttemptStatus.SUCCEEDED
    finally:
        identity_service.close()
