"""WKN 唯一执行内核与 AgentOS V2 身份链的真实纵向接线。"""

from __future__ import annotations

import asyncio

import pytest

from components.task_manager.store import WorkflowRegistry
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from domain.identity_graph import IdentityResolver
from domain.models import AttemptStatus, RunStatus, StepExecutionStatus
from runtime.v2 import WknAcgIdentityBridge, WorkflowRuntimeV2
from runtime.workflow_runtime import WorkflowRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage
from support.acg.models import ACGBlueprint, StepNode
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _IdentityAgent(BaseAgent):
    async def run(self, context):
        if context.task.input.get("forceFailure"):
            raise RuntimeError("identity vertical slice failure")
        return AgentOutput(
            output={"result": context.step.step_id},
            summary=f"completed:{context.step.step_id}",
            evidenceRefs=[f"evidence:{context.step.step_id}"],
        )


def _runtime(*, force_failure: bool = False, blueprint: ACGBlueprint | None = None):
    repositories = SQLiteV2Repositories(SQLiteV2Storage(":memory:"))
    identity_runtime = WorkflowRuntimeV2(repositories)
    bridge = WknAcgIdentityBridge(identity_runtime, repositories)
    agents = AgentRegistry()
    agents.register(_IdentityAgent(AgentProfile(
        agentId="agent-identity",
        agentName="identity-agent",
        domain="general",
        capabilities=["analysis"],
    )))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="identity-acg",
        name="identity acg",
        domain="general",
        runtimeEngine="acg",
        steps=[WorkflowStepDefinition(
            stepId="analyse",
            name="分析任务",
            agentName="identity-agent",
            capability="analysis",
            outputSpec={"type": "object", "properties": {"result": {"type": "string"}}},
        )],
    ))
    runtime = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        identity_lifecycle=bridge,
    )
    task = runtime.create_task(
        "身份纵向测试",
        workflow_id="identity-acg",
        input={
            "authenticatedUserId": "user-identity",
            "forceFailure": force_failure,
        }
        | (
            {"acgBlueprint": blueprint.model_dump(by_alias=True, mode="json")}
            if blueprint is not None
            else {}
        ),
    )
    return runtime, identity_runtime, bridge, task


def test_wkn_execution_reuses_agentos_task_run_and_attempt_ids() -> None:
    runtime, identity_runtime, _bridge, task = _runtime()
    try:
        _, run = runtime.prepare_run(task.task_id)
        result = asyncio.run(runtime.execute_prepared_run(run.run_id))

        repositories = identity_runtime.repositories
        domain_task = repositories.user_tasks.get(task.task_id)
        domain_run = repositories.runs.get(run.run_id)
        attempts = repositories.attempts.list_for_run(run.run_id)
        executions = repositories.step_executions.list_for_attempt(attempts[0].attempt_id)
        binding = repositories.execution_bindings.get_for_attempt(attempts[0].attempt_id)
        origin = IdentityResolver(repositories).resolve_execution_origin(
            executions[0].step_execution_id
        )

        assert task.task_id.startswith("task_")
        assert run.run_id.startswith("run_")
        assert result.status is WorkflowStatus.COMPLETED
        assert domain_task is not None and domain_task.task_id == task.task_id
        assert domain_run is not None and domain_run.run_id == run.run_id
        assert domain_run.status is RunStatus.SUCCEEDED
        assert len(attempts) == 1
        assert attempts[0].attempt_id.startswith("attempt_")
        assert attempts[0].status is AttemptStatus.SUCCEEDED
        assert executions[0].status is StepExecutionStatus.SUCCEEDED
        assert executions[0].output["outputRef"].startswith("output:")
        assert binding is not None
        assert binding.metadata["wknBindingId"].startswith("binding:")
        assert result.execution_state["schedulingDecisions"][0]["attemptId"] == attempts[0].attempt_id
        assert origin.user_task.task_id == task.task_id
        assert origin.run.run_id == run.run_id
        assert origin.task_node_binding.acg_node_id == "analyse"
        assert origin.execution_binding.agent_id == "agent-identity"
    finally:
        identity_runtime.close()


def test_wkn_failure_finishes_same_attempt_and_run_identity() -> None:
    runtime, identity_runtime, _bridge, task = _runtime(force_failure=True)
    try:
        _, run = runtime.prepare_run(task.task_id)
        with pytest.raises(Exception):
            asyncio.run(runtime.execute_prepared_run(run.run_id))

        attempts = identity_runtime.repositories.attempts.list_for_run(run.run_id)
        execution = identity_runtime.repositories.step_executions.list_for_attempt(
            attempts[0].attempt_id
        )[0]
        assert identity_runtime.repositories.runs.get(run.run_id).status is RunStatus.FAILED
        assert attempts[0].status is AttemptStatus.FAILED
        assert attempts[0].failure_reason == "identity vertical slice failure"
        assert execution.status is StepExecutionStatus.FAILED
    finally:
        identity_runtime.close()


def test_identity_attempt_and_binding_hooks_are_idempotent() -> None:
    runtime, identity_runtime, bridge, task = _runtime()
    try:
        _, run = runtime.prepare_run(task.task_id)
        first = bridge.ensure_attempt(run, "analyse", 1)
        second = bridge.ensure_attempt(run, "analyse", 1)
        assert first == second
        assert len(identity_runtime.repositories.attempts.list_for_run(run.run_id)) == 1
    finally:
        identity_runtime.close()


def test_parallel_wkn_nodes_keep_attempt_and_execution_identity_isolated() -> None:
    blueprint = ACGBlueprint(
        graphId="identity-parallel-graph",
        nodes=[
            StepNode(nodeId="left", agentName="identity-agent", capability="analysis"),
            StepNode(nodeId="right", agentName="identity-agent", capability="analysis"),
        ],
    )
    runtime, identity_runtime, _bridge, task = _runtime(blueprint=blueprint)
    try:
        _, run = runtime.prepare_run(task.task_id)
        result = asyncio.run(runtime.execute_prepared_run(run.run_id))

        attempts = identity_runtime.repositories.attempts.list_for_run(run.run_id)
        executions = [
            execution
            for attempt in attempts
            for execution in identity_runtime.repositories.step_executions.list_for_attempt(
                attempt.attempt_id
            )
        ]
        assert result.status is WorkflowStatus.COMPLETED
        assert {attempt.node_id for attempt in attempts} == {
            execution.node_id for execution in executions
        }
        assert len({attempt.attempt_id for attempt in attempts}) == 2
        assert len({execution.step_execution_id for execution in executions}) == 2
        assert all(execution.run_id == run.run_id for execution in executions)
    finally:
        identity_runtime.close()


def test_cancelling_prepared_wkn_run_projects_cancelled_terminal_state() -> None:
    runtime, identity_runtime, _bridge, task = _runtime()
    try:
        _, run = runtime.prepare_run(task.task_id)
        cancelled = runtime.cancel(run.run_id)

        assert cancelled.status is WorkflowStatus.CANCELLED
        assert identity_runtime.repositories.runs.get(run.run_id).status is RunStatus.CANCELLED
    finally:
        identity_runtime.close()


def test_wkn_graph_revision_creates_new_blueprint_version_for_same_run() -> None:
    runtime, identity_runtime, bridge, task = _runtime()
    try:
        _, run = runtime.prepare_run(task.task_id)
        original = identity_runtime.repositories.runs.get(run.run_id)
        revised = ACGBlueprint.model_validate(run.acg_blueprint).model_copy(deep=True)
        revised.version += 1
        revised.nodes.append(
            StepNode(
                nodeId="verify",
                agentName="identity-agent",
                capability="analysis",
            )
        )

        bridge.on_blueprint_revised(run, revised)

        updated = identity_runtime.repositories.runs.get(run.run_id)
        assert updated.blueprint_id != original.blueprint_id
        assert updated.graph_version == original.graph_version + 1
        assert len(identity_runtime.repositories.blueprints.list_for_task(task.task_id)) == 2
        assert bridge.ensure_attempt(run, "verify", 1).startswith("attempt_")
    finally:
        identity_runtime.close()


def test_same_user_task_can_execute_another_run_after_success() -> None:
    runtime, identity_runtime, _bridge, task = _runtime()
    try:
        _, first = runtime.prepare_run(task.task_id)
        asyncio.run(runtime.execute_prepared_run(first.run_id))

        _, second = runtime.prepare_run(task.task_id)
        result = asyncio.run(runtime.execute_prepared_run(second.run_id))

        runs = identity_runtime.repositories.runs.list_for_task(task.task_id)
        assert first.run_id != second.run_id
        assert result.status is WorkflowStatus.COMPLETED
        assert [item.status for item in runs] == [RunStatus.SUCCEEDED, RunStatus.SUCCEEDED]
    finally:
        identity_runtime.close()
