"""OpenAI 兼容模型运行时的合同测试。"""

from __future__ import annotations

import asyncio

from adapters.openai_runtime import OpenAICompatibleRuntime
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
