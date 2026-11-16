"""Shared call capacity must not share per-attempt model wrapper state."""

import asyncio
from time import monotonic

import pytest

from adapters.model.guarded import GuardedModelRuntime, ModelCallGateRegistry
from adapters.model.protocols import StructuredGenerationError, StructuredGenerationResult
from contracts.runtime_events import RuntimeEvent


class _Model:
    def __init__(self):
        self.started = []
        self.entered = None
        self.release = None

    async def generate_json(self, *, prompt, **kwargs):
        self.started.append((prompt, monotonic()))
        if prompt == "wait":
            self.entered.set()
            await self.release.wait()
        if prompt == "fail":
            raise StructuredGenerationError("MODEL_AUTH_INVALID", "permanent failure")
        return StructuredGenerationResult(data={"ok": True}, provider="test", model="test")

    async def stream_generate_json(self, **kwargs):
        self.started.append((kwargs["attempt_id"], monotonic()))
        self.entered.set()
        await self.release.wait()
        yield RuntimeEvent(eventType="model.completed", runId="run", sequence=1,
                           attemptId=kwargs["attempt_id"], payload={})


def _wrappers(delegate, *, interval=0):
    registry = ModelCallGateRegistry()
    return tuple(GuardedModelRuntime(
        delegate=delegate, max_concurrency=1, min_interval_seconds=interval,
        _gate=registry.gate_for("route", max_concurrency=1, min_interval_seconds=interval),
    ) for _ in range(2))


def test_shared_gate_preserves_stream_attempt_ids_and_serializes_json():
    delegate = _Model()
    first, second = _wrappers(delegate)

    async def run():
        delegate.entered, delegate.release = asyncio.Event(), asyncio.Event()

        async def consume(wrapper, attempt):
            return [event async for event in wrapper.stream_generate_json(attempt_id=attempt)]

        stream = asyncio.create_task(consume(first, "first-attempt"))
        await delegate.entered.wait()
        waiting = asyncio.create_task(consume(second, "second-attempt"))
        await asyncio.sleep(0)
        assert first.last_attempt_id == "first-attempt"
        assert second.last_attempt_id == "second-attempt"
        assert [name for name, _ in delegate.started] == ["first-attempt"]
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        pending_json = asyncio.create_task(second.generate_json(prompt="json", schema={}))
        await asyncio.sleep(0)
        assert not pending_json.done()
        delegate.release.set()
        assert (await stream)[0].attempt_id == "first-attempt"
        assert (await pending_json).data == {"ok": True}

    asyncio.run(asyncio.wait_for(run(), 2))


@pytest.mark.parametrize("failure", ["cancel", "error"])
def test_shared_gate_releases_capacity_after_call_failure(failure):
    delegate = _Model()
    first, second = _wrappers(delegate)

    async def run():
        delegate.entered, delegate.release = asyncio.Event(), asyncio.Event()
        if failure == "cancel":
            active = asyncio.create_task(first.generate_json(prompt="wait", schema={}))
            await delegate.entered.wait()
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
        else:
            with pytest.raises(StructuredGenerationError, match="MODEL_AUTH_INVALID"):
                await first.generate_json(prompt="fail", schema={})
        return await second.generate_json(prompt="next", schema={})

    assert asyncio.run(asyncio.wait_for(run(), 2)).data == {"ok": True}


def test_shared_gate_enforces_start_spacing_across_wrappers():
    delegate = _Model()
    first, second = _wrappers(delegate, interval=0.02)

    async def run():
        await asyncio.gather(first.generate_json(prompt="one", schema={}),
                             second.generate_json(prompt="two", schema={}))

    asyncio.run(run())
    assert delegate.started[1][1] - delegate.started[0][1] >= 0.02


def test_shared_gate_rejects_conflicting_route_policy():
    registry = ModelCallGateRegistry()
    gate = registry.gate_for("route", max_concurrency=1, min_interval_seconds=0)
    with pytest.raises(ValueError, match="policy cannot change"):
        registry.gate_for("route", max_concurrency=2, min_interval_seconds=0)
    with pytest.raises(ValueError, match="does not match"):
        GuardedModelRuntime(delegate=_Model(), max_concurrency=2, _gate=gate)


def test_shared_gate_rejects_a_second_live_loop_without_splitting_capacity():
    first, second = _wrappers(_Model())
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(first.generate_json(prompt="first", schema={}))
        with pytest.raises(StructuredGenerationError) as error:
            asyncio.run(second.generate_json(prompt="second", schema={}))
        assert error.value.code == "MODEL_GATE_EVENT_LOOP_MISMATCH"
    finally:
        loop.close()
    assert asyncio.run(second.generate_json(prompt="after-close", schema={})).data == {"ok": True}


def test_closing_stream_closes_delegate_before_releasing_shared_capacity():
    closed = []

    class EarlyStream(_Model):
        async def stream_generate_json(self, **kwargs):
            try:
                yield RuntimeEvent(eventType="model.output.delta", runId="run", sequence=1, payload={})
                await asyncio.Event().wait()
            finally:
                closed.append(True)

    first, second = _wrappers(EarlyStream())

    async def run():
        stream = first.stream_generate_json(attempt_id="first")
        await anext(stream)
        await stream.aclose()
        assert closed == [True]
        return await second.generate_json(prompt="after-close", schema={})

    assert asyncio.run(asyncio.wait_for(run(), 2)).data == {"ok": True}
