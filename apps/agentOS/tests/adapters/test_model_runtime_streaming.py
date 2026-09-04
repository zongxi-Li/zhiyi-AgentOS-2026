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
