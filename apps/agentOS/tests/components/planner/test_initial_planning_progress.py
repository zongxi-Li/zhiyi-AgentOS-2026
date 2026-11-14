"""The formal initial-plan entry must retain streaming and safe failure evidence."""
import asyncio
import json

import pytest

from adapters.model_adapter import StructuredGenerationError
from components.planner.task_decomposer import TaskDecompositionError
from contracts.mission_semantic import MissionSemanticRequest
from contracts.runtime_events import RuntimeEvent
from contracts.workflow import WorkflowDefinition, WorkflowDefinitionType
from test_initial_planning_sources import initial_run, ready_boundary, runtime_boundary
from test_planning_commit_runtime import dump_databases


class PlannerStream:
    provider = "fake"
    model = "initial-planner"

    def __init__(self, *, failure=None, on_first_call=None):
        self.failure = failure
        self.on_first_call = on_first_call
        self.calls = 0

    async def stream_generate_json(self, **kwargs):
        self.calls += 1
        if self.calls == 1 and self.on_first_call:
            self.on_first_call()
        run_id = kwargs["run_id"]
        yield RuntimeEvent(eventType="model.started", runId=run_id, sequence=1, payload={})
        if self.failure:
            raise StructuredGenerationError(self.failure, "PRIVATE MODEL RESPONSE")
        data = (
            {"primaryGoal": "Analyze supplied input", "requiredCapabilities": ["task_understanding"],
             "estimatedComplexity": "simple"}
            if self.calls == 1 else
            {"tasks": [{"key": "understand", "title": "Understand the request",
                        "objective": "Analyze supplied input and record its constraints",
                        "capabilityId": "task_understanding", "sourceRefs": [],
                        "acceptanceCriteria": ["Input constraints are recorded"],
                        "logicalRole": "task", "decompositionRationale": "Establish the requirements"}],
             "relations": [], "controlPolicies": []}
        )
        yield RuntimeEvent(eventType="model.output.delta", runId=run_id, sequence=2,
                           payload={"delta": json.dumps(data)})
        yield RuntimeEvent(eventType="model.completed", runId=run_id, sequence=3,
                           payload={"data": data})


def dynamic_run(initial_run, llm):
    runtime, store, agent, _, ledger = initial_run
    runtime.workflow_registry.register(WorkflowDefinition(
        workflowId="initial-observation", name="initial observation", domain="general",
        runtimeEngine="acg", definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP))
    mission = runtime.create_mission("Analyze input", workflow_id="initial-observation")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="initial-observation-source", expectedMissionRevision=0,
        objective="Analyze supplied input", constraints=[], sourceRefs=[]))
    runtime.set_intent_llm(llm)
    _, run = runtime.prepare_run(mission.mission_id, workflow_id="initial-observation")
    return runtime, store, agent, run, ledger


def planning_events(run):
    return [event.payload for event in run.trace
            if isinstance(event.payload, dict) and event.payload.get("planningProgress")]


def test_initial_runtime_streams_and_keeps_progress_without_materializing(initial_run, monkeypatch):
    llm = PlannerStream()
    runtime, store, agent, run, ledger = dynamic_run(initial_run, llm)
    live = []
    monkeypatch.setattr("runtime.live_events.runtime_event_broker.publish_from_thread",
                        lambda run_id, event: live.append(event))

    def concurrent_update():
        latest = store.get_run(run.run_id)
        latest.lifecycle_message = "preserve concurrent state"
        store.save_run(latest)

    llm.on_first_call = concurrent_update
    asyncio.run(runtime.execute_prepared_run(run.run_id))
    saved = store.get_run(run.run_id)
    events = planning_events(saved)
    assert llm.calls == 2
    assert events[0]["kind"] == "started"
    assert events[-1]["kind"] == "completed"
    assert any(event["kind"] == "profile_resolved" for event in events)
    assert any(event["kind"] == "plan_parsed" and event["taskCount"] == 1 for event in events)
    assert {event.payload["callKey"] for event in live
            if event.event_type == "planner.model.output.delta"} == {"intent_profile", "decompose"}
    assert all("delta" not in event for event in events)
    assert not any(event.event_type == "planner.graph.compiled" for event in live)
    assert saved.lifecycle_message == "preserve concurrent state"
    assert ledger.latest(run.mission_id) is not None
    assert not saved.steps and not saved.acg_blueprint and not agent.calls


@pytest.mark.parametrize("code", ["MODEL_OUTPUT_INVALID_JSON", "MODEL_TTFT_TIMEOUT"])
def test_initial_failure_retains_stage_and_model_code_without_private_text(initial_run, monkeypatch, code):
    runtime, store, agent, run, ledger = dynamic_run(initial_run, PlannerStream(failure=code))
    live = []
    monkeypatch.setattr("runtime.live_events.runtime_event_broker.publish_from_thread",
                        lambda run_id, event: live.append(event))
    with pytest.raises(ValueError, match="INVALID_PROPOSAL.*" + code):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    saved = store.get_run(run.run_id)
    failure = planning_events(saved)[-1]
    assert failure["kind"] == "failed"
    assert failure["stage"] == "intent_profile"
    assert failure["errorCode"] == code
    assert any(event.event_type == "planner.failed" for event in live)
    assert "PRIVATE MODEL RESPONSE" not in repr(saved.trace)
    assert not ledger.latest(run.mission_id) and not saved.steps and not agent.calls


def test_direct_initial_acceptance_remains_ledger_only_with_progress(initial_run):
    runtime, store, _, run, ledger = initial_run
    events = []
    before = dump_databases(store)
    receipt = runtime.planning_commit_authority.accept_initial(run.run_id, progress_callback=events.append)
    assert receipt.status == "ACCEPTED", receipt
    assert dump_databases(store) == before
    assert any(event.get("status") == "plan_parsed" for event in events)
    assert len(ledger.pending_events()) == 1


def test_initial_task_contract_failure_is_not_source_drift(initial_run, monkeypatch):
    runtime, store, _, run, ledger = initial_run
    engine = runtime._planning_engine_for_run(run)
    monkeypatch.setattr(runtime, "_planning_engine_for_run", lambda _: engine)

    def invalid(**kwargs):
        raise TaskDecompositionError("PRIVATE MODEL RESPONSE")

    monkeypatch.setattr(engine.semantic_planner, "plan_template", invalid)
    with pytest.raises(ValueError, match="INVALID_PROPOSAL.*TASK_PLAN_CONTRACT_FAILED"):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    saved = store.get_run(run.run_id)
    assert planning_events(saved)[-1]["errorCode"] == "TASK_PLAN_CONTRACT_FAILED"
    assert "PRIVATE MODEL RESPONSE" not in repr(saved.trace)
    assert not ledger.latest(run.mission_id)


def test_initial_stream_cancellation_remains_terminal(initial_run):
    llm = PlannerStream()
    runtime, store, agent, run, ledger = dynamic_run(initial_run, llm)
    llm.on_first_call = lambda: runtime.cancel(run.run_id)
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status.value == "cancelled"
    assert store.get_run(run.run_id).status == result.status
    assert not ledger.latest(run.mission_id) and not result.steps and not agent.calls
