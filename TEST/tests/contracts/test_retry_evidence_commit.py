"""Recovered reads remain original evidence inputs after the retry commits."""
from copy import deepcopy

import pytest

from components.executor.graph import ACGExecutionState
from components.executor.node_runner import ACGNodeRunner
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.execution_evidence import freeze_workspace_observations, workspace_observation_progress
from contracts.workflow import StepStatus
from adapters.agent.base import AgentOutput, AgentProfile, BaseAgent
from TEST.tests.contracts.test_execution_evidence import EvidenceRun


class StoredResultAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentProfile(agentName="reader", domain="general"))
        self.calls = 0

    async def run(self, context):
        self.calls += 1
        return AgentOutput(output={"answer": "Analysis based on authenticated prior reads"})


class HistoryTools:
    allowed_tools = ()

    def __init__(self, observations):
        self.observations = observations

    def list_tools(self):
        return []

    def bind_context(self, context, guard):
        self.context = context
        return self

    async def previous_attempt_observations(self, context):
        assert context is self.context
        return deepcopy(self.observations)


@pytest.mark.asyncio
async def test_node_commit_publishes_historical_receipt_refs_without_reporting_new_actions(tmp_path):
    agent = StoredResultAgent()
    runner = ACGNodeRunner.minimal(agent=agent)
    store = SQLiteExecutionValueStore(db_path=tmp_path / "retry.sqlite3")
    runner.value_store = store
    evidence = EvidenceRun(store, run_id=runner.run.run_id)
    record = evidence.record("one", "old-operation", 0, {"path": "source.py", "text": "saved source"})
    original = deepcopy(record)
    runner.run.input["workspaceBinding"] = {"workspaceId": "workspace", "grantId": "grant"}
    runner.run.execution_state.update(retryEvidenceContextVersion=1,
        readOnlyRetryProofs={"old-operation": {"stepId": "one"}})
    freeze_workspace_observations(runner.run, [{"kind": "file", "path": "source.py", "operation": "read"}])
    runner.steps["one"].output_spec = {"type": "object", "required": ["answer"],
        "properties": {"answer": {"type": "string"}}}
    runner.tool_runtime = HistoryTools([{"kind": "previous_attempt_tool_observation", "record": record,
        "operationKey": "old-read", "requestRef": record["requestRef"], "receiptRef": record["receiptRef"],
        "result": {"text": "saved source"}}])
    state = ACGExecutionState(runId=runner.run.run_id)
    result = await runner("one", state)
    assert result["toolCalls"] == []
    assert result["historicalToolEvidence"] == [original]
    assert "saved source" not in str(result)
    commit = store.get_node_commit(run_id=runner.run.run_id, commit_id=result["commitId"])
    assert commit["historicalToolEvidence"] == [original]
    runner.run.execution_state["outputRefs"] = {"one": result["outputRef"]}
    runner.run.completed_step_ids = ["one"]
    runner.run.steps = [runner.steps["one"]]
    runner.steps["one"].status = StepStatus.COMPLETED
    assert workspace_observation_progress(runner.run, store)[0]["complete"]
    assert (await runner("one", state))["historicalToolEvidence"] == [original]
    assert agent.calls == 1 and record == original


def test_historical_evidence_cannot_bypass_receipt_integrity_or_later_mutations(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "historical.sqlite3")
    evidence = EvidenceRun(store).require({"kind": "file", "path": "source.py", "operation": "read"})
    old = evidence.record("reader", "old-attempt", 0, {"path": "source.py"})
    output = store.put_output(run_id=evidence.run.run_id, step_id="reader", payload={"answer": "saved"})
    store.prepare_node_commit(run_id=evidence.run.run_id, commit_id="retry-commit")
    store.complete_node_commit(run_id=evidence.run.run_id, commit_id="retry-commit", payload={
        "outputRef": output, "auditOutcome": "allow", "toolCalls": [], "historicalToolEvidence": [old]})
    from contracts.workflow import WorkflowStep
    evidence.run.steps.append(WorkflowStep(stepId="reader", name="reader", agentName="offline", status="completed"))
    evidence.run.completed_step_ids = ["reader"]
    evidence.run.execution_state["outputRefs"] = {"reader": output}
    assert evidence.progress()[0]["complete"]
    evidence.commit({"tool": "fs.write", "path": "source.py", "output": {"created": False},
        "started": "2026-11-16T01:01:01+00:00", "ended": "2026-11-16T01:01:02+00:00"}, step_id="writer")
    assert not evidence.progress()[0]["complete"]
