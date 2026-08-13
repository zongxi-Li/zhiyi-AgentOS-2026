"""融合 ACG 运行时的端到端执行测试。"""

from __future__ import annotations

import asyncio

import pytest

from runtime.workflow_runtime import WorkflowRuntime
from components.executor.value_store import SQLiteExecutionValueStore
from components.memory.store import SQLiteMemoryStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.executor.graph import ACGExecutionState
from components.task_manager.store import WorkflowRegistry
from contracts.workflow import ReviewDecision, ReviewDecisionType, StepStatus, WorkflowDefinition, WorkflowRun, WorkflowStepDefinition, WorkflowStatus
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


def test_runtime_restores_persistent_provenance_before_review_resume(tmp_path) -> None:
    """审核恢复重建 Runtime 时，血缘账本必须先通过校验并从原链继续追加。"""
    agents = AgentRegistry()
    agents.register(_RunAgent(AgentProfile(agentName="runner", domain="general")))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="acg-provenance-review", name="review", domain="general", runtimeEngine="acg",
        steps=[
            WorkflowStepDefinition(stepId="review", name="review", agentName="runner", reviewRequired=True),
            WorkflowStepDefinition(stepId="deliver", name="deliver", agentName="runner"),
        ],
    ))
    store = MemoryWorkflowStore()
    first = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
        execution_value_store=SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3"),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
        provenance_store=SQLiteProvenanceStore(db_path=tmp_path / "provenance.sqlite3"),
    )
    task = first.create_task("review", workflow_id="acg-provenance-review")
    _, run = first.prepare_run(task.task_id)
    paused = asyncio.run(first.execute_prepared_run(run.run_id))

    recreated = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
        execution_value_store=SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3"),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
        provenance_store=SQLiteProvenanceStore(db_path=tmp_path / "provenance.sqlite3"),
    )

    result = asyncio.run(recreated.apply_review(ReviewDecision(
        runId=run.run_id,
        stepId="review",
        decision=ReviewDecisionType.APPROVED,
    )))

    ledger = recreated.provenance_store.load_ledger(run_id=run.run_id, task_id=task.task_id)
    assert result.status is WorkflowStatus.COMPLETED
    assert ledger.verify_integrity() is True
    assert len(ledger.productions) == 2


def test_runtime_refuses_review_resume_when_provenance_chain_is_tampered(tmp_path) -> None:
    """恢复前发现血缘链损坏时必须拒绝，不能继续执行或追加伪造事件。"""
    agents = AgentRegistry()
    agents.register(_RunAgent(AgentProfile(agentName="runner", domain="general")))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="acg-provenance-tampered", name="review", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="review", name="review", agentName="runner", reviewRequired=True)],
    ))
    store = MemoryWorkflowStore()
    provenance_path = tmp_path / "provenance.sqlite3"
    runtime = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
        execution_value_store=SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3"),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
        provenance_store=SQLiteProvenanceStore(db_path=provenance_path),
    )
    task = runtime.create_task("review", workflow_id="acg-provenance-tampered")
    _, run = runtime.prepare_run(task.task_id)
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
    runtime.provenance_store.close()

    import sqlite3
    connection = sqlite3.connect(provenance_path)
    connection.execute(
        "UPDATE acg_provenance_events SET event_json = replace(event_json, 'eventHash', 'tamperedHash') WHERE run_id = ?",
        (run.run_id,),
    )
    connection.commit()
    connection.close()

    recreated = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
        execution_value_store=SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3"),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
        provenance_store=SQLiteProvenanceStore(db_path=provenance_path),
    )

    with pytest.raises(ValueError, match="provenance"):
        asyncio.run(recreated.apply_review(ReviewDecision(
            runId=run.run_id,
            stepId="review",
            decision=ReviewDecisionType.APPROVED,
        )))

    assert paused.status is WorkflowStatus.WAITING_REVIEW
    assert store.get_run(run.run_id).status is WorkflowStatus.WAITING_REVIEW


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


def test_runtime_persists_completed_node_without_tool_calls_before_run_end() -> None:
    """没有工具调用时，节点完成事件也必须立即写回 WorkflowStore。"""
    runtime = _runtime()
    task = runtime.create_task("persist", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.task_id)
    state = ACGExecutionState(runId=run.run_id, completedStepIds=["extract"])

    runtime._project_acg_event(
        run,
        state,
        {"type": "node_completed", "stepId": "extract", "outputSummary": "done"},
    )

    persisted = runtime.workflow_store.get_run(run.run_id)
    assert persisted.get_step("extract").status is StepStatus.COMPLETED


def test_runtime_marks_parallel_failed_and_cancelled_steps_before_run_failure() -> None:
    """并行超步失败时，失败与取消节点必须在最终 run 失败前留下准确状态。"""
    runtime = _runtime()
    task = runtime.create_task("parallel", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.task_id)
    run.steps[1].step_id = "cancelled"
    run.steps[0].step_id = "failed"
    run.current_step_id = "failed"
    run.steps[0].status = StepStatus.RUNNING
    run.steps[1].status = StepStatus.RUNNING
    runtime.workflow_store.save_run(run)

    runtime._project_acg_event(
        run,
        ACGExecutionState(runId=run.run_id),
        {"type": "superstep_failed", "failedStepIds": ["failed"], "cancelledStepIds": ["cancelled"]},
    )

    persisted = runtime.workflow_store.get_run(run.run_id)
    assert persisted.get_step("failed").status is StepStatus.FAILED
    assert persisted.get_step("cancelled").status is StepStatus.CANCELLED


def test_runtime_projects_real_parallel_failure_and_sibling_cancellation() -> None:
    """真实并行 Agent 失败时，Runtime 必须保存失败和取消节点状态。"""
    class ParallelAgent(BaseAgent):
        async def run(self, context):
            if context.step.step_id == "fail":
                raise RuntimeError("planned failure")
            await asyncio.sleep(30)
            return AgentOutput(output={"answer": "late"})

    agents = AgentRegistry()
    agents.register(ParallelAgent(AgentProfile(agentId="parallel", agentName="parallel", domain="general")))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="parallel-run", name="parallel", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="placeholder", name="placeholder", agentName="parallel")],
    ))
    runtime = WorkflowRuntime(agent_registry=agents, workflow_registry=workflows, workflow_store=MemoryWorkflowStore())
    blueprint = ACGBlueprint(
        graphId="parallel-graph",
        nodes=[
            StepNode(nodeId="fail", agentName="parallel"),
            StepNode(nodeId="slow", agentName="parallel"),
        ],
    )
    task = runtime.create_task(
        "parallel", workflow_id="parallel-run",
        input={"acgBlueprint": blueprint.model_dump(by_alias=True, mode="json")},
    )
    _, run = runtime.prepare_run(task.task_id)

    with pytest.raises(RuntimeError, match="ACG superstep failed"):
        asyncio.run(runtime.execute_prepared_run(run.run_id))

    persisted = runtime.workflow_store.get_run(run.run_id)
    assert persisted.status is WorkflowStatus.FAILED
    assert persisted.get_step("fail").status is StepStatus.FAILED
    assert persisted.get_step("slow").status is StepStatus.CANCELLED


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


def test_runtime_projects_safe_communication_provenance_trace() -> None:
    """运行 Trace 应持久化通信血缘元数据，但不得复制节点输出正文。"""
    runtime = _runtime()
    task = runtime.create_task("provenance", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.task_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    events = [
        event for event in result.trace
        if event.event_type.value in {"data_produced", "data_consumed"}
    ]
    assert events
    assert any(event.payload.get("fieldNames") == ["title"] for event in events)
    assert any(event.payload.get("consumedFields") == ["title"] for event in events)
    assert "AgentOS" not in str([event.payload for event in events])
    assert "hidden" not in str([event.payload for event in events])


def test_runtime_projects_memory_policy_access_without_memory_body() -> None:
    """运行 Trace 要记录步骤记忆策略的执行事实，但不能复制任何记忆正文。"""
    runtime = _runtime()
    task = runtime.create_task("memory trace", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.task_id)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    events = [
        event for event in result.trace
        if event.observation == "Step memory policy applied"
    ]
    assert len(events) == 2
    assert all(event.payload["read"] is True for event in events)
    assert all(event.payload["written"] is True for event in events)
    assert "AgentOS" not in str([event.payload for event in events])


def test_runtime_does_not_duplicate_trace_for_replayed_node_commit() -> None:
    """崩溃恢复重放同一节点提交时，Trace 只能保留一次提交记录。"""
    runtime = _runtime()
    task = runtime.create_task("commit replay", workflow_id="acg-run")
    _, run = runtime.prepare_run(task.task_id)
    state = ACGExecutionState(runId=run.run_id)
    event = {
        "type": "node_completed",
        "stepId": "extract",
        "outputSummary": "safe summary",
        "commitId": "commit:run-1:extract:0",
        "memoryAccess": {"policyId": "default", "read": True, "readCount": 0, "write": True, "written": True, "limit": 10, "tokensUsed": 0},
        "provenanceEvents": [{"eventType": "data_produced", "payload": {"eventId": "prod_000001", "fieldNames": ["title"]}}],
    }

    runtime._project_acg_event(run, state, event)
    runtime._project_acg_event(run, state, event)

    assert len([item for item in run.trace if item.event_type.value == "step_succeeded"]) == 1
    assert len([item for item in run.trace if item.observation == "Step memory policy applied"]) == 1
    assert len([item for item in run.trace if item.event_type.value == "data_produced"]) == 1


def test_sync_acg_step_freezes_blueprint_memory_policy() -> None:
    """Blueprint 的记忆策略必须复制到本次运行步骤，避免执行期重新读取可变蓝图。"""
    runtime = _runtime()
    run = WorkflowRun(
        taskId="task-1",
        workflowId="acg-run",
        domain="general",
        runtimeEngine="acg",
    )
    blueprint = ACGBlueprint(
        graphId="memory-policy",
        nodes=[
            StepNode(
                nodeId="extract",
                name="extract",
                agentName="runner",
                metadata={
                    "memoryPolicy": {
                        "policyId": "extract-v1",
                        "read": False,
                        "write": True,
                        "allowedTypes": ["episodic"],
                        "limit": 3,
                        "tokenBudget": 120,
                        "requireAudit": True,
                    }
                },
            )
        ],
    )

    runtime._sync_run_steps_to_acg(run, blueprint)

    assert run.steps[0].input["memoryPolicy"] == {
        "policyId": "extract-v1",
        "read": False,
        "write": True,
        "allowedTypes": ["episodic"],
        "limit": 3,
        "tokenBudget": 120,
        "requireAudit": True,
    }


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
