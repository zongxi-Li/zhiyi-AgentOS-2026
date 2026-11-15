from __future__ import annotations

import asyncio
from time import monotonic

import pytest

from adapters.model_runtime import RegisteredModelRuntime
from components.planner.complexity import call_planning_model
from components.planner.intent_analyzer import IntentParser
from contracts.capability import CapabilityKind, CapabilityManifest, ModelCapabilityEnvelope, ModelStreamEvent
from contracts.runtime_events import RuntimeEvent
from adapters.model_compatibility import ModelCompatibilityRegistry


class _PlannerStream:
    provider = "fake"
    model = "planner-1"

    async def stream_generate_json(self, **kwargs):
        assert kwargs["run_id"] == "run-stream"
        assert kwargs["node_id"] is None
        assert kwargs["attempt_id"] is None
        assert kwargs["emit_output_deltas"] is True
        yield RuntimeEvent(eventType="model.started", runId="run-stream", sequence=1, payload={})
        yield RuntimeEvent(eventType="model.first_token", runId="run-stream", sequence=2, payload={"elapsedMs": 12})
        yield RuntimeEvent(eventType="model.output.delta", runId="run-stream", sequence=3, payload={"delta": '{"ok": true}'})
        yield RuntimeEvent(eventType="model.activity", runId="run-stream", sequence=4, payload={"elapsedMs": 18, "idleMs": 2, "receivedChunks": 1, "receivedLength": 12})
        yield RuntimeEvent(eventType="model.completed", runId="run-stream", sequence=5, payload={"data": {"ok": True}})


def test_planner_stream_publishes_transient_structured_output_deltas() -> None:
    progress: list[dict] = []
    result = call_planning_model(
        _PlannerStream(),
        stage="outline",
        call_key="outline",
        prompt="SECRET_PROMPT",
        schema={"type": "object"},
        audit={},
        model_timeout_seconds=2,
        planning_deadline=monotonic() + 2,
        run_id="run-stream",
        progress_callback=progress.append,
    )

    assert result["data"] == {"ok": True}
    assert [item["eventType"] for item in progress] == [
        "planner.stage.started",
        "planner.model.started",
        "planner.model.first_token",
        "planner.model.output.delta",
        "planner.model.activity",
        "planner.model.completed",
        "planner.stage.completed",
    ]
    assert all("SECRET_PROMPT" not in str(item) for item in progress)
    delta = next(item for item in progress if item["eventType"] == "planner.model.output.delta")
    assert delta["delta"] == '{"ok": true}'
    assert delta["persistTrace"] is False
    assert all(item.get("callKey") == "outline" for item in progress)


def test_planner_calls_share_one_total_deadline_across_retries() -> None:
    progress: list[dict] = []
    started = monotonic()
    with pytest.raises(TimeoutError) as error:
        call_planning_model(
            _registered_runtime(_StreamingAdapter("ttft")),
            stage="relations",
            call_key="relations",
            prompt="{}",
            schema={"type": "object"},
            audit={},
            model_timeout_seconds=1,
            planning_deadline=started + 0.015,
            run_id="run-budget",
            progress_callback=progress.append,
        )
    assert getattr(error.value, "code", None) == "MODEL_TIMEOUT"
    assert monotonic() - started < 0.5
    assert any(item.get("eventType") == "planner.stage.retry" for item in progress)


def test_intent_profile_repair_uses_a_distinct_stream_call_key() -> None:
    class RepairStream:
        provider = "fake"
        model = "planner-1"

        def __init__(self) -> None:
            self.call_keys: list[str] = []

        async def stream_generate_json(self, **kwargs):
            self.call_keys.append(str(kwargs.get("prompt", "")))
            result = (
                {"primaryGoal": "", "requiredCapabilities": [], "estimatedComplexity": "simple"}
                if len(self.call_keys) == 1
                else {"primaryGoal": "analyze the request", "requiredCapabilities": ["analysis"], "estimatedComplexity": "simple"}
            )
            run_id = kwargs["run_id"]
            yield RuntimeEvent(eventType="model.started", runId=run_id, sequence=1, payload={})
            yield RuntimeEvent(eventType="model.first_token", runId=run_id, sequence=2, payload={"elapsedMs": 1})
            yield RuntimeEvent(eventType="model.completed", runId=run_id, sequence=3, payload={"data": result})

    llm = RepairStream()
    progress: list[dict] = []
    parser = IntentParser(llm=llm, progress_callback=progress.append)
    profile = parser.parse(intent="analyze this request", run_id="run-repair")

    assert profile.primary_goal == "analyze the request"
    assert len(llm.call_keys) == 2
    call_keys = [item.get("callKey") for item in progress if item.get("eventType") == "planner.model.started"]
    assert call_keys == ["intent_profile", "intent_profile.repair1"]


class _StreamingAdapter:
    def __init__(self, mode: str = "normal") -> None:
        self.mode = mode
        self.closed = False
        self.manifest = CapabilityManifest(
            capabilityId="fake-planner-runtime",
            kind=CapabilityKind.MODEL,
            displayName="fake planner",
            provider="fake",
            capabilities=["planner-1"],
            version="1.0.0",
        )

    def is_available(self) -> bool:
        return True

    def describe_model(self, model: str) -> ModelCapabilityEnvelope:
        return ModelCapabilityEnvelope.unknown(provider="fake", model=model, version="1.0.0")

    async def invoke(self, request):  # pragma: no cover - stream-only fixture
        raise AssertionError("planner test must use the provider stream")

    async def astream(self, request):
        try:
            if self.mode == "ttft":
                await asyncio.sleep(0.05)
            if self.mode == "exhausted":
                yield ModelStreamEvent(requestId=request.request_id, eventType="delta", delta='{"ok":', provider="fake", model="planner-1")
                yield ModelStreamEvent(requestId=request.request_id, eventType="completed", provider="fake", model="planner-1", metadata={"finishReason": "length"})
                return
            yield ModelStreamEvent(requestId=request.request_id, eventType="delta", delta='{"ok":', provider="fake", model="planner-1")
            if self.mode == "slow-active":
                await asyncio.sleep(0.01)
            yield ModelStreamEvent(requestId=request.request_id, eventType="delta", delta="true}", provider="fake", model="planner-1")
            yield ModelStreamEvent(requestId=request.request_id, eventType="completed", provider="fake", model="planner-1")
        finally:
            self.closed = True


def _registered_runtime(adapter: _StreamingAdapter) -> RegisteredModelRuntime:
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    return RegisteredModelRuntime(registry=registry, provider="fake", model="planner-1")


def test_registered_stream_reports_ttft_and_idle_deadlines() -> None:
    async def scenario() -> None:
        adapter = _StreamingAdapter("slow-active")
        runtime = _registered_runtime(adapter)
        events = [event async for event in runtime.stream_generate_json(
            prompt="{}", schema={"type": "object"}, run_id="run-1",
            ttft_timeout=0.05, idle_timeout=0.05, total_timeout=0.2,
        )]
        assert [event.event_type for event in events] == [
            "model.started", "model.first_token", "model.output.delta", "model.activity",
            "model.output.delta", "model.activity", "model.completed",
        ]
        assert events[1].payload["elapsedMs"] >= 0
        assert events[3].payload["idleMs"] >= 0

        timed_out = _StreamingAdapter("ttft")
        with pytest.raises(Exception) as error:
            _ = [event async for event in _registered_runtime(timed_out).stream_generate_json(
                prompt="{}", schema={"type": "object"}, run_id="run-2",
                ttft_timeout=0.01, idle_timeout=0.05, total_timeout=0.1,
            )]
        assert getattr(error.value, "code", None) == "MODEL_TTFT_TIMEOUT"

        with pytest.raises(Exception) as exhausted:
            _ = [event async for event in _registered_runtime(_StreamingAdapter("exhausted")).stream_generate_json(
                prompt="{}", schema={"type": "object"}, run_id="run-3",
                ttft_timeout=0.1, idle_timeout=0.1, total_timeout=0.2,
            )]
        assert getattr(exhausted.value, "code", None) == "MODEL_OUTPUT_EXHAUSTED"

    asyncio.run(scenario())


def test_registered_stream_closes_provider_iterator_on_cancellation() -> None:
    async def scenario() -> None:
        adapter = _StreamingAdapter("ttft")
        runtime = _registered_runtime(adapter)
        async def consume() -> None:
            async for _ in runtime.stream_generate_json(
                prompt="{}", schema={"type": "object"}, run_id="run-cancel",
                ttft_timeout=1, idle_timeout=1, total_timeout=2,
            ):
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert adapter.closed is True

    asyncio.run(scenario())
