from __future__ import annotations

import asyncio

import pytest

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.model_adapter import StructuredGenerationError
from adapters.prompt_runtime import planner_prompt_metadata
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
            prompt_metadata=planner_prompt_metadata(),
        )]

    events = asyncio.run(collect())
    assert any(event.event_type == "model.activity" for event in events)
    completed = next(event for event in events if event.event_type == "model.completed")
    assert completed.payload["data"] == {"answer": "ok"}
    assert completed.payload["promptTemplateHash"]
    assert completed.payload["promptInstanceHash"]
    assert completed.payload["schemaHash"]
    assert completed.payload["streaming"] is True
    assert completed.payload["preset"] == "planner"


def test_stream_failure_audit_keeps_prompt_identity_without_raw_prompt() -> None:
    class _EmptyAdapter(_ClosingStreamingAdapter):
        def astream(self, _request: ModelInvocationRequest):
            async def iterator():
                if False:
                    yield
            return iterator()

    registry = ModelCompatibilityRegistry()
    registry.register(_EmptyAdapter())
    runtime = RegisteredModelRuntime(
        registry=registry, provider="fixture", model="fixture-model"
    )

    async def collect() -> None:
        async for _event in runtime.stream_generate_json(
            prompt='{"source":"TOP SECRET"}',
            schema={"type": "object"},
            run_id="run-empty",
            prompt_metadata=planner_prompt_metadata(),
        ):
            pass

    with pytest.raises(StructuredGenerationError) as captured:
        asyncio.run(collect())

    audit = captured.value.audit
    assert audit["promptTemplateHash"]
    assert audit["promptInstanceHash"]
    assert audit["schemaHash"]
    assert audit["streaming"] is True
    assert "TOP SECRET" not in str(audit)


@pytest.mark.parametrize("finish,body,code", [
    ("stop", "PRIVATE-INVALID-JSON", "MODEL_OUTPUT_INVALID_JSON"),
    ("length", '{"answer":', "MODEL_OUTPUT_EXHAUSTED"),
])
def test_consumed_stream_usage_survives_decoding_and_capacity_failure(finish, body, code):
    class _MalformedAdapter(_ClosingStreamingAdapter):
        def astream(self, request):
            async def iterator():
                yield ModelStreamEvent(requestId=request.request_id, eventType="delta", delta=body,
                                       provider="fixture", model="fixture-model")
                yield ModelStreamEvent(requestId=request.request_id, eventType="completed",
                                       provider="fixture", model="fixture-model",
                                       metadata={"finishReason": finish, "usage": {"prompt_tokens": 101, "completion_tokens": 31}})
            return iterator()
    registry = ModelCompatibilityRegistry()
    registry.register(_MalformedAdapter())
    runtime = RegisteredModelRuntime(registry=registry, provider="fixture", model="fixture-model")
    async def collect():
        async for _ in runtime.stream_generate_json(prompt="PRIVATE-PROMPT", schema={"type": "object"}, run_id="run-malformed"):
            pass
    with pytest.raises(StructuredGenerationError) as captured:
        asyncio.run(collect())
    assert captured.value.code == code
    assert captured.value.audit["usage"] == {"prompt_tokens": 101, "completion_tokens": 31}
    assert captured.value.audit["finishReason"] == finish
    assert captured.value.audit["model"] == "fixture-model"
    assert "PRIVATE-PROMPT" not in str(captured.value.audit)
    assert "PRIVATE-INVALID-JSON" not in str(captured.value.audit)


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


def test_registered_model_runtime_projects_stream_usage_finish_reason_and_latency() -> None:
    class _UsageAdapter(_ClosingStreamingAdapter):
        def astream(self, request: ModelInvocationRequest):
            async def iterator():
                await asyncio.sleep(0.01)
                yield ModelStreamEvent(
                    requestId=request.request_id,
                    eventType="delta",
                    delta='{"answer":"ok"}',
                    provider="fixture",
                    model="fixture-model",
                )
                yield ModelStreamEvent(
                    requestId=request.request_id,
                    eventType="completed",
                    provider="fixture",
                    model="fixture-model",
                    metadata={
                        "finishReason": "stop",
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 3,
                            "total_tokens": 15,
                        },
                    },
                )
            return iterator()

    registry = ModelCompatibilityRegistry()
    registry.register(_UsageAdapter())
    runtime = RegisteredModelRuntime(registry=registry, provider="fixture", model="fixture-model")

    async def collect():
        return [event async for event in runtime.stream_generate_json(
            prompt="private prompt", schema={"type": "object"}, run_id="run-usage",
        )]

    completed = next(event for event in asyncio.run(collect()) if event.event_type == "model.completed")
    assert completed.payload["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }


def test_registered_model_runtime_forwards_reasoning_effort_on_stream() -> None:
    """流式桥接同样必须把显式 reasoning_effort 写入统一请求选项。"""

    captured: list[ModelInvocationRequest] = []

    class _CapturingAdapter(_ClosingStreamingAdapter):
        def astream(self, request: ModelInvocationRequest):
            captured.append(request)

            async def iterator():
                yield ModelStreamEvent(
                    requestId=request.request_id, eventType="delta",
                    delta='{"answer":"ok"}', provider="fixture", model="fixture-model",
                )
                yield ModelStreamEvent(
                    requestId=request.request_id, eventType="completed",
                    provider="fixture", model="fixture-model",
                )
            return iterator()

    registry = ModelCompatibilityRegistry()
    registry.register(_CapturingAdapter())
    runtime = RegisteredModelRuntime(registry=registry, provider="fixture", model="fixture-model")

    async def collect():
        return [event async for event in runtime.stream_generate_json(
            prompt="private prompt", schema={"type": "object"}, run_id="run-effort",
            reasoning_effort="max",
        )]

    asyncio.run(collect())

    assert captured and captured[0].options.get("reasoning_effort") == "max"
