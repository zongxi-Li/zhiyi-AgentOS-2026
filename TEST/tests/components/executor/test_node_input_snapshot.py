"""Failed node inputs remain inspectable without publishing node results."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from components.executor.graph import ACGExecutionState
from components.executor.node_runner import ACGNodeRunner
from components.executor.orphan_cleaner import ExecutionOrphanCleaner
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.execution import NodeExecutionPhase, NodeExecutionRecord
from contracts.workflow import WorkflowStep
from adapters.agent.base import AgentOutput, AgentProfile, BaseAgent


def execution_record(path, operation):
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT payload_json FROM acg_node_executions WHERE operation_id=?",
                                 (operation,)).fetchone()
    return NodeExecutionRecord.model_validate_json(row[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["input_contract", "agent", "output_contract"])
async def test_sqlite_failed_execution_keeps_prepared_input_and_memory_refs(tmp_path, failure):
    database = tmp_path / "values.sqlite3"
    values = SQLiteExecutionValueStore(db_path=database)
    invocations = []

    class FailingAgent(BaseAgent):
        async def run(self, context):
            invocations.append(context)
            node = execution_record(database, context.commit_id)
            assert node.phase is NodeExecutionPhase.PREPARED
            assert node.attempt_id == "scheduler-attempt"
            saved = values.get_node_input_context(run_id=context.run.run_id, operation_id=context.commit_id)
            assert saved == context.context_pack.model_dump(by_alias=True, mode="json")
            assert node.artifact_refs["memoryInput"].startswith("tool:")
            assert node.artifact_refs["executionGuidance"].startswith("tool:")
            if failure == "agent":
                raise RuntimeError("model transport failed after admission")
            return AgentOutput(output={"undeclared": "invalid output"})

    agent = FailingAgent(AgentProfile(agentName="reader", domain="general"))
    runner = ACGNodeRunner.minimal(agent=agent)
    runner.value_store = values
    runner.attempt_ids["one"] = "scheduler-attempt"
    runner.steps["one"].goal = "review saved evidence"
    runner.steps["one"].input = {"from": {"source": ["finding"]}}
    runner.steps["one"].output_spec = {"type": "object", "required": ["answer"],
                                        "properties": {"answer": {"type": "string"}}}
    if failure == "input_contract":
        runner.steps["one"].input["schema"] = {"type": "object", "required": ["missing"]}
    runner.steps["source"] = WorkflowStep(stepId="source", name="source", agentName="reader")
    runner.upstream_step_ids["one"] = ("source",)
    runner.memory.remember_step_output(run_id=runner.run.run_id, step_id="previous",
                                      output={"finding": "review saved evidence"})
    upstream_ref = values.put_output(run_id=runner.run.run_id, step_id="source",
        payload={"finding": "authorized bytes", "secret": "not delivered"})
    state = ACGExecutionState(runId=runner.run.run_id, outputRefs={"source": upstream_ref})
    operation = runner._commit_id(state.run_id, "one", 0)
    message = "model transport failed" if failure == "agent" else "contract|Contract"
    with pytest.raises(RuntimeError if failure == "agent" else ValueError, match=message):
        await runner("one", state)
    node = execution_record(database, operation)
    assert node.phase is NodeExecutionPhase.PREPARED
    assert "output" not in node.artifact_refs
    assert values.get_node_commit(run_id=state.run_id, commit_id=operation)["stage"] == "prepared"
    assert "one" not in state.output_refs and "one" not in state.context_refs
    assert len(invocations) == (0 if failure == "input_contract" else 1)
    values.close()

    reopened = SQLiteExecutionValueStore(db_path=database)
    try:
        assert reopened.list_node_executions(run_id=state.run_id) == (node,)
        orphan = reopened.put_context_pack(run_id=state.run_id, step_id="unused", payload={"data": "orphan"})
        stats = ExecutionOrphanCleaner(value_store=reopened).clean(run_id=state.run_id,
            protected_refs={upstream_ref}, older_than=datetime.now(timezone.utc) + timedelta(seconds=1))
        assert stats.deleted == 1
        assert orphan not in {ref.reference for ref in reopened.list_references(
            run_id=state.run_id, older_than=datetime.now(timezone.utc) + timedelta(seconds=1))}
        saved = reopened.get_node_input_context(run_id=state.run_id, operation_id=operation)
        assert saved["data"] == {"finding": "authorized bytes"}
        assert saved["sourceData"] == {"source": {"finding": "authorized bytes"}}
        assert "not delivered" not in json.dumps(saved)
        if failure != "input_contract":
            memory = reopened.get_tool_value(run_id=state.run_id, key=operation + ":memory-retrieval")
            assert memory["records"] == [record.model_dump(by_alias=True, mode="json") for record in invocations[0].memory]
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_required_only_output_fields_survive_node_publication():
    invocations = []
    class RequiredOnlyAgent(BaseAgent):
        async def run(self, context):
            invocations.append(context)
            return AgentOutput(output={"answer": "declared without properties", "private": "drop"})

    runner = ACGNodeRunner.minimal(agent=RequiredOnlyAgent(AgentProfile(agentName="reader", domain="general")))
    runner.steps["one"].output_spec = {"type": "object", "required": ["answer"]}
    state = ACGExecutionState(runId=runner.run.run_id)
    result = await runner("one", state)
    assert runner.value_store.get_output(run_id=state.run_id, output_ref=result["outputRef"]) == {
        "answer": "declared without properties"}
    assert result["nodeExecution"]["artifactRefs"]["context"] == result["contextRef"]
    replayed = await runner("one", state)
    assert len(invocations) == 1
    assert replayed["contextRef"] == result["contextRef"]
