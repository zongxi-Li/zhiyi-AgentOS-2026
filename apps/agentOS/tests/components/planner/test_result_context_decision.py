"""Missing model context is resolved by reading committed work, without new Steps."""
import asyncio
import json

import pytest

from components.planner.runtime_decision import decide_runtime
from components.planner.react_loop import BoundedReActPlanningLoop
from components.planner.unified_actions import PlannerActionGateway
from contracts.planning import TaskPlan
from contracts.runtime_planning import RuntimePlanningState
from runtime.planning_results import read_planning_result_page
from support.acg.native_capabilities import build_default_capability_catalog
from test_unified_actions import runtime_at, WaitPlanner


class Model:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.requests = []
        self.schemas = []

    def generate_json(self, prompt, schema, **kwargs):
        request = json.loads(prompt)
        self.requests.append(request)
        self.schemas.append(schema)
        turn = next(self.turns)
        return {"data": turn(request) if callable(turn) else turn}


@pytest.fixture
def committed(tmp_path):
    runtime, store = runtime_at(tmp_path)
    runtime.runtime_planning_coordinator.planner_for_run = lambda _: WaitPlanner()
    mission = runtime.create_mission("Reuse completed source inspection", workflow_id="seq")
    _, run = runtime.prepare_run(mission.mission_id)
    asyncio.run(runtime.execute_prepared_run(run.run_id))
    saved = store.get_run(run.run_id)
    observation = RuntimePlanningState.model_validate(saved.execution_state["planningLoop"]).current.observation
    plan = TaskPlan.model_validate(saved.execution_state["taskPlan"])
    return runtime, store, saved, observation, plan


def test_default_planner_reads_an_older_result_before_deciding_without_new_nodes(committed):
    runtime, store, run, observation, plan = committed
    source = observation.committed_results[0]
    field = next(item.name for item in source.fields if item.present)
    model = Model([
        {"observationId": observation.fingerprint(), "action": "read_result",
         "read": {"stepId": source.step_id, "fields": [field]}},
        {"observationId": observation.fingerprint(), "action": "wait",
         "reason": "Existing result supplies the requested information; no replacement acquisition needed"},
    ])
    before = len(runtime.execution_value_store.list_node_commits(run_id=run.run_id))
    decision = decide_runtime(observation=observation, task_plan=plan, llm=model,
        result_context_provider=lambda current, **kwargs: read_planning_result_page(runtime, current, **kwargs))
    feedback = model.requests[1]["resultReadFeedback"][0]["result"]
    expected = runtime.execution_value_store.get_output(run_id=run.run_id, output_ref=source.output_ref)
    assert feedback["data"][field] == expected[field]
    assert feedback["commitId"] == source.commit_id
    assert decision.task_plan_patch is None
    assert len(runtime.execution_value_store.list_node_commits(run_id=run.run_id)) == before
    assert store.get_run(run.run_id).execution_state["taskPlan"] == run.execution_state["taskPlan"]
    assert model.schemas[0]["type"] == "object" and "anyOf" not in model.schemas[0]


def test_result_lookup_error_returns_context_feedback_instead_of_execution_work(committed):
    runtime, _, _, observation, plan = committed
    source = observation.committed_results[0]
    model = Model([
        {"observationId": observation.fingerprint(), "action": "read_result",
         "read": {"stepId": source.step_id, "fields": ["undeclared-private-field"]}},
        {"observationId": observation.fingerprint(), "action": "wait", "reason": "Use known results"},
    ])
    decision = decide_runtime(observation=observation, task_plan=plan, llm=model,
        result_context_provider=lambda current, **kwargs: read_planning_result_page(runtime, current, **kwargs))
    assert decision.task_plan_patch is None
    feedback = model.requests[1]["validationCorrection"]
    assert feedback["error"]["code"] == "RESULT_READ_INVALID"
    assert "undeclared-private-field" not in json.dumps(feedback)


def test_react_gateway_reuses_the_same_history_reader_and_keeps_body_out_of_audit(committed):
    runtime, store, run, observation, plan = committed
    source = observation.committed_results[0]
    field = next(item.name for item in source.fields if item.present)
    events = []
    provider = lambda current, **kwargs: read_planning_result_page(runtime, current, **kwargs)
    gateway = PlannerActionGateway(workflow_store=store, capability_catalog=build_default_capability_catalog(),
        result_context_provider=provider, audit_sink=events.append)
    model = Model([
        {"turnKind": "use_tool", "actionRequest": {"requestRef": "historical-1",
            "query": {"target": "step_output", "result": {"stepId": source.step_id, "fields": [field]}}}},
        {"turnKind": "decide", "finalDecision": {"observationId": observation.fingerprint(),
            "action": "wait", "reason": "Reuse the available committed finding"}},
    ])
    decision = BoundedReActPlanningLoop(llm=model, gateway=gateway).decide(observation=observation, task_plan=plan)
    assert decision.reason == "Reuse the available committed finding"
    feedback = model.requests[1]["toolFeedback"][0]
    assert feedback["stepOutput"]["outputRef"] == source.output_ref
    assert field in feedback["stepOutput"]["data"]
    assert all("stepOutput" not in event and "data" not in event for event in events)
    assert not store.get_run(run.run_id).execution_state.get("graphPatchRefs")


def test_react_feedback_keeps_earlier_reads_after_more_than_twelve_actions(committed):
    _, store, _, observation, plan = committed
    gateway = PlannerActionGateway(workflow_store=store, capability_catalog=build_default_capability_catalog())
    session = gateway.open_session(observation.run_id)
    from contracts.planner_actions import PlannerToolFeedback
    feedback = [PlannerToolFeedback(requestRef=f"read-{index}", outcome="read", target="run_state")
        for index in range(20)]
    loop = BoundedReActPlanningLoop(llm=None, gateway=gateway)
    prompt = json.loads(loop._build_prompt(observation, plan, session, feedback))
    assert [item["requestRef"] for item in prompt["toolFeedback"]] == [f"read-{index}" for index in range(20)]
    assert loop.budget.max_context_chars is None


def test_default_planner_detects_unchanged_read_facts_without_a_call_count_limit(committed):
    from adapters.model_adapter import StructuredGenerationError
    runtime, _, _, observation, plan = committed
    source = observation.committed_results[0]
    read = {"observationId": observation.fingerprint(), "action": "read_result",
        "read": {"stepId": source.step_id}}
    model = Model([read, read, read])
    with pytest.raises(StructuredGenerationError) as caught:
        decide_runtime(observation=observation, task_plan=plan, llm=model,
            result_context_provider=lambda current, **kwargs: read_planning_result_page(runtime, current, **kwargs))
    assert caught.value.code == "PLANNER_DECISION_NO_PROGRESS"
    assert model.requests[-1]["validationCorrection"]["error"]["code"] == "RESULT_ALREADY_DELIVERED"


def test_default_planner_can_reopen_older_context_after_other_reads(committed):
    runtime, _, _, observation, plan = committed
    source = observation.committed_results[0]
    context = observation.context_catalog[0]
    read = {"observationId": observation.fingerprint(), "action": "read_result",
        "read": {"stepId": source.step_id}}
    model = Model([read,
        {"observationId": observation.fingerprint(), "action": "read_result",
            "read": {"contextRef": context.context_ref}}, read,
        {"observationId": observation.fingerprint(), "action": "wait", "reason": "Use the original evidence"}])
    decision = decide_runtime(observation=observation, task_plan=plan, llm=model,
        result_context_provider=lambda current, **kwargs: read_planning_result_page(runtime, current, **kwargs))
    history = model.requests[-1]["resultReadFeedback"]
    assert len(history) == 3 and history[0] == history[-1]
    assert decision.reason == "Use the original evidence"
    assert "validationCorrection" not in model.requests[-1]


def test_default_planner_repeated_invalid_lookup_reports_no_progress(committed):
    from adapters.model_adapter import StructuredGenerationError
    runtime, _, _, observation, plan = committed
    read = {"observationId": observation.fingerprint(), "action": "read_result",
        "read": {"stepId": "not-an-indexed-step"}}
    with pytest.raises(StructuredGenerationError) as caught:
        decide_runtime(observation=observation, task_plan=plan, llm=Model([read, read]),
            result_context_provider=lambda current, **kwargs: read_planning_result_page(runtime, current, **kwargs))
    assert caught.value.code == "PLANNER_DECISION_NO_PROGRESS"


@pytest.mark.parametrize('when', ['cached_replay', 'during_read'])
def test_result_read_rechecks_current_observation_before_replaying_or_publishing(committed, when):
    runtime, store, run, observation, _ = committed
    source = observation.committed_results[0]
    def change_boundary():
        current = store.get_run(run.run_id)
        current.execution_state['planningLoop']['current']['observationId'] = 'different-boundary'
        store.save_run(current)
    def provider(current, **kwargs):
        result = read_planning_result_page(runtime, current, **kwargs)
        if when == 'during_read':
            change_boundary()
        return result
    gateway = PlannerActionGateway(workflow_store=store, capability_catalog=build_default_capability_catalog(),
        result_context_provider=provider)
    session = gateway.open_session(run.run_id)
    request = {'requestRef': 'historical-read', 'query': {'target': 'step_output', 'result': {'stepId': source.step_id}}}
    first = gateway.submit(session.session_id, request)
    if when == 'cached_replay':
        assert first.step_output
        change_boundary()
        result = gateway.submit(session.session_id, request)
    else:
        result = first
    assert result.code == 'STALE_OBSERVATION'
    assert not getattr(result, 'step_output', None)
