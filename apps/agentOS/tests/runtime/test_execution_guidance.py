"""Operator guidance is explicit, isolated, frozen and refreshable at boundaries."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from components.executor.value_store import InMemoryExecutionValueStore, SQLiteExecutionValueStore
from contracts import stable_checksum
from contracts.execution_guidance import ExecutionGuidance, execution_guidance_key, guidance_projection
from contracts.workflow import RuntimeRunRecord, WorkflowStep
from runtime.execution_guidance import bind_execution_guidance, build_execution_guidance


def user_input(content="Use existing evidence and state uncertainty", *, source="run", operation="input:1"):
    return {"sourceRunId": source, "operationId": operation, "content": content,
            "submittedAt": "2026-11-19T09:32:05Z"}


def run_for(*, inputs=(), applied=True):
    return RuntimeRunRecord(runId="run", missionId="mission_0123456789ab", workflowId="flow",
        domain="general", runtimeEngine="acg", steps=[WorkflowStep(stepId="report", name="Report", agentName="agent")],
        executionState={"graphVersion": 6, "taskPlanVersion": 6, "planningLoop": {
            "userInputs": list(inputs), "current": {"status": "applied" if applied else "decided",
                "observationId": "observation:1", "decision": {"observationId": "observation:1",
                    "action": "continue", "reason": "Deliver the report from committed evidence",
                    "taskPlanPatch": {"private": "not projected"}}}}})


def workflow_store(run, inbox=()):
    data = {"run": run, "inbox": list(inbox)}
    return SimpleNamespace(get_run=lambda run_id: data["run"].model_copy(deep=True),
        list_planning_inputs=lambda run_id: deepcopy(data["inbox"])), data


def test_guidance_keeps_confirmed_input_order_and_only_public_applied_direction():
    inherited = user_input("Earlier scope", source="parent", operation="input:parent")
    first, latest = user_input(), user_input("Finalize now", operation="input:2")
    run = run_for(inputs=(inherited, first))
    before = run.model_copy(deep=True)
    result = build_execution_guidance(run, "report", pending_inputs=(first, latest))
    assert [i["operationId"] for i in result["userInputs"]] == ["input:parent", "input:1", "input:2"]
    assert result["plannerDecision"] == {"observationId": "observation:1", "action": "continue",
        "reason": "Deliver the report from committed evidence"}
    assert "private" not in str(result)
    assert ExecutionGuidance.model_validate(result).graph_version == 6
    assert run == before
    result["userInputs"][0]["content"] = "tamper local copy"
    assert run == before


def test_unapplied_planner_candidate_is_not_delivered_as_execution_direction():
    run = run_for(applied=False)
    assert build_execution_guidance(run, "report") is None


@pytest.mark.parametrize("damage", ["foreign_inbox", "conflicting_duplicate", "other_observation"])
def test_guidance_rejects_foreign_or_conflicting_control_facts(damage):
    run = run_for(inputs=(user_input(),))
    inbox = [user_input()]
    if damage == "foreign_inbox":
        inbox = [user_input(source="another-run")]
    elif damage == "conflicting_duplicate":
        inbox = [user_input("different content with same operation")]
    else:
        run.execution_state["planningLoop"]["current"]["decision"]["observationId"] = "other"
    with pytest.raises(ValueError, match="execution guidance"):
        build_execution_guidance(run, "report", pending_inputs=inbox)


def test_admission_snapshot_survives_restart_while_reader_sees_new_inbox(tmp_path):
    run = run_for(inputs=(user_input(),))
    workflow, data = workflow_store(run, (user_input(),))
    path = tmp_path / "values.sqlite3"
    values = SQLiteExecutionValueStore(db_path=path)
    frozen, reader = bind_execution_guidance(workflow_store=workflow, run=run, step_id="report",
        commit_id="commit", value_store=values)
    assert reader() == frozen
    values.close()
    data["inbox"].append(user_input("Finalize without further discovery", operation="input:2"))
    values = SQLiteExecutionValueStore(db_path=path)
    try:
        resumed, reader = bind_execution_guidance(workflow_store=workflow, run=run, step_id="report",
            commit_id="commit", value_store=values)
        assert resumed == frozen
        assert [i["operationId"] for i in reader()["userInputs"]] == ["input:1", "input:2"]
        snapshot = values.get_tool_value(run_id="run", key=execution_guidance_key("commit"))
        assert snapshot["guidanceHash"] == stable_checksum(frozen)
        resumed["userInputs"][0]["content"] = "local mutation"
        assert values.get_tool_value(run_id="run", key=execution_guidance_key("commit"))["guidance"] == frozen
    finally:
        values.close()


def test_legacy_admission_stays_empty_but_session_can_read_current_guidance():
    run = run_for(inputs=(user_input(),))
    workflow, _ = workflow_store(run, (user_input(),))
    values = InMemoryExecutionValueStore()
    frozen, reader = bind_execution_guidance(workflow_store=workflow, run=run, step_id="report",
        commit_id="legacy", value_store=values, legacy_execution=True)
    assert frozen is None
    assert reader()["userInputs"][0]["operationId"] == "input:1"
    assert values.get_tool_value(run_id="run", key=execution_guidance_key("legacy"))["guidance"] is None
    frozen, _ = bind_execution_guidance(workflow_store=workflow, run=run, step_id="report",
        commit_id="legacy", value_store=values)
    assert frozen is None


@pytest.mark.parametrize("damage", ["mission", "graph", "step"])
def test_bound_reader_cannot_follow_other_mission_graph_or_node(damage):
    run = run_for(inputs=(user_input(),))
    workflow, data = workflow_store(run)
    _, reader = bind_execution_guidance(workflow_store=workflow, run=run, step_id="report",
        commit_id="commit", value_store=InMemoryExecutionValueStore())
    if damage == "mission":
        data["run"].mission_id = "mission_abcdef012345"
    elif damage == "graph":
        data["run"].execution_state["graphVersion"] = 7
    else:
        data["run"].steps = []
    with pytest.raises(ValueError, match="no longer owns"):
        reader()


def test_guidance_projection_validates_the_bound_owner():
    run = run_for(inputs=(user_input(),))
    context = SimpleNamespace(run=run, step=SimpleNamespace(step_id="report"),
        execution_guidance=build_execution_guidance(run, "report"))
    assert guidance_projection(context) == context.execution_guidance
    context.step.step_id = "different"
    with pytest.raises(ValueError, match="another node"):
        guidance_projection(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_runner_binds_explicit_guidance_and_live_inbox_without_mutating_contract(legacy):
    from components.executor.graph import ACGExecutionState
    from components.executor.node_runner import ACGNodeRunner
    from service.agents.base import AgentOutput, AgentProfile, BaseAgent

    delivered, inbox = [], []

    class Agent(BaseAgent):
        async def run(self, context):
            delivered.append(context)
            assert (context.execution_guidance is None) is legacy
            if not legacy:
                assert context.execution_guidance["userInputs"][0]["content"] == "Deliver now"
            inbox.append({**user_input("Another current instruction", operation="input:2"),
                          "sourceRunId": context.run.run_id})
            assert context.execution_guidance_reader()["userInputs"][-1]["content"] == "Another current instruction"
            assert context.step.goal == "Compile evidence"
            return AgentOutput(output={"answer": "report"})

    runner = ACGNodeRunner.minimal(agent=Agent(AgentProfile(agentName="agent", domain="general")))
    runner.steps["one"].goal = "Compile evidence"
    runner.run.steps = [runner.steps["one"]]
    inbox.append({**user_input("Deliver now"), "sourceRunId": runner.run.run_id})
    runner.workflow_store = SimpleNamespace(get_run=lambda _: runner.run.model_copy(deep=True),
        list_planning_inputs=lambda _: deepcopy(inbox))
    state = ACGExecutionState(runId=runner.run.run_id)
    commit_id = runner._commit_id(state.run_id, "one", 0)
    if legacy:
        runner.value_store.prepare_node_commit(run_id=state.run_id, commit_id=commit_id)
    result = await runner("one", state)
    assert result["nodeExecution"]["artifactRefs"]["executionGuidance"].startswith("tool:")
    snapshot = runner.value_store.get_tool_value(run_id=state.run_id, key=execution_guidance_key(commit_id))
    assert snapshot["guidance"] == delivered[0].execution_guidance
    await runner("one", state)
    assert len(delivered) == 1
