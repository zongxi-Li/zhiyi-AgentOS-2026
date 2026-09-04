"""Phase 1-2 streaming path tests using a deterministic fake provider."""

from __future__ import annotations

import asyncio

from adapters.model.native import NativeGeneralAgent
from components.communicator.contracts import ContextPack
from contracts.runtime_events import RuntimeEvent
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
from runtime.live_events import RuntimeEventBroker
from service.agents import AgentRunContext
from support.acg.models import build_default_capability_catalog


class _FakeStreamingProvider:
    delegate = None

    def __init__(self, broker: RuntimeEventBroker) -> None:
        self.broker = broker
        self.delegate = self

    def is_available(self) -> bool:
        return True

    async def stream_generate_json(self, **kwargs):
        run_id = kwargs["run_id"]
        node_id = kwargs["node_id"]
        for index, (event_type, payload) in enumerate([
            ("node.started", {}),
            ("model.started", {"provider": "fake", "model": "fake-1"}),
            ("model.first_token", {}),
            ("model.output.delta", {"delta": '{"task_summary":"ok"}'}),
            ("model.completed", {"data": {"task_summary": "ok", "constraints": [], "success_criteria": [], "assumptions": [], "open_questions": []}}),
            ("node.completed", {}),
        ]):
            yield RuntimeEvent(eventType=event_type, runId=run_id, nodeId=node_id, attemptId="attempt-1", sequence=index + 1, payload=payload)


def test_fake_provider_native_agent_broker_timeline_and_sse_shape(monkeypatch) -> None:
    async def scenario() -> list[RuntimeEvent]:
        broker = RuntimeEventBroker()
        import adapters.model.native as native_module
        monkeypatch.setattr(native_module, "runtime_event_broker", broker)
        agent = NativeGeneralAgent()
        model = _FakeStreamingProvider(broker)
        task = RuntimeMissionRecord(missionId="m1", title="understand")
        run = RuntimeRunRecord(missionId=task.mission_id, workflowId="wf", domain="general", runtimeEngine="acg")
        step = WorkflowStep(stepId="step-1", name="understand", agentName=agent.profile.agent_name, capability="task_understanding")
        context = AgentRunContext(task=task, run=run, workflow=WorkflowDefinition(workflowId="wf", name="wf", domain="general", runtimeEngine="acg"), step=step, memory=[], contextPack=ContextPack(runId=run.run_id, stepId=step.step_id), modelRuntime=model, capabilityDescriptor=build_default_capability_catalog().get("task_understanding"), commitId="attempt-1")
        queue = asyncio.Queue()
        broker._queues[run.run_id].add(queue)
        result = await agent.run(context)
        assert result.output["task_summary"] == "ok"
        events = [queue.get_nowait() for _ in range(queue.qsize())]
        assert [event.event_type for event in events] == ["node.started", "model.started", "model.first_token", "model.output.delta", "model.completed", "node.completed"]
        assert events[3].payload["delta"]
        assert "data" not in events[4].payload
        return events

    events = asyncio.run(scenario())
    # SSE uses the same alias-based JSON envelope as the broker contract.
    payload = events[3].model_dump(by_alias=True, mode="json")
    assert payload["eventType"] == "model.output.delta"
    assert payload["runId"] == events[3].run_id


def test_sse_disconnect_removes_subscriber_without_affecting_publishers() -> None:
    async def scenario() -> None:
        broker = RuntimeEventBroker()
        stream = broker.subscribe("disconnect-run")
        task = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await broker.publish("disconnect-run", RuntimeEvent(eventType="node.started", runId="disconnect-run", nodeId="n", sequence=0))
        assert "disconnect-run" not in broker._queues

    asyncio.run(scenario())
