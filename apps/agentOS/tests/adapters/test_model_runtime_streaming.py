from __future__ import annotations

import asyncio

import pytest

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.model_adapter import StructuredGenerationError
from adapters.prompt_runtime import planner_prompt_metadata
from contracts.capability import CapabilityKind, CapabilityManifest, ModelInvocationRequest, ModelInvocationResponse, ModelStreamEvent
from support.model_stream_policy import ModelStreamPolicy


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


def test_stream_quota_settles_usage_and_releases_capacity_before_next_call() -> None:
    from datetime import timedelta

    from components.resource.scheduler.leases import InMemoryLeaseCoordinator
    from contracts.resource import ModelQuotaPolicy
    from runtime.model_quota import ModelCallQuota

    class _CompletedAdapter(_ClosingStreamingAdapter):
        def astream(self, request):
            async def iterator():
                try:
                    yield ModelStreamEvent(requestId=request.request_id, eventType="delta", delta='{"answer":"ok"}',
                                           provider="fixture", model="fixture-model")
                    yield ModelStreamEvent(requestId=request.request_id, eventType="completed",
                                           provider="fixture", model="fixture-model", metadata={"usage": {"total_tokens": 2}})
                finally:
                    self.closed.set()
            return iterator()

    adapter = _CompletedAdapter()
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    coordinator = InMemoryLeaseCoordinator()
    records = []
    quota = ModelCallQuota(coordinator=coordinator,
        policy=ModelQuotaPolicy(scope="shared-stream", maxConcurrency=1, tokensPerMinute=100_000),
        audit=lambda _resource, record: records.append(record))
    runtime = RegisteredModelRuntime(registry=registry, provider="fixture", model="fixture-model", call_quota=quota)

    def stream(**timeouts):
        return runtime.stream_generate_json(prompt="private prompt", schema={"type": "object"},
                                            run_id="run-quota-stream", max_output_tokens=8, **timeouts)

    async def scenario():
        for _ in range(2):
            adapter.closed.clear()
            events = [event async for event in stream()]
            assert events[-1].event_type == "model.completed"
            assert adapter.closed.is_set() and coordinator.active_slots(quota.resource_id) == 0
            assert records[-1]["actualTokens"] == 2 and records[-1]["status"] == "settled"
        occupied = coordinator.acquire(lease_id="occupied-stream", resource_id=quota.resource_id, capacity=1,
            run_id="other-run", step_id="other-step", attempt_id="other-attempt", ttl=timedelta(seconds=2))
        assert occupied is not None

        async def release_capacity():
            await asyncio.sleep(.03)
            coordinator.release(occupied.lease_id)

        release_task = asyncio.create_task(release_capacity())
        try:
            events = [event async for event in stream(ttft_timeout=.005, total_timeout=1)]
        finally:
            await release_task
        assert events[-1].event_type == "model.completed"
        assert coordinator.active_slots(quota.resource_id) == 0 and records[-1]["actualTokens"] == 2
        adapter.closed.clear()
        partial = stream()
        async for event in partial:
            if event.event_type == "model.output.delta":
                break
        await partial.aclose()
        assert adapter.closed.is_set() and coordinator.active_slots(quota.resource_id) == 0
        assert len(records) == 4 and records[-1]["status"] == "unknown"

    asyncio.run(scenario())


def test_private_provider_activity_keeps_stream_alive_until_public_json_arrives() -> None:
    # provider 活动节奏用注入时钟表达：Windows 默认计时粒度（~15.6ms）下，
    # 真实 sleep(0.01) 的唤醒延迟在 10~25.6ms 间随机分布，会以固定概率越过
    # 20ms TTFT 窗口，把"provider 活动 10ms 后到达"的题设变成随机的
    # MODEL_TTFT_TIMEOUT。clock/wait_for 是本运行时公开的确定性测试钩子
    # （先例见 test_model_runtime.py 的 failover 超时测试）；deadline 数值、
    # 事件序列与断言保持原语义。
    clock_state = {"now": 0.0}

    def fake_clock() -> float:
        return clock_state["now"]

    async def clocked_wait_for(awaitable, timeout: float):
        # 以注入时钟执行 wait_for 的超时契约：awaitable 完成后若虚拟时间
        # 已越过 deadline，等价于真实 wait_for 的 TimeoutError 路径。
        started = clock_state["now"]
        result = await awaitable
        if clock_state["now"] - started > timeout:
            raise asyncio.TimeoutError
        return result

    class _ThinkingAdapter(_ClosingStreamingAdapter):
        def astream(self, request: ModelInvocationRequest):
            async def iterator():
                for _ in range(4):
                    await asyncio.sleep(0)
                    clock_state["now"] += 0.01
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
    runtime = RegisteredModelRuntime(
        registry=registry,
        provider="fixture",
        model="fixture-model",
        clock=fake_clock,
        wait_for=clocked_wait_for,
    )

    async def collect():
        return [event async for event in runtime.stream_generate_json(
            prompt="private prompt", schema={"type": "object"}, run_id="run-thinking",
            # The fixture yields every 10ms. Leave headroom for Windows event
            # loop scheduling when the full suite is under load; this test
            # validates private provider activity, not sub-20ms latency.
            ttft_timeout=0.10, idle_timeout=0.10, total_timeout=0.5,
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


class _StreamClock:
    """Advance event time deterministically, canceling stalled iterator reads."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def wait_for(self, awaitable, timeout):
        started = self.now
        task = asyncio.ensure_future(awaitable)
        await asyncio.sleep(0)
        if not task.done():
            self.now += timeout
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise asyncio.TimeoutError
        result = task.result()
        if self.now - started > timeout:
            raise asyncio.TimeoutError
        return result


class _ToolActivityAdapter(_ClosingStreamingAdapter):
    supports_streamed_tool_turns = True

    def __init__(self, events, clock):
        super().__init__()
        self.events, self.clock = events, clock

    def describe_model(self, model):
        capability = super().describe_model(model)
        return capability.model_copy(update={"features": capability.features.model_copy(update={"tools": True})})

    def astream(self, request):
        async def iterator():
            try:
                for kind, delay in self.events:
                    if kind == "stall":
                        await asyncio.Event().wait()
                    self.clock.now += delay
                    event = {"requestId": request.request_id, "eventType": kind,
                        "provider": "fixture", "model": "fixture-model"}
                    if kind == "delta":
                        event["delta"] = '{"answer":"ok"}'
                    elif kind == "reasoning_delta":
                        event["delta"] = "PRIVATE REASONING"
                    elif kind == "tool_call":
                        event["toolArguments"] = "PRIVATE ARGUMENTS"
                    if kind == "completed":
                        event["response"] = ModelInvocationResponse(requestId=request.request_id,
                            provider="fixture", model="fixture-model", content={"answer": "ok"})
                    event["metadata"] = {"usage": {"total_tokens": 3}}
                    yield ModelStreamEvent(**event)
            finally:
                self.closed.set()
        return iterator()


def _activity_runtime(events):
    clock = _StreamClock()
    adapter = _ToolActivityAdapter(events, clock)
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    runtime = RegisteredModelRuntime(registry=registry, provider="fixture", model="fixture-model",
        clock=clock, wait_for=clock.wait_for)
    return runtime, adapter, clock


async def _consume_activity_runtime(runtime, path="tools", **kwargs):
    if path == "json":
        return [event async for event in runtime.stream_generate_json(prompt="PRIVATE PROMPT",
            schema={"type": "object"}, run_id="run-phase-timeout", **kwargs)]

    async def progress(_kind, _payload):
        pass

    return await runtime.generate_tool_turn(messages=[{"role": "user", "content": "PRIVATE PROMPT"}],
        tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}],
        schema={"type": "object"}, timeout_seconds=2, progress_callback=progress, **kwargs)


@pytest.mark.parametrize("path", ["tools", "json"])
@pytest.mark.parametrize(("events", "code"), [
    ([("stall", 0)], "MODEL_TTFT_TIMEOUT"),
    ([("delta", .01), ("stall", 0)], "MODEL_IDLE_TIMEOUT"),
    ([("reasoning_delta", .01), ("stall", 0)], "MODEL_IDLE_TIMEOUT"),
])
def test_stream_paths_share_first_response_and_idle_deadlines(monkeypatch, path, events, code):
    monkeypatch.setattr(ModelStreamPolicy, "from_environment", classmethod(
        lambda cls: ModelStreamPolicy(first_response=.05, idle=.08, total=1)))
    runtime, adapter, _ = _activity_runtime(events)
    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(_consume_activity_runtime(runtime, path))
    assert caught.value.code == code
    assert adapter.closed.is_set()
    assert "PRIVATE" not in str(caught.value.audit)
    if path == "tools":
        diagnostics = caught.value.audit["streamDiagnostics"]
        assert diagnostics["streamTerminationReason"] == code
        assert diagnostics["completionObserved"] is False


@pytest.mark.parametrize("path", ["tools", "json"])
@pytest.mark.parametrize("kind", ["activity", "reasoning_delta", "tool_call"])
def test_private_activity_refreshes_stream_deadline_without_public_output(monkeypatch, path, kind):
    monkeypatch.setattr(ModelStreamPolicy, "from_environment", classmethod(
        lambda cls: ModelStreamPolicy(first_response=.05, idle=.08, total=1)))
    runtime, adapter, clock = _activity_runtime([(kind, .04)] * 6 + [("delta", .01), ("completed", .01)])
    result = asyncio.run(_consume_activity_runtime(runtime, path))
    assert clock.now > .05
    assert adapter.closed.is_set()
    if path == "tools":
        assert result.content == {"answer": "ok"}
    else:
        assert result[-1].payload["data"] == {"answer": "ok"}


@pytest.mark.parametrize("path", ["tools", "json"])
def test_active_streams_still_obey_total_policy(monkeypatch, path):
    monkeypatch.setattr(ModelStreamPolicy, "from_environment", classmethod(
        lambda cls: ModelStreamPolicy(first_response=.05, idle=.08, total=.1)))
    runtime, adapter, _ = _activity_runtime([("activity", .04)] * 4 + [("completed", 0)])
    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(_consume_activity_runtime(runtime, path))
    assert caught.value.code == "MODEL_TOTAL_TIMEOUT"
    assert adapter.closed.is_set()


def test_tool_stream_overall_deadline_caps_a_blocked_progress_consumer(monkeypatch):
    monkeypatch.setattr(ModelStreamPolicy, "from_environment", classmethod(
        lambda cls: ModelStreamPolicy(first_response=1, idle=1, total=2)))
    runtime, adapter, _ = _activity_runtime([("delta", 0), ("completed", 0)])

    async def blocked_progress(kind, _payload):
        if kind == "model.output.delta":
            await asyncio.Event().wait()

    async def run():
        await runtime.generate_tool_turn(messages=[], tools=[{"type": "function", "function": {"name": "read"}}],
            schema={}, timeout_seconds=.05, progress_callback=blocked_progress)

    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(run())
    assert caught.value.code == "MODEL_TIMEOUT"
    assert caught.value.audit["streamDiagnostics"]["firstTokenObserved"] is True
    assert caught.value.audit["usage"] == {"total_tokens": 3}
    assert adapter.closed.is_set()


def test_tool_stream_external_cancellation_preserves_cancellation_and_closes_iterator():
    runtime, adapter, _ = _activity_runtime([("activity", 0), ("stall", 0)])
    runtime._wait_for = asyncio.wait_for

    async def run():
        started = asyncio.Event()

        async def progress(kind, _payload):
            if kind == "model.started":
                started.set()

        task = asyncio.create_task(runtime.generate_tool_turn(messages=[],
            tools=[{"type": "function", "function": {"name": "read"}}], schema={},
            timeout_seconds=2, progress_callback=progress))
        await started.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert adapter.closed.is_set()

    asyncio.run(run())


def test_tool_stream_quota_admission_precedes_provider_deadlines_and_releases_slot(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    monkeypatch.setattr(ModelStreamPolicy, "from_environment", classmethod(
        lambda cls: ModelStreamPolicy(first_response=.05, idle=.08, total=1)))
    runtime, adapter, clock = _activity_runtime([("delta", .01), ("completed", .01)])
    slots = {"active": 0, "entries": 0}

    @asynccontextmanager
    async def quota(_request, _timeout):
        # Model capacity wait is not provider first-response latency.
        clock.now += .2
        slots["active"] += 1
        slots["entries"] += 1
        try:
            yield SimpleNamespace(observe=lambda _usage: None)
        finally:
            slots["active"] -= 1

    runtime._call_quota = quota
    result = asyncio.run(_consume_activity_runtime(runtime))
    assert result.content == {"answer": "ok"}
    assert slots == {"active": 0, "entries": 1}
    assert adapter.closed.is_set()


def test_registered_runtime_declares_tool_turn_deadline_ownership():
    runtime, _adapter, _clock = _activity_runtime([("delta", .01), ("completed", .01)])
    assert runtime.manages_tool_turn_timeout is True
