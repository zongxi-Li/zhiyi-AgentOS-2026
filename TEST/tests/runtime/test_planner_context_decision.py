"""Default Planner reads failed-node context without creating execution work."""
import asyncio
from copy import deepcopy
import json

import pytest

from components.executor.graph import ACGSuperstepError
from contracts.memory import MemoryRecord
from contracts.planning import TaskPlan
from contracts.runtime_planning import RuntimePlanningDecision
from components.planner.runtime_decision import decide_runtime
from runtime.orchestration.planning_results import read_planning_result_page
from runtime.orchestration.state_persistence import acg_execution_state_from_run
from TEST.tests.runtime.test_planning_loop import Agent, Planner, attach, prepared


class ContextReadingModel:
    def __init__(self, observation, entry, fields):
        self.observation = observation
        self.entry = entry
        self.fields = fields
        self.requests = []
        self.schemas = []

    def generate_json(self, prompt, schema, **kwargs):
        request = json.loads(prompt)
        self.requests.append(request)
        self.schemas.append(schema)
        if len(self.requests) == 1:
            directory = request["observation"]["contextCatalog"]
            assert directory["catalog"] == "contexts" and directory["count"] >= 1
            assert any(item["contextKind"] == self.entry.context_kind for item in directory["groups"])
            return {"data": {"observationId": self.observation.fingerprint(), "action": "read_result",
                "read": {"catalog": "contexts", "contextKind": self.entry.context_kind,
                    "stepId": self.entry.step_id}}}
        previous = request["resultReadFeedback"][-1]["result"]
        if previous.get("catalog"):
            matched = next((entry for entry in previous["data"].get("entries", ())
                if entry["contextRef"] == self.entry.context_ref), None)
            if matched is None:
                assert previous["nextCursor"] is not None
                return {"data": {"observationId": self.observation.fingerprint(), "action": "read_result",
                    "read": {"catalog": "contexts", "contextKind": self.entry.context_kind,
                        "stepId": self.entry.step_id, "cursor": previous["nextCursor"]}}}
            return {"data": {"observationId": self.observation.fingerprint(), "action": "read_result",
                "read": {"contextRef": matched["contextRef"], "fields": self.fields}}}
        following = request["resultReadFeedback"][-1]["result"]["nextCursor"]
        if following is not None:
            return {"data": {"observationId": self.observation.fingerprint(), "action": "read_result",
                "read": {"contextRef": self.entry.context_ref, "fields": self.fields, "cursor": following}}}
        return {"data": {"observationId": self.observation.fingerprint(), "action": "wait",
            "reason": "The saved context explains the failed attempt; preserve it for recovery."}}


@pytest.fixture
def failed_context(tmp_path):
    runtime, agent, prepared_run = prepared(tmp_path, Agent(fail=True))
    runtime.memory_store.put(MemoryRecord(memoryId="prior-B-evidence", memoryType="episodic",
        scope=prepared_run.run_id, content={"finding": "B do B saved evidence", "unresolved": ["B remains incomplete"]}))
    attach(runtime, Planner(lambda observation, _: RuntimePlanningDecision(
        observationId=observation.fingerprint(), action="abort", reason="Preserve the failed attempt")))
    with pytest.raises(ACGSuperstepError):
        asyncio.run(runtime.execute_prepared_run(prepared_run.run_id))
    run = runtime.workflow_store.get_run(prepared_run.run_id)
    failed = next(node for node in runtime.execution_value_store.list_node_executions(run_id=run.run_id)
                  if node.step_id == "B")
    identity = {"runId": run.run_id, "stepId": "B", "attemptId": failed.attempt_id, "commitId": failed.operation_id}
    tool_request = {"identity": identity, "request": {"protocolVersion": "1", "requestId": "read-B",
        "invocationId": "read-B", "resourceId": "hands", "capabilityId": "fs.read",
        "idempotencyKey": "read-B", "input": {"path": "source.py"},
        "authorization": {"workspaceId": "workspace", "grantId": "grant"}}}
    original_tool_ref = runtime.execution_value_store.put_tool_value(run_id=run.run_id, step_id="B",
        key="failed-node-tool-request", payload=tool_request)
    observation = runtime.runtime_planning_coordinator.observe(run, acg_execution_state_from_run(run), "failure")
    return runtime, agent, run, failed, observation, original_tool_ref, tool_request


@pytest.mark.parametrize("context_kind,fields,expected_status,expected_trust", [
    ("attempt_input", ["runId", "stepId", "stepGoal"], "prepared", "assembled_context"),
    ("memory_retrieval", ["identity", "records"], "prepared", "memory_snapshot"),
    ("tool_request", ["identity", "request"], "admitted", "host_recorded"),
])
@pytest.mark.parametrize("include_committed_results", [False, True])
def test_default_planner_reads_failed_node_context_and_preserves_execution_state(
    failed_context, context_kind, fields, expected_status, expected_trust, include_committed_results,
):
    runtime, agent, run, failed, observation, original_tool_ref, tool_request = failed_context
    if not include_committed_results:
        observation = observation.model_copy(update={"committed_results": ()})
    entry = next(item for item in observation.context_catalog
                 if item.context_kind == context_kind and item.step_id == "B")
    assert entry.status == expected_status and entry.trust == expected_trust
    assert entry.attempt_id == failed.attempt_id and entry.operation_id == failed.operation_id
    assert all(item.step_id != "B" for item in observation.committed_results)
    plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
    model = ContextReadingModel(observation, entry, fields)
    commits = deepcopy(runtime.execution_value_store.list_node_commits(run_id=run.run_id))
    executions = [item.model_dump(by_alias=True, mode="json")
                  for item in runtime.execution_value_store.list_node_executions(run_id=run.run_id)]
    original_run = run.model_dump(by_alias=True, mode="json")
    original_catalog = observation.context_catalog
    calls = list(agent.calls)
    decision = decide_runtime(observation=observation, task_plan=plan, llm=model,
        result_context_provider=lambda current, **arguments: read_planning_result_page(runtime, current, **arguments))

    feedbacks = [feedback for feedback in model.requests[-1]["resultReadFeedback"]
        if feedback["result"].get("contextRef")]
    result = feedbacks[0]["result"]
    data = {field: value for feedback in feedbacks for field, value in feedback["result"]["data"].items()}
    assert result["contextRef"] == entry.context_ref and result["contextKind"] == context_kind
    assert result["sourceRunId"] == run.run_id and result["stepId"] == "B"
    assert result["status"] == expected_status and result["trust"] == expected_trust
    assert result["checksum"] == entry.checksum and result["observationId"] == observation.fingerprint()
    assert result["graphVersion"] == observation.graph_version
    if context_kind == "attempt_input":
        assert data == {"runId": run.run_id, "stepId": "B", "stepGoal": "B"}
    else:
        assert data["identity"] == tool_request["identity"]
        if context_kind == "memory_retrieval":
            assert any(record["memoryId"] == "prior-B-evidence" for record in data["records"])
        else:
            assert data["request"]["input"] == {"path": "source.py"}
            assert result["status"] != "completed"
    assert feedbacks[-1]["result"]["nextCursor"] is None
    assert all(item["result"]["status"] == expected_status and item["result"]["trust"] == expected_trust
               for item in feedbacks)
    assert decision.action == "wait" and decision.task_plan_patch is None
    assert decision.observation_id == observation.fingerprint()
    assert runtime.workflow_store.get_run(run.run_id).model_dump(by_alias=True, mode="json") == original_run
    assert runtime.execution_value_store.list_node_commits(run_id=run.run_id) == commits
    assert [item.model_dump(by_alias=True, mode="json")
        for item in runtime.execution_value_store.list_node_executions(run_id=run.run_id)] == executions
    assert runtime.execution_value_store.get_output(run_id=run.run_id, output_ref=original_tool_ref) == tool_request
    assert observation.context_catalog == original_catalog and agent.calls == calls
    assert model.schemas[0]["type"] == "object" and "anyOf" not in model.schemas[0]
