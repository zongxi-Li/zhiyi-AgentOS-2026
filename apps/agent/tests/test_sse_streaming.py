import asyncio
import json

import pytest

from app.api.chat import _stream_sse_events


class FakeRequest:
    def __init__(self, disconnect_after=None):
        self.calls = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self):
        self.calls += 1
        return self.disconnect_after is not None and self.calls >= self.disconnect_after


async def collect(generator):
    return [event async for event in generator]


@pytest.mark.asyncio
async def test_stream_preserves_data_and_done_format():
    async def chunks():
        yield "first"
        yield "second"

    events = await collect(_stream_sse_events(chunks(), FakeRequest(), 0.05))

    first = json.loads(events[0].split("data: ", 1)[1])
    second = json.loads(events[1].split("data: ", 1)[1])
    done = json.loads(events[-1].split("data: ", 1)[1])
    assert first["event"] == "content_delta"
    assert first["data"]["delta"] == "first"
    assert second["data"]["delta"] == "second"
    assert done["event"] == "done"


@pytest.mark.asyncio
async def test_heartbeat_is_emitted_while_model_is_idle():
    async def chunks():
        await asyncio.sleep(0.06)
        yield "ready"

    events = await collect(_stream_sse_events(chunks(), FakeRequest(), 0.01))

    assert events.count(": heartbeat\n\n") >= 3
    heartbeat_events = [event for event in events if "event: heartbeat\n" in event]
    assert len(heartbeat_events) >= 3
    heartbeat = json.loads(heartbeat_events[0].split("data: ", 1)[1])
    assert heartbeat["event"] == "heartbeat"
    assert heartbeat["data"]["status"] == "waiting"
    assert '"event": "done"' in events[-1]


@pytest.mark.asyncio
async def test_heartbeats_and_runtime_events_share_one_wire_sequence():
    from app.llm.chat_stream import ChatStreamEvent, ChatStreamEventType

    release = asyncio.Event()
    runtime_events = [
        ChatStreamEvent(event=ChatStreamEventType.CONTENT_DELTA, request_id="one", sequence=1, data={"delta": "before"}),
        ChatStreamEvent(event=ChatStreamEventType.CONTENT_DELTA, request_id="one", sequence=2, data={"delta": "after"}),
        ChatStreamEvent(event=ChatStreamEventType.DONE, request_id="one", sequence=3, data={"status": "completed"}),
    ]

    async def chunks():
        yield runtime_events[0]
        await release.wait()
        yield runtime_events[1]
        yield runtime_events[2]

    iterator = _stream_sse_events(chunks(), FakeRequest(), .001, request_id="one").__aiter__()
    frames = [await anext(iterator)]
    try:
        heartbeats = 0
        async with asyncio.timeout(2):
            while heartbeats < 2:
                frame = await anext(iterator)
                frames.append(frame)
                heartbeats += frame.startswith("event: heartbeat\n")
        release.set()
        frames.extend([frame async for frame in iterator])
    finally:
        release.set()
        await iterator.aclose()

    payloads = [json.loads(frame.split("data: ", 1)[1]) for frame in frames if "data: " in frame]
    assert [item["sequence"] for item in payloads] == list(range(1, len(payloads) + 1))
    assert [item["data"].get("delta") for item in payloads if item["event"] == "content_delta"] == ["before", "after"]
    assert payloads[-1]["event"] == "done"
    # SSE framing owns its sequence; the reusable runtime events stay unchanged.
    assert [item.sequence for item in runtime_events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_disconnect_closes_pending_model_generator_without_done():
    closed = asyncio.Event()

    async def chunks():
        try:
            await asyncio.sleep(10)
            yield "never"
        finally:
            closed.set()

    events = await collect(_stream_sse_events(chunks(), FakeRequest(disconnect_after=2), 0.01))

    assert events == []
    assert closed.is_set()


@pytest.mark.asyncio
async def test_model_exception_is_not_reflected_to_client():
    async def chunks():
        raise RuntimeError("private-key-material")
        yield  # pragma: no cover

    events = await collect(_stream_sse_events(chunks(), FakeRequest(), 0.01))

    assert len(events) == 1
    assert "AI_STREAM_FAILED" in events[0]
    assert "private-key-material" not in events[0]


@pytest.mark.asyncio
async def test_turn_limit_failure_reports_its_own_code():
    from agents.exceptions import MaxTurnsExceeded

    async def chunks():
        raise MaxTurnsExceeded("Max turns (6) exceeded")
        yield  # pragma: no cover

    events = await collect(_stream_sse_events(chunks(), FakeRequest(), 0.01))

    payload = json.loads(events[0].split("data: ", 1)[1])
    assert payload["data"]["code"] == "AI_TURN_LIMIT_EXCEEDED"
    assert payload["data"]["retryable"] is False
    assert "本次回复达到工具轮数上限" in payload["data"]["message"]


@pytest.mark.asyncio
async def test_timeout_failure_reports_upstream_timeout():
    async def chunks():
        raise asyncio.TimeoutError()
        yield  # pragma: no cover

    events = await collect(_stream_sse_events(chunks(), FakeRequest(), 0.01))

    payload = json.loads(events[0].split("data: ", 1)[1])
    assert payload["data"]["code"] == "AI_UPSTREAM_TIMEOUT"
    assert payload["data"]["retryable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,code", [
    ("first_response", "AI_MODEL_FIRST_RESPONSE_TIMEOUT"),
    ("idle", "AI_MODEL_IDLE_TIMEOUT"), ("total", "AI_MODEL_TOTAL_TIMEOUT"),
])
async def test_model_wait_phase_is_preserved_without_replaying_partial_output(phase, code):
    from support.model_stream_policy import ModelStreamTimeout

    async def chunks():
        yield "已输出"
        raise ModelStreamTimeout(phase)

    events = await collect(_stream_sse_events(chunks(), FakeRequest(), .01))
    assert "已输出" in events[0]
    payload = json.loads(events[-1].split("data: ", 1)[1])
    assert payload["data"]["code"] == code
    assert payload["data"]["retryable"] is False
    assert not any("event: done" in event for event in events)


@pytest.mark.asyncio
async def test_raw_httpx_read_timeout_has_timeout_classification():
    import httpx

    async def chunks():
        raise httpx.ReadTimeout("secret must not be exposed")
        yield

    events = await collect(_stream_sse_events(chunks(), FakeRequest(), .01))
    assert "AI_UPSTREAM_TIMEOUT" in events[0]
    assert "secret" not in events[0]
