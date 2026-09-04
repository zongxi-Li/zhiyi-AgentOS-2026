from __future__ import annotations

import asyncio

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from contracts.capability import CapabilityKind, CapabilityManifest, ModelInvocationRequest, ModelStreamEvent


class _ClosingStreamingAdapter:
    manifest = CapabilityManifest(
        capabilityId="model.closing-stream",
        kind=CapabilityKind.MODEL,
        displayName="Closing stream fixture",
        provider="fixture",
        capabilities=["fixture-model"],
    )

    def __init__(self) -> None:
        self.closed = asyncio.Event()

    def describe_model(self, _model: str):
        from contracts.capability import ModelCapabilityEnvelope

        return ModelCapabilityEnvelope.unknown(provider="fixture", model="fixture-model")

    async def invoke(self, _request: ModelInvocationRequest):
        raise AssertionError("streaming test must not use the synchronous invoke path")

    def astream(self, request: ModelInvocationRequest):
        async def iterator():
            try:
                yield ModelStreamEvent(
                    requestId=request.request_id,
                    eventType="delta",
                    delta='{"task_summary":"live"}',
                    provider="fixture",
                    model="fixture-model",
                )
                await asyncio.Event().wait()
            finally:
                self.closed.set()

        return iterator()


def test_registered_model_runtime_closes_provider_iterator_on_consumer_cancel() -> None:
    adapter = _ClosingStreamingAdapter()
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    runtime = RegisteredModelRuntime(
        registry=registry,
        provider="fixture",
        model="fixture-model",
    )

    async def scenario() -> None:
        async def consume() -> None:
            async for event in runtime.stream_generate_json(
                prompt="private prompt",
                schema={"type": "object"},
                run_id="run-cancel-stream",
                node_id="node-1",
                attempt_id="attempt-1",
            ):
                if event.event_type == "model.output.delta":
                    task = asyncio.current_task()
                    assert task is not None
                    task.cancel()

        task = asyncio.create_task(consume())
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.wait_for(adapter.closed.wait(), timeout=1)

    asyncio.run(scenario())


def test_private_provider_activity_keeps_stream_alive_until_public_json_arrives() -> None:
    class _ThinkingAdapter(_ClosingStreamingAdapter):
        def astream(self, request: ModelInvocationRequest):
            async def iterator():
                for _ in range(4):
                    await asyncio.sleep(0.01)
                    yield ModelStreamEvent(
                        requestId=request.request_id, eventType="activity",
                        provider="fixture", model="fixture-model",
                    )
                yield ModelStreamEvent(
                    requestId=request.request_id, eventType="delta", delta='{"answer":"ok"}',
                    provider="fixture", model="fixture-model",
                )
                yield ModelStreamEvent(
                    requestId=request.request_id, eventType="completed",
                    provider="fixture", model="fixture-model",
                )
            return iterator()

    adapter = _ThinkingAdapter()
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    runtime = RegisteredModelRuntime(registry=registry, provider="fixture", model="fixture-model")

    async def collect():
        return [event async for event in runtime.stream_generate_json(
            prompt="private prompt", schema={"type": "object"}, run_id="run-thinking",
            ttft_timeout=0.02, idle_timeout=0.03, total_timeout=0.2,
        )]

    events = asyncio.run(collect())
    assert any(event.event_type == "model.activity" for event in events)
    completed = next(event for event in events if event.event_type == "model.completed")
    assert completed.payload["data"] == {"answer": "ok"}


def test_registered_model_runtime_accepts_fenced_streamed_json() -> None:
    class _FencedAdapter(_ClosingStreamingAdapter):
        def astream(self, request: ModelInvocationRequest):
            async def iterator():
                yield ModelStreamEvent(
                    requestId=request.request_id, eventType="delta",
                    delta='```json\n{"answer":"ok"}\n```', provider="fixture", model="fixture-model",
                )
                yield ModelStreamEvent(
                    requestId=request.request_id, eventType="completed",
                    provider="fixture", model="fixture-model",
                )
            return iterator()

    registry = ModelCompatibilityRegistry()
    registry.register(_FencedAdapter())
    runtime = RegisteredModelRuntime(registry=registry, provider="fixture", model="fixture-model")

    async def collect():
        return [event async for event in runtime.stream_generate_json(
            prompt="private prompt", schema={"type": "object"}, run_id="run-fenced",
        )]

    completed = next(event for event in asyncio.run(collect()) if event.event_type == "model.completed")
    assert completed.payload["data"] == {"answer": "ok"}
