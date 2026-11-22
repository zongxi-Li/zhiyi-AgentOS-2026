"""ACG 五个持久化边界发生进程中断后的恢复演练。"""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from adapters.agent.resource_execution import ResourceExecutionError
from components.auditor import SQLiteDecisionStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor.graph import ACGSuperstepError
from components.executor.memory_input import memory_retrieval_key, memory_retrieval_reference
from components.executor.value_store import ExecutionValueAccessError, SQLiteExecutionValueStore
from components.memory import MemoryService
from components.memory.store import SQLiteMemoryStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.mission.store import WorkflowRegistry
from contracts.execution import NodeExecutionPhase, NodeExecutionRecord
from contracts.memory import MemoryQuery
from contracts.workflow import StepStatus, TraceEventType, WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from runtime.workflow_runtime import ExecutionRuntime
from adapters.agent import AgentRegistry
from adapters.agent.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore


class InjectedFault(BaseException):
    """仅测试使用的进程中断模拟；不属于生产运行时错误合同。"""


class _FaultAgent(BaseAgent):
    """记录调用并追加真实文件副作用，验证恢复不会重复执行 Agent。"""

    def __init__(self, effect_path: Path) -> None:
        super().__init__(AgentProfile(agentName="fault-agent", domain="general"))
        self.commit_ids: list[str | None] = []
        self.effect_path = effect_path

    async def run(self, context):
        self.commit_ids.append(context.commit_id)
        with self.effect_path.open("a", encoding="utf-8") as effects:
            effects.write(f"{context.commit_id}\n")
        return AgentOutput(output={"answer": "components.safe"}, summary="components.safe")


def _runtime(tmp_path, *, store, agents) -> ExecutionRuntime:
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="fault-run",
        name="fault run",
        domain="general",
        runtimeEngine="acg",
        steps=[WorkflowStepDefinition(
            stepId="one",
            name="one",
            agentName="fault-agent",
            outputSpec={"type": "object", "properties": {"answer": {"type": "string"}}},
        )],
    ))
    return ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
        execution_value_store=SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3"),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
        provenance_store=SQLiteProvenanceStore(db_path=tmp_path / "provenance.sqlite3"),
        decision_store=SQLiteDecisionStore(db_path=tmp_path / "decisions.sqlite3"),
    )


def _durable_evidence(tmp_path: Path, run_id: str) -> dict[str, list[tuple]]:
    """独立只读连接检查已有证据，不把未提交正文当作合法输出读取。"""
    queries = (
        ("commits", "values.sqlite3", "SELECT commit_id, payload_json, stage FROM acg_node_commits WHERE run_id = ? ORDER BY commit_id"),
        ("executions", "values.sqlite3", "SELECT operation_id, payload_json, phase FROM acg_node_executions WHERE run_id = ? ORDER BY operation_id"),
        ("values", "values.sqlite3", "SELECT reference, kind, payload_json, operation_id FROM execution_values WHERE run_id = ? ORDER BY reference"),
        ("provenance", "provenance.sqlite3", "SELECT event_id, event_json FROM acg_provenance_events WHERE run_id = ? ORDER BY event_id"),
        ("decisions", "decisions.sqlite3", "SELECT decision_id, decision_json, decision_hash FROM acg_audit_decisions WHERE run_id = ? ORDER BY decision_id"),
    )
    evidence = {}
    for name, filename, query in queries:
        with closing(sqlite3.connect((tmp_path / filename).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            evidence[name] = connection.execute(query, (run_id,)).fetchall()
    return evidence


@pytest.mark.parametrize(
    "stage",
    ["after_values", "after_provenance", "after_memory", "after_trace", "after_checkpoint"],
)
def test_restart_respects_commit_boundary_without_repeating_agent_effects(stage: str, tmp_path) -> None:
    """已提交节点可恢复；未提交且副作用未知的节点须保留证据并明确拒绝重放。"""
    store = MemoryWorkflowStore()
    agents = AgentRegistry()
    agent = _FaultAgent(tmp_path / "agent-effects.txt")
    agents.register(agent)
    first = _runtime(tmp_path, store=store, agents=agents)
    task = first.create_mission("fault recovery", workflow_id="fault-run")
    _, run = first.prepare_run(task.mission_id)

    def interrupt(actual: str) -> None:
        if actual == stage:
            raise InjectedFault(stage)

    first._fault_hook = interrupt
    with pytest.raises(InjectedFault, match=stage):
        asyncio.run(first.execute_prepared_run(run.run_id))

    commit_id = f"commit:{run.run_id}:one:0"
    assert agent.commit_ids == [commit_id]
    assert agent.effect_path.read_text(encoding="utf-8").splitlines() == [commit_id]
    evidence = _durable_evidence(tmp_path, run.run_id)
    recovered = _runtime(tmp_path, store=store, agents=agents)
    if stage in {"after_values", "after_provenance", "after_memory"}:
        assert recovered.execution_value_store.list_node_commits(run_id=run.run_id) == (
            {"commitId": commit_id, "stage": "prepared"},
        )
        assert len(evidence["executions"]) == 1
        execution = NodeExecutionRecord.model_validate_json(evidence["executions"][0][1])
        assert execution.phase is NodeExecutionPhase.AUDITED
        assert execution.audit_ref
        assert execution.failure_code is None
        assert len(evidence["decisions"]) == 1
        memory_ref = memory_retrieval_reference(run.run_id, commit_id)
        snapshots = [row for row in evidence["values"] if row[0] == memory_ref]
        assert len(snapshots) == 1
        _, kind, payload_json, operation_id = snapshots[0]
        assert kind == "output"
        assert operation_id is None
        snapshot = json.loads(payload_json)
        assert snapshot["identity"] == {
            "runId": run.run_id, "stepId": "one",
            "attemptId": execution.attempt_id, "commitId": commit_id,
        }
        recovered.execution_value_store.assert_reference(
            kind="output", run_id=run.run_id, step_id="one", reference=memory_ref,
        )
        assert recovered.execution_value_store.get_tool_value(
            run_id=run.run_id, key=memory_retrieval_key(commit_id),
        ) == snapshot
        node_values = [row for row in evidence["values"] if row[0] != memory_ref]
        assert len(node_values) == 2
        assert {row[1] for row in node_values} == {"output", "context"}
        assert {row[3] for row in node_values} == {commit_id}
        ledger = recovered.provenance_store.load_ledger(run_id=run.run_id, mission_id=task.mission_id)
        assert len(ledger.productions) == (0 if stage == "after_values" else 1)

        with pytest.raises(ACGSuperstepError) as failure:
            asyncio.run(recovered.execute_prepared_run(run.run_id))

        assert failure.value.outcome_unknown
        assert isinstance(failure.value.cause, ResourceExecutionError)
        assert failure.value.cause.outcome_unknown
        assert str(failure.value.cause) == "unfinished Agent operation requires explicit reconciliation"
        failed = store.get_run(run.run_id)
        assert failed.status is WorkflowStatus.FAILED
        assert failed.steps[0].status is StepStatus.FAILED
        assert failed.execution_state["recoveryOutcome"]["action"] == "review"
        assert failed.execution_state["recoveryOutcome"]["status"] == "required"
        assert failed.execution_state["recoveryOutcome"]["reasonCode"] == "REMOTE_EXECUTION_OUTCOME_UNKNOWN"
        assert not any(event.event_type is TraceEventType.STEP_SUCCEEDED for event in failed.trace)
        assert _durable_evidence(tmp_path, run.run_id) == evidence
        for reference, kind, _, _ in node_values:
            with pytest.raises(ExecutionValueAccessError, match="not committed"):
                if kind == "output":
                    recovered.execution_value_store.get_output(run_id=run.run_id, output_ref=reference)
                else:
                    recovered.execution_value_store.get_context_pack(run_id=run.run_id, context_ref=reference)
        assert agent.commit_ids == [commit_id]
        assert agent.effect_path.read_text(encoding="utf-8").splitlines() == [commit_id]
        return

    result = asyncio.run(recovered.execute_prepared_run(run.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.steps[0].status is StepStatus.COMPLETED
    assert agent.commit_ids == [commit_id]
    assert agent.effect_path.read_text(encoding="utf-8").splitlines() == [commit_id]
    assert sum(event.event_type is TraceEventType.STEP_SUCCEEDED for event in result.trace) == 1
    assert recovered.checkpoint_store.latest_version(run_id=run.run_id) == 1
    assert len(recovered.provenance_store.load_ledger(run_id=run.run_id, mission_id=task.mission_id).productions) == 1
    records = MemoryService(store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3")).search(
        MemoryQuery(query="components.safe", scope=run.run_id)
    )
    assert {record.memory_id for record in records} == {
        f"memory:{run.run_id}:one",
        f"capsule:{run.run_id}:execution",
    }
    assert len(records) == 2
    assert '"answer"' not in json.dumps(result.execution_state, ensure_ascii=False)
