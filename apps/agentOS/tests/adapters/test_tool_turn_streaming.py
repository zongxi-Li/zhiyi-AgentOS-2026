"""Real tool-enabled model adapters stream public output before final validation."""
import asyncio
import json

import pytest

from adapters.guarded_model import GuardedModelRuntime
from adapters.model_adapter import StructuredGenerationError
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.openai_runtime import OpenAICompatibleRuntime
from contracts.capability import CapabilityKind, CapabilityManifest, ModelInvocationRequest


TOOLS = [{"type": "function", "function": {"name": "fs__list", "parameters": {"type": "object"}}}]


def model(transport):
    adapter = OpenAICompatibleRuntime(manifest=CapabilityManifest(capabilityId="stream-tools",
        kind=CapabilityKind.MODEL, displayName="Test", provider="test", capabilities=["mock"],
        metadata={"modelCapabilities": {"mock": {"features": {"tools": True, "streaming": True}}}}), transport=transport)
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    return GuardedModelRuntime(delegate=RegisteredModelRuntime(registry=registry, provider="test", model="mock")), adapter


@pytest.mark.asyncio
async def test_tool_enabled_turn_publishes_content_before_the_provider_completes():
    release = asyncio.Event()
    observed = asyncio.Event()
    events = []

    class Transport:
        async def post_json(self, **_):
            raise AssertionError("streaming must not use the complete-response API")

        async def stream_json(self, **kwargs):
            assert kwargs["payload"]["stream"] is True
            yield {"choices": [{"delta": {"reasoning_content": "PRIVATE"}}]}
            yield {"choices": [{"delta": {"content": '{"answer":"first'}}]}
            await release.wait()
            yield {"choices": [{"delta": {"content": ' second"}'}, "finish_reason": "stop"}]}
            yield {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 3}}

    runtime, _ = model(Transport())

    async def progress(kind, payload):
        events.append((kind, payload))
        if kind == "model.output.delta":
            observed.set()

    task = asyncio.create_task(runtime.generate_tool_turn(messages=[], tools=TOOLS, schema={"type": "object"},
        progress_callback=progress, commit_id="turn", timeout_seconds=5))
    try:
        await asyncio.wait_for(observed.wait(), 2)
        assert not task.done()
        assert not any(kind == "model.completed" for kind, _ in events)
        release.set()
        result = await task
        assert result.content == {"answer": "first second"}
        assert result.metadata["streaming"] is True
        assert result.usage["completion_tokens"] == 3
        assert "PRIVATE" not in json.dumps(events)
        assert "data" not in events[-1][1]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interleaved_tool_fragments_keep_private_context_internal_and_finish_once():
    class Transport:
        async def stream_json(self, **_):
            yield {"choices": [{"delta": {"reasoning_content": "PRIVATE"}}]}
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call-a", "type": "function", "function": {"name": "fs__", "arguments": '{"path":'}},
                {"index": 1, "id": "call-b", "type": "function", "function": {"name": "fs__read", "arguments": '{"path":"n"}'}},
            ]}}]}
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call-a", "function": {"name": "list", "arguments": '"."}'}},
            ]}, "finish_reason": "tool_calls"}]}

    _, adapter = model(Transport())
    request = ModelInvocationRequest(requestId="turn", model="mock", options={"tools": TOOLS})
    events = [event async for event in adapter.astream(request)]
    response = events[-1].response
    assert [(call["id"], call["function"]["name"]) for call in response.tool_calls] == [("call-a", "fs__list"), ("call-b", "fs__read")]
    assert json.loads(response.tool_calls[0]["function"]["arguments"]) == {"path": "."}
    assert response.assistant_message["reasoning_content"] == "PRIVATE"
    assert "PRIVATE" not in json.dumps([event.model_dump() for event in events])
    assert "response" not in events[-1].model_dump()


@pytest.mark.asyncio
async def test_cancelling_a_tool_stream_closes_the_provider_without_completing_the_turn():
    started, closed = asyncio.Event(), asyncio.Event()

    class Transport:
        async def stream_json(self, **_):
            try:
                yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call", "function": {"name": "fs__list", "arguments": '{"path":'}}]}}]}
                started.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

    runtime, _ = model(Transport())
    events = []
    async def progress(kind, payload):
        events.append(kind)
    task = asyncio.create_task(runtime.generate_tool_turn(messages=[], tools=TOOLS, schema={}, progress_callback=progress))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(closed.wait(), 2)
    assert "model.completed" not in events


@pytest.mark.asyncio
@pytest.mark.parametrize("finish,code", [("length", "MODEL_OUTPUT_EXHAUSTED"), (None, "MODEL_STREAM_INCOMPLETE")])
async def test_unfinished_turns_fail_without_becoming_executable_tool_calls(finish, code):
    class Transport:
        async def stream_json(self, **_):
            yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call", "function": {"name": "fs__list", "arguments": '{"path":'}}]}}]}
            if finish:
                yield {"choices": [{"delta": {}, "finish_reason": finish}]}

    runtime, _ = model(Transport())
    async def progress(*_):
        pass
    with pytest.raises(StructuredGenerationError) as failed:
        await runtime.generate_tool_turn(messages=[], tools=TOOLS, schema={}, progress_callback=progress)
    assert failed.value.code == code
