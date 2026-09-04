"""OpenAI 兼容模型运行时的合同测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.http_transport import HttpTransportError
from adapters.openai_runtime import ModelInvocationError, OpenAICompatibleRuntime
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
)


class _JsonTransport:
    """记录运行时发出的 JSON 请求，不建立真实网络连接。"""

    def __init__(self) -> None:
        self.path: str | None = None
        self.payload: dict | None = None
        self.idempotency_key: str | None = None

    async def post_json(self, *, path: str, payload: dict, idempotency_key: str | None = None) -> dict:
        """返回 OpenAI Chat Completions 兼容的最小 JSON 响应。"""
        self.path = path
        self.payload = payload
        self.idempotency_key = idempotency_key
        return {
            "id": "chatcmpl-test",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"answer":"ok"}'},
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }


def test_openai_compatible_runtime_maps_json_request_and_response() -> None:
    """注入式传输应收到标准请求，并把 JSON 文本映射为统一模型响应。"""
    transport = _JsonTransport()
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.local",
            kind=CapabilityKind.MODEL,
            displayName="Local compatible model",
            provider="openai_compatible",
            capabilities=["local-chat"],
        ),
        transport=transport,
    )

    response = asyncio.run(
        runtime.invoke(
            ModelInvocationRequest(
                requestId="request-1",
                model="local-chat",
                messages=[{"role": "user", "content": "只返回 JSON"}],
                responseSchema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
                options={"temperature": 0},
                commitId="commit:run-1:step-1:0",
            )
        )
    )

    assert transport.path == "/chat/completions"
    assert transport.payload == {
        "model": "local-chat",
        "messages": [{"role": "user", "content": "只返回 JSON"}],
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "agentos_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            },
        },
    }
    assert response.request_id == "request-1"
    assert response.content == {"answer": "ok"}
    assert response.provider == "openai_compatible"
    assert response.model == "local-chat"
    assert response.usage == {"prompt_tokens": 12, "completion_tokens": 3}
    assert response.metadata == {"finishReason": "stop"}
    assert transport.idempotency_key == "commit:run-1:step-1:0"


def test_openai_compatible_runtime_preserves_safe_transport_error_code() -> None:
    """HTTP 限流等传输错误必须保留稳定代码，不能退化为无差别供应商失败。"""
    class _RateLimitedTransport:
        async def post_json(self, **_kwargs) -> dict:
            raise HttpTransportError("MODEL_RATE_LIMITED", "private provider body")

    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.limit",
            kind=CapabilityKind.MODEL,
            displayName="Limited model",
            provider="openai_compatible",
            capabilities=["local-chat"],
        ),
        transport=_RateLimitedTransport(),
    )

    with pytest.raises(ModelInvocationError) as captured:
        asyncio.run(
            runtime.invoke(
                ModelInvocationRequest(requestId="request-1", model="local-chat")
            )
        )

    assert captured.value.code == "MODEL_RATE_LIMITED"
    assert "private provider body" not in str(captured.value)


def test_openai_runtime_classifies_length_finish_as_capacity_exhaustion() -> None:
    class _LengthTransport:
        async def post_json(self, **_kwargs) -> dict:
            return {
                "choices": [{"finish_reason": "length", "message": {"content": '{"partial":'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.length", kind=CapabilityKind.MODEL,
            displayName="Length model", provider="openai_compatible", capabilities=["local-chat"],
        ),
        transport=_LengthTransport(),
    )

    with pytest.raises(ModelInvocationError) as captured:
        asyncio.run(runtime.invoke(ModelInvocationRequest(requestId="request-length", model="local-chat")))

    assert captured.value.code == "MODEL_OUTPUT_EXHAUSTED"
    assert captured.value.usage == {"prompt_tokens": 10, "completion_tokens": 20}
    assert captured.value.metadata["finishReason"] == "length"


def test_openai_compatible_runtime_projects_stream_deltas() -> None:
    """流式响应只向调用会话输出 delta 与完成事件，不写入持久化状态。"""
    class _StreamTransport:
        async def stream_json(self, **_kwargs):
            yield {"choices": [{"delta": {"content": "hel"}}]}
            yield {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]}

    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.stream",
            kind=CapabilityKind.MODEL,
            displayName="Stream model",
            provider="openai_compatible",
            capabilities=["local-chat"],
        ),
        transport=_StreamTransport(),
    )

    async def collect():
        return [event async for event in runtime.astream(ModelInvocationRequest(requestId="stream-1", model="local-chat"))]

    events = asyncio.run(collect())

    assert [(event.event_type, event.delta) for event in events] == [
        ("delta", "hel"),
        ("delta", "lo"),
        ("completed", ""),
    ]


def test_openai_compatible_runtime_projects_stream_tool_calls() -> None:
    """工具参数分片只作为当前会话事件返回。"""
    class _StreamTransport:
        async def stream_json(self, **_kwargs):
            yield {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "id": "call-1",
                            "function": {"name": "search", "arguments": '{"q":"x'},
                        }]
                    }
                }]
            }
            yield {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}

    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.tools",
            kind=CapabilityKind.MODEL,
            displayName="Tool stream model",
            provider="openai_compatible",
            capabilities=["local-chat"],
        ),
        transport=_StreamTransport(),
    )

    async def collect():
        request = ModelInvocationRequest(requestId="stream-tool-1", model="local-chat")
        return [event async for event in runtime.astream(request)]

    events = asyncio.run(collect())
    assert [
        (event.event_type, event.tool_call_id, event.tool_name, event.tool_arguments)
        for event in events
    ] == [
        ("tool_call", "call-1", "search", '{"q":"x'),
        ("completed", None, None, ""),
    ]
