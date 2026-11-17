import asyncio
from time import monotonic

import pytest

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.openai_runtime import OpenAICompatibleRuntime
from components.planner.complexity import call_planning_model
from contracts.capability import CapabilityKind, CapabilityManifest


class Transport:
    async def stream_json(self, **kwargs):
        assert "streamReasoning" not in kwargs["payload"]
        assert "stream_reasoning" not in kwargs["payload"]
        yield {"choices": [{"delta": {"reasoning_content": "先核对约束，"}}]}
        yield {"choices": [{"delta": {"reasoning_content": "再拆分任务。"}}]}
        yield {"choices": [{"delta": {"content": '{"ok":true}'}, "finish_reason": "stop"}]}


def runtime():
    adapter = OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="model.planner-reasoning", kind=CapabilityKind.MODEL,
        displayName="Reasoning fixture", provider="fixture", capabilities=["planner"],
    ), transport=Transport())
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    return RegisteredModelRuntime(registry=registry, provider="fixture", model="planner")


@pytest.mark.parametrize("enabled", [False, True])
def test_reasoning_is_an_opt_in_channel_and_does_not_enter_structured_output(enabled):
    async def collect():
        return [event async for event in runtime().stream_generate_json(
            prompt="Task", schema={"type": "object"}, run_id="reasoning-run",
            emit_reasoning_deltas=enabled,
        )]
    events = asyncio.run(collect())
    thought = [event.payload["delta"] for event in events if event.event_type == "model.reasoning.delta"]
    assert "".join(thought) == ("先核对约束，再拆分任务。" if enabled else "")
    assert events[-1].payload["data"] == {"ok": True}
    assert "先核对" not in str(events[-1].payload)
    first_output = next(i for i, event in enumerate(events) if event.event_type == "model.output.delta")
    if enabled:
        assert next(i for i, event in enumerate(events) if event.event_type == "model.reasoning.delta") < first_output


def test_planner_forwards_thought_chunks_with_call_identity_and_without_trace_persistence():
    progress = []
    audit = {}
    result = call_planning_model(runtime(), stage="outline", call_key="outline:1",
        prompt="Task", schema={"type": "object"}, audit=audit, model_timeout_seconds=5,
        planning_deadline=monotonic() + 5, run_id="reasoning-run", progress_callback=progress.append)
    chunks = [item for item in progress if item["eventType"] == "planner.model.reasoning.delta"]
    assert "".join(item["delta"] for item in chunks) == "先核对约束，再拆分任务。"
    assert all(item["callKey"] == "outline:1" and item["stage"] == "outline" and item["persistTrace"] is False for item in chunks)
    assert result["data"] == {"ok": True}
    assert "先核对" not in str(audit)
