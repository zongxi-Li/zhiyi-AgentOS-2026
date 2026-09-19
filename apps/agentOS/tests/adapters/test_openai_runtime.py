"""OpenAI 兼容模型运行时的合同测试。"""

from __future__ import annotations

import asyncio
import logging

import pytest

from adapters.http_transport import HttpTransportError
from adapters.openai_runtime import ModelInvocationError, OpenAICompatibleRuntime
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
)
from adapters.model.native_prompt import NativeCapabilityPromptBuilder
from support.acg.models import build_default_capability_catalog


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


def test_openai_runtime_accepts_json_wrapped_in_a_markdown_fence() -> None:
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.fenced", kind=CapabilityKind.MODEL,
            displayName="Fenced model", provider="openai_compatible", capabilities=["local-chat"],
        ),
        transport=_JsonTransport(),
    )

    assert runtime._content_object("```json\n{\"answer\":\"ok\"}\n```") == {"answer": "ok"}


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


def test_openai_compatible_runtime_reports_safe_incomplete_stream_diagnostics() -> None:
    class _IncompleteStreamTransport:
        async def stream_json(self, **_kwargs):
            yield {"choices": [{"delta": {"content": "partial"}}]}

    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.incomplete",
            kind=CapabilityKind.MODEL,
            displayName="Incomplete stream model",
            provider="glm",
            capabilities=["local-chat"],
        ),
        transport=_IncompleteStreamTransport(),
    )

    async def collect():
        return [event async for event in runtime.astream(
            ModelInvocationRequest(requestId="stream-incomplete", model="local-chat")
        )]

    with pytest.raises(ModelInvocationError) as captured:
        asyncio.run(collect())

    assert captured.value.code == "MODEL_STREAM_INCOMPLETE"
    diagnostics = captured.value.metadata["streamDiagnostics"]
    assert diagnostics == {
        "streamStarted": True,
        "firstTokenObserved": True,
        "outputDeltaObserved": True,
        "deltaCount": 1,
        "completionObserved": False,
        "streamTerminationReason": "eof_before_completion",
        "elapsedMs": diagnostics["elapsedMs"],
    }
    assert "partial" not in repr(diagnostics)


def test_openai_compatible_runtime_logs_only_stream_usage_shape(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _UsageStreamTransport:
        async def stream_json(self, **_kwargs):
            yield {
                "id": "chatcmpl-test",
                "choices": [{"delta": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}],
            }
            yield {
                "id": "chatcmpl-test",
                "choices": [],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                },
            }

    monkeypatch.setenv("AGENTOS_PROVIDER_USAGE_DIAGNOSTICS", "1")
    caplog.set_level(logging.INFO)
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.stream-usage",
            kind=CapabilityKind.MODEL,
            displayName="Stream usage model",
            provider="glm",
            capabilities=["glm-test"],
        ),
        transport=_UsageStreamTransport(),
    )

    async def collect():
        return [
            event
            async for event in runtime.astream(
                ModelInvocationRequest(requestId="stream-usage", model="glm-test")
            )
        ]

    events = asyncio.run(collect())
    completed = next(event for event in events if event.event_type == "completed")
    assert completed.metadata["finishReason"] == "stop"
    assert completed.metadata["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    assert completed.metadata["streamDiagnostics"]["completionObserved"] is True
    diagnostic = "\n".join(record.getMessage() for record in caplog.records)
    assert "provider_usage_diagnostic" in diagnostic
    assert "response_mode=stream" in diagnostic
    assert "usage_present=True" in diagnostic
    assert "usage_type=dict" in diagnostic
    assert "usage_keys=['completion_tokens', 'prompt_tokens', 'total_tokens']" in diagnostic
    assert "prompt=" not in diagnostic
    assert "response正文" not in diagnostic
    assert "12" not in diagnostic


def test_glm_runtime_uses_supported_json_mode_and_keeps_reasoning_private() -> None:
    class _GlmStreamTransport:
        def __init__(self) -> None:
            self.payload = None

        async def stream_json(self, **kwargs):
            self.payload = kwargs["payload"]
            yield {"choices": [{"delta": {"reasoning_content": "private chain"}}]}
            yield {"choices": [{"delta": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}]}

    transport = _GlmStreamTransport()
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.glm", kind=CapabilityKind.MODEL,
            displayName="GLM", provider="glm", capabilities=["glm-test"],
        ),
        transport=transport,
    )

    async def collect():
        request = ModelInvocationRequest(
            requestId="glm-stream", model="glm-test",
            responseSchema={"type": "object", "properties": {"answer": {"type": "string"}}},
        )
        return [event async for event in runtime.astream(request)]

    events = asyncio.run(collect())
    assert transport.payload["response_format"] == {"type": "json_object"}
    assert transport.payload["thinking"] == {"type": "disabled"}
    assert transport.payload["messages"][0]["role"] == "system"
    assert '"answer":{"type":"string"}' in transport.payload["messages"][0]["content"]
    assert transport.payload["messages"][1:] == []
    assert [event.event_type for event in events] == ["activity", "delta", "completed"]
    assert "private chain" not in repr(events)


def test_glm_runtime_honors_reasoning_effort_and_enables_thinking() -> None:
    """显式 reasoning_effort 必须原样送达 GLM 并打开思考，而不是被静默关闭。"""
    transport = _JsonTransport()
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.glm", kind=CapabilityKind.MODEL,
            displayName="GLM", provider="glm", capabilities=["glm-test"],
        ),
        transport=transport,
    )

    asyncio.run(runtime.invoke(ModelInvocationRequest(
        requestId="glm-effort", model="glm-test",
        responseSchema={"type": "object", "properties": {"answer": {"type": "string"}}},
        options={"reasoning_effort": "max", "max_tokens": 4096},
    )))

    assert transport.payload["reasoning_effort"] == "max"
    assert transport.payload["thinking"] == {"type": "enabled"}
    assert transport.payload["response_format"] == {"type": "json_object"}
    assert transport.payload["max_tokens"] == 4096
    assert transport.payload["messages"][0]["role"] == "system"


@pytest.mark.parametrize("requested,expected", [("medium", "high"), ("low", "high"), ("max", "max")])
def test_deepseek_runtime_enables_thinking_and_clamps_effort(requested: str, expected: str) -> None:
    """DeepSeek 档位走 thinking enabled + effort 外发；low/medium 收敛到官方 high。"""
    transport = _JsonTransport()
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.deepseek", kind=CapabilityKind.MODEL,
            displayName="DeepSeek", provider="deepseek", capabilities=["deepseek-flash"],
        ),
        transport=transport,
    )

    asyncio.run(runtime.invoke(ModelInvocationRequest(
        requestId="deepseek-effort", model="deepseek-flash",
        responseSchema={"type": "object", "properties": {"answer": {"type": "string"}}},
        options={"reasoning_effort": requested},
    )))

    assert transport.payload["reasoning_effort"] == expected
    assert transport.payload["thinking"] == {"type": "enabled"}
    assert transport.payload["response_format"] == {"type": "json_object"}


def test_deepseek_runtime_without_effort_disables_thinking() -> None:
    """无显式档位时关思考直出，防私有推理与 JSON 输出争夺预算（与 GLM 同语义）。"""
    transport = _JsonTransport()
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.deepseek", kind=CapabilityKind.MODEL,
            displayName="DeepSeek", provider="deepseek", capabilities=["deepseek-flash"],
        ),
        transport=transport,
    )

    asyncio.run(runtime.invoke(ModelInvocationRequest(
        requestId="deepseek-plain", model="deepseek-flash",
        responseSchema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )))

    assert transport.payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in transport.payload
    assert transport.payload["response_format"] == {"type": "json_object"}
    assert '"answer":{"type":"string"}' in transport.payload["messages"][0]["content"]


def test_glm_schema_instruction_follows_agentos_system_authority() -> None:
    transport = _JsonTransport()
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.glm", kind=CapabilityKind.MODEL,
            displayName="GLM", provider="glm", capabilities=["glm-test"],
        ), transport=transport,
    )
    asyncio.run(runtime.invoke(ModelInvocationRequest(
        requestId="glm-authority", model="glm-test",
        messages=[
            {"role": "system", "content": "AgentOS Kernel and planner policy"},
            {"role": "user", "content": "runtime data"},
        ], responseSchema={"type": "object"},
    )))
    assert [item["role"] for item in transport.payload["messages"]] == ["system", "user"]
    assert transport.payload["messages"][0]["content"].startswith("AgentOS Kernel and planner policy")
    assert "TRANSPORT OUTPUT CONTRACT" in transport.payload["messages"][0]["content"]


@pytest.mark.parametrize("provider", ["openai_compatible", "glm", "zhipu"])
def test_provider_preserves_complete_executor_authority_and_user_request(provider: str) -> None:
    descriptor = build_default_capability_catalog().get("cost_analysis")
    envelope = NativeCapabilityPromptBuilder().build_envelope(
        capability_descriptor=descriptor, step_goal="Calculate cost",
        acceptance_criteria=["Inputs and units are explicit"], source_refs=[],
        logical_role="task", task_title="Mission", task_input={}, context_data={},
        source_data={}, evidence_refs=[], output_schema=descriptor.output_contract,
    )
    transport = _JsonTransport()
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId=f"model.{provider}", kind=CapabilityKind.MODEL,
            displayName=provider, provider=provider, capabilities=["test-model"],
        ), transport=transport,
    )
    asyncio.run(runtime.invoke(ModelInvocationRequest(
        requestId=f"authority-{provider}", model="test-model",
        messages=[
            {"role": "system", "content": envelope.system_prompt},
            {"role": "user", "content": envelope.user_prompt},
        ], responseSchema={"type": "object"},
    )))
    assert [item["role"] for item in transport.payload["messages"]] == ["system", "user"]
    system = transport.payload["messages"][0]["content"]
    assert system.startswith("You are an execution component inside Zhiyi AgentOS")
    assert "You are an execution agent" in system
    assert '"capabilityId":"cost_analysis"' in system
    assert transport.payload["messages"][-1]["content"] == envelope.user_prompt


def test_non_glm_runtime_strips_reasoning_effort_option() -> None:
    """非思考供应商端点不外发 reasoning_effort，保持既有 wire format。"""
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

    asyncio.run(runtime.invoke(ModelInvocationRequest(
        requestId="effort-strip", model="local-chat",
        responseSchema={"type": "object", "properties": {"answer": {"type": "string"}}},
        options={"reasoning_effort": "high"},
    )))

    assert "reasoning_effort" not in transport.payload
    assert transport.payload["response_format"]["type"] == "json_schema"


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
