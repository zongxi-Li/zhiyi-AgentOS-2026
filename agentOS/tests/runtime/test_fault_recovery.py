"""ACG 五个持久化边界发生进程中断后的恢复演练。"""

from __future__ import annotations

import asyncio
import json

import pytest

from components.auditor import SQLiteDecisionStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor.value_store import SQLiteExecutionValueStore
from components.memory import MemoryService
from components.memory.store import SQLiteMemoryStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.task_manager.store import WorkflowRegistry
from contracts.memory import MemoryQuery
from contracts.workflow import TraceEventType, WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from runtime.workflow_runtime import WorkflowRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore


class InjectedFault(BaseException):
    """仅测试使用的进程中断模拟；不属于生产运行时错误合同。"""


class _FaultAgent(BaseAgent):
    """记录提交标识，验证中断重试不会生成新的外部副作用键。"""

    def __init__(self) -> None:
        super().__init__(AgentProfile(agentName="fault-agent", domain="general"))
        self.commit_ids: list[str | None] = []

    async def run(self, context):
        self.commit_ids.append(context.commit_id)
        return AgentOutput(output={"answer": "safe"}, summary="safe")


def _runtime(tmp_path, *, store, agents) -> WorkflowRuntime:
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
    return WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=store,
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3"),
        execution_value_store=SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3"),
        memory_store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3"),
        provenance_store=SQLiteProvenanceStore(db_path=tmp_path / "provenance.sqlite3"),
        decision_store=SQLiteDecisionStore(db_path=tmp_path / "decisions.sqlite3"),
    )


@pytest.mark.parametrize(
    "stage",
    ["after_values", "after_provenance", "after_memory", "after_trace", "after_checkpoint"],
)
def test_restart_reuses_commit_and_does_not_duplicate_persistence(stage: str, tmp_path) -> None:
    """任何写入边界中断后，重建运行时必须恢复为一份提交、Trace、记忆和检查点。"""
    store = MemoryWorkflowStore()
    agents = AgentRegistry()
    agent = _FaultAgent()
    agents.register(agent)
    first = _runtime(tmp_path, store=store, agents=agents)
    task = first.create_task("fault recovery", workflow_id="fault-run")
    _, run = first.prepare_run(task.task_id)

    def interrupt(actual: str) -> None:
        if actual == stage:
            raise InjectedFault(stage)

    first._fault_hook = interrupt
    with pytest.raises(InjectedFault, match=stage):
        asyncio.run(first.execute_prepared_run(run.run_id))

    recovered = _runtime(tmp_path, store=store, agents=agents)
    result = asyncio.run(recovered.execute_prepared_run(run.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    assert set(agent.commit_ids) == {"commit:" + run.run_id + ":one:0"}
    assert sum(event.event_type is TraceEventType.STEP_SUCCEEDED for event in result.trace) == 1
    assert recovered.checkpoint_store.latest_version(run_id=run.run_id) == 1
    assert len(recovered.provenance_store.load_ledger(run_id=run.run_id, task_id=task.task_id).productions) == 1
    records = MemoryService(store=SQLiteMemoryStore(db_path=tmp_path / "memory.sqlite3")).search(
        MemoryQuery(query="safe", scope=run.run_id)
    )
    assert {record.memory_id for record in records} == {
        f"memory:{run.run_id}:one",
        f"capsule:{run.run_id}:execution",
    }
    assert len(records) == 2
    assert '"answer"' not in json.dumps(result.execution_state, ensure_ascii=False)
