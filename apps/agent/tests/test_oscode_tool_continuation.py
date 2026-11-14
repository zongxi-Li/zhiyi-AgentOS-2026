"""Exercise OScode's real SDK stream and tool-continuation wire contract offline."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from agents import function_tool

from app.llm import chat_session
from app.llm.stream_transport import ModelStreamClient
from app.tools import runtime as runtime_module


def frame(delta, finish=None):
    return ("data: " + json.dumps({
        "id": "continuation-test", "object": "chat.completion.chunk", "created": 0,
        "model": "glm-5.3-flash",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }) + "\n\n").encode()


def install_client(monkeypatch, handler):
    class Client(ModelStreamClient):
        def __init__(self, policy, **kwargs):
            super().__init__(policy, transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(runtime_module, "ModelStreamClient", Client)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_glm_preserves_tool_turn_reasoning_on_continuation_and_restore(
    monkeypatch, tmp_path, streaming,
):
    monkeypatch.setattr(chat_session, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(chat_session, "current_trusted_user",
                        lambda: SimpleNamespace(user_id="test-user", tenant_id="test-tenant"))
    requests, effects = [], []
    reasoning = "Synthetic planning fragment. Synthetic continuation fragment."

    @function_tool
    def inspect_workspace() -> str:
        """Return a synthetic inspection result without accessing files."""
        effects.append("inspected")
        return "synthetic directory listing"

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            if streaming:
                data = (frame({"role": "assistant", "reasoning_content": reasoning})
                    + frame({"content": "Inspecting the workspace."})
                    + frame({"tool_calls": [{"index": 0, "id": "call_inspect", "type": "function",
                        "function": {"name": "inspect_workspace", "arguments": "{}"}}]})
                    + frame({}, "tool_calls") + b"data: [DONE]\n\n")
            else:
                return httpx.Response(200, json={
                    "id": "tool-response", "object": "chat.completion", "created": 0,
                    "model": "glm-5.3-flash", "choices": [{"index": 0, "finish_reason": "tool_calls",
                        "message": {"role": "assistant", "content": "Inspecting the workspace.",
                            "reasoning_content": reasoning, "tool_calls": [{"id": "call_inspect",
                                "type": "function", "function": {"name": "inspect_workspace", "arguments": "{}"}}]}}],
                })
        elif streaming:
            data = frame({"role": "assistant", "content": "Completed."}, "stop") + b"data: [DONE]\n\n"
        else:
            return httpx.Response(200, json={
                "id": "final-response", "object": "chat.completion", "created": 0,
                "model": "glm-5.3-flash", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Completed."}}],
            })
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)

    install_client(monkeypatch, handler)
    runtime = runtime_module.AgentsToolRuntime(allowed_tools=set())
    build = runtime._build_agent

    def with_tool(*args, **kwargs):
        agent, client, metadata = build(*args, **kwargs)
        agent.tools = [inspect_workspace]
        return agent, client, metadata

    monkeypatch.setattr(runtime, "_build_agent", with_tool)
    options = dict(model="glm-5.3-flash", base_url="https://open.bigmodel.cn/api/coding/paas/v4",
                   api_key="offline-test", session_id="continuation", thinking_mode="deep")
    if streaming:
        events = [event async for event in runtime.stream("inspect", request_id="first", **options)]
        assert "".join(e.data["delta"] for e in events if e.event.value == "reasoning_delta") == reasoning
    else:
        await runtime.run("inspect", **options)

    assert len(requests) == 2
    tool_message = next(m for m in requests[1]["messages"] if m.get("tool_calls"))
    assert tool_message.get("reasoning_content") == reasoning
    assert any(m.get("role") == "tool" and m.get("content") == "synthetic directory listing"
               for m in requests[1]["messages"])
    assert effects == ["inspected"]

    # Restoring a durable session must preserve the same protocol, without rerunning the tool.
    if streaming:
        _ = [event async for event in runtime.stream("follow up", request_id="second", **options)]
    else:
        await runtime.run("follow up", **options)
    restored = next(m for m in requests[2]["messages"] if m.get("tool_calls"))
    assert restored["reasoning_content"] == reasoning
    assert effects == ["inspected"]


@pytest.mark.asyncio
async def test_reasoning_is_forwarded_before_provider_response_finishes(monkeypatch):
    release = asyncio.Event()
    closed = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield frame({"role": "assistant", "reasoning_content": "first fragment"})
            await release.wait()
            yield frame({"reasoning_content": " second fragment"})
            yield frame({"content": "Completed."}, "stop")
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            closed.set()

    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    install_client(monkeypatch, handler)
    runtime = runtime_module.AgentsToolRuntime(allowed_tools=set())
    iterator = runtime.stream("inspect", model="glm-5.3-flash",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4", api_key="offline-test",
        request_id="streaming-test").__aiter__()
    try:
        async with asyncio.timeout(2):
            while (event := await anext(iterator)).event.value != "reasoning_delta":
                pass
        assert event.data["delta"] == "first fragment"
        assert not release.is_set() and not closed.is_set()
        release.set()
        events = [event async for event in iterator]
        assert any(e.event.value == "reasoning_delta" and e.data["delta"] == " second fragment" for e in events)
        assert events[-1].event.value == "done"
    finally:
        release.set()
        await iterator.aclose()
    assert closed.is_set()
