"""融合 ACG 运行时的端到端执行测试。"""

from __future__ import annotations

import asyncio

import pytest

from runtime.workflow_runtime import WorkflowRuntime
from components.executor.value_store import SQLiteExecutionValueStore
from components.memory.store import SQLiteMemoryStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.executor.graph import ACGExecutionState
from components.task_manager.store import WorkflowRegistry
from contracts.workflow import ReviewDecision, ReviewDecisionType, WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.acg.models import ACGBlueprint, ACGEdge, ConditionOperator, ConditionSpec, ControlNode, ControlType, EdgeType, StepNode


class _RunAgent(BaseAgent):
    """以最小确定性输出验证 Runtime 的引用式执行路径。"""

    async def run(self, context):
        if context.step.step_id == "extract":
            return AgentOutput(output={"title": "AgentOS", "secret": "hidden"}, summary="extracted")
        return AgentOutput(output={"summary": context.context_pack.data.get("title", "reviewed")}, summary="summarized")


def _runtime() -> WorkflowRuntime:
    """建立含两步严格合同 ACG 的独立内存运行时。"""
    agents = AgentRegistry()
    agents.register(_RunAgent(AgentProfile(agentName="runner", domain="general")))
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="acg-run",
            name="ACG run",
            domain="general",
            runtimeEngine="acg",
            steps=[
                WorkflowStepDefinition(
                    stepId="extract",
                    name="extract",
                    agentName="runner",
                    outputSpec={"type": "object", "properties": {"title": {"type": "string"}}},
                ),
                WorkflowStepDefinition(
                    stepId="summarize",
                    name="summarize",
                    agentName="runner",
                    input={"from": {"extract": ["title"]}},
                    outputSpec={"type": "object", "properties": {"summary": {"type": "string"}}},
                ),
            ],
        )
    )
    return WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    )


def test_runtime_executes_prepared_acg_with_reference_state() -> None:
    """新 ACG run 应完成，运行投影只能含引用而不能含节点输出正文。"""
    runtime = _runtime()
    task = runtime.create_task("run", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.task_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.execution_state["engineMigration"] == "langgraph_fused_v1"
    assert result.runtime_graph is None
    assert result.output["outputRef"].startswith("output:")
    assert "title" not in result.execution_state
    latest_id, latest_state = runtime.checkpoint_store.load_latest(run_id=result.run_id)
    assert latest_id == result.execution_state["checkpointId"]
    assert latest_state["checkpointId"] == latest_id
    assert latest_state["completedStepIds"] == ["extract", "summarize"]


def test_runtime_resumes_review_checkpoint_after_recreation(tmp_path) -> None:
    """重建 Runtime 后应从 SQLite 审核检查点继续，审核步骤不得再次执行。"""
    agents = AgentRegistry()
    agent = _RunAgent(AgentProfile(agentName="runner", domain="general"))
    agents.register(agent)
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="acg-review",
            name="ACG review",
            domain="general",
            runtimeEngine="acg",
            steps=[
                WorkflowStepDefinition(stepId="review", name="review", agentName="runner", reviewRequired=True),
                WorkflowStepDefinition(stepId="deliver", name="deliver", agentName="runner"),
            ],
        )
    )
    store = MemoryWorkflowStore()
    checkpoint_db = tmp_path / "checkpoints.sqlite3"
    value_db = tmp_path / "values.sqlite3"
    first = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=checkpoint_db),
        execution_value_store=SQLiteExecutionValueStore(db_path=value_db),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
    )
    task = first.create_task("review", workflow_id="acg-review")
    _, run = first.prepare_run(task.task_id)

    paused = asyncio.run(first.execute_prepared_run(run.run_id))

    assert paused.status is WorkflowStatus.WAITING_REVIEW
    assert paused.execution_state["checkpointId"].startswith("acgckpt_")
    recreated = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=checkpoint_db),
        execution_value_store=SQLiteExecutionValueStore(db_path=value_db),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
    )

    result = asyncio.run(recreated.apply_review(ReviewDecision(
        runId=run.run_id,
        stepId="review",
        decision=ReviewDecisionType.APPROVED,
        operationId="approve-1",
    )))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.completed_step_ids == ["review", "deliver"]


def test_execute_prepared_run_does_not_restart_waiting_review_run() -> None:
    """等待审核的运行重复调用执行入口时必须保持暂停，不得重跑节点。"""
    runtime = _runtime()
    runtime.workflow_registry.register(WorkflowDefinition(
        workflowId="acg-wait", name="wait", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="review", name="review", agentName="runner", reviewRequired=True)],
    ))
    task = runtime.create_task("wait", workflow_id="acg-wait")
    _, run = runtime.prepare_run(task.task_id)
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))

    repeated = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert paused.status is WorkflowStatus.WAITING_REVIEW
    assert repeated.status is WorkflowStatus.WAITING_REVIEW
    assert repeated.execution_state["checkpointId"] == paused.execution_state["checkpointId"]


def test_runtime_projects_model_metadata_without_generated_content() -> None:
    """运行 Trace 只能记录模型调用元数据，不能记录 Agent 输出正文。"""
    class ModelAgent(_RunAgent):
        async def run(self, context):
            return AgentOutput(
                output={"title": "secret output"},
                modelInvocations=[{
                    "provider": "local",
                    "model": "unit",
                    "usage": {"tokens": 2},
                    "prompt": "must-not-trace",
                    "response": "must-not-trace",
                }],
            )

    agents = AgentRegistry()
    agents.register(ModelAgent(AgentProfile(agentName="runner", domain="general")))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="model-run", name="model", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="one", name="one", agentName="runner")],
    ))
    runtime = WorkflowRuntime(agent_registry=agents, workflow_registry=workflows, workflow_store=MemoryWorkflowStore())
    task = runtime.create_task("model", workflow_id="model-run")
    _, run = runtime.prepare_run(task.task_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    model_events = [event for event in result.trace if event.event_type.value == "model_called"]
    assert model_events[0].payload == {"provider": "local", "model": "unit", "usage": {"tokens": 2}}


def test_runtime_rejects_checkpoint_from_different_graph_version(tmp_path) -> None:
    """恢复前必须确认 checkpoint 与运行时冻结的图及版本完全一致。"""
    runtime = _runtime()
    runtime.checkpoint_store = ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3")
    task = runtime.create_task("version", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.task_id)
    checkpoint_id = runtime.checkpoint_store.save(
        run_id=run.run_id,
        state=ACGExecutionState(runId=run.run_id, graphId="different-graph").model_dump(by_alias=True),
    )

    with pytest.raises(ValueError, match="graphId"):
        asyncio.run(runtime.resume_from_checkpoint(run_id=run.run_id, checkpoint_id=checkpoint_id))

    assert runtime.workflow_store.get_run(run.run_id).status is not WorkflowStatus.RUNNING


def test_runtime_projects_safe_tool_call_metadata() -> None:
    """工具 Trace 只记录名称等元数据，不记录参数正文。"""
    class ToolAgent(_RunAgent):
        async def run(self, context):
            return AgentOutput(
                output={"answer": "done"},
                toolExecutions=[{
                    "tool": "lookup",
                    "status": "success",
                    "arguments": {"secret": "must-not-trace"},
                }],
            )

    agents = AgentRegistry()
    agents.register(ToolAgent(AgentProfile(agentName="runner", domain="general", allowedTools=["lookup"])))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="tool-run", name="tool", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="one", name="one", agentName="runner")],
    ))
    runtime = WorkflowRuntime(agent_registry=agents, workflow_registry=workflows, workflow_store=MemoryWorkflowStore())
    task = runtime.create_task("tool", workflow_id="tool-run")
    _, run = runtime.prepare_run(task.task_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    tool_events = [event for event in result.trace if event.event_type.value == "tool_called"]
    assert tool_events[0].payload == {"tool": "lookup", "status": "success"}


def test_runtime_marks_unselected_acg_branch_skipped() -> None:
    """Runtime 投影应把条件未选分支明确标为 skipped_by_condition。"""
    agents = AgentRegistry()

    class RouteAgent(_RunAgent):
        async def run(self, context):
            if context.step.step_id == "source":
                return AgentOutput(output={"approved": True}, summary="routed")
            return AgentOutput(output={"answer": context.step.step_id}, summary=context.step.step_id)

    agents.register(RouteAgent(AgentProfile(agentName="runner", domain="general")))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="route-run", name="route", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="placeholder", name="placeholder", agentName="runner")],
    ))
    blueprint = ACGBlueprint(
        graphId="route-runtime", taskId="task-route",
        nodes=[
            StepNode(nodeId="source", agentName="runner", outputSpec={"type": "object", "properties": {"approved": {"type": "boolean"}}}),
            ControlNode(nodeId="if", controlType=ControlType.IF,
                        conditionSpec=ConditionSpec(sourceNodeId="source", jsonPointer="/approved", operator=ConditionOperator.BOOLEAN, cases={"true": "yes-edge", "false": "no-edge"}),
                        branchEdgeIds=["yes-edge", "no-edge"]),
            StepNode(nodeId="yes", agentName="runner"),
            StepNode(nodeId="no", agentName="runner"),
        ],
        edges=[
            ACGEdge(sourceId="source", targetId="if", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(edgeId="yes-edge", sourceId="if", targetId="yes", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(edgeId="no-edge", sourceId="if", targetId="no", edgeType=EdgeType.DEPENDENCY),
        ],
    )
    runtime = WorkflowRuntime(agent_registry=agents, workflow_registry=workflows, workflow_store=MemoryWorkflowStore())
    task = runtime.create_task(
        "route", workflow_id="route-run",
        input={"acgBlueprint": blueprint.model_dump(by_alias=True, mode="json")},
    )
    _, run = runtime.prepare_run(task.task_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.get_step("yes").status.value == "completed"
    assert result.get_step("no").status.value == "skipped_by_condition"
