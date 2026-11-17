"""OpenAI 兼容模型运行时的合同测试。"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from adapters.http_transport import HttpTransportError
from adapters.openai_runtime import ModelInvocationError, OpenAICompatibleRuntime, decode_json_object
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
)
from adapters.model.native_prompt import NativeCapabilityPromptBuilder
from support.acg.models import build_default_capability_catalog


def test_markdown_literal_control_whitespace_is_decoded_without_regenerating_content():
    text = '{"deliverable":{"content":"# Title\nA\tB\r\nEnd"}}'
    assert decode_json_object(text) == {"deliverable": {"content": "# Title\nA\tB\r\nEnd"}}


@pytest.mark.parametrize("text", [
    '{"content":"unfinished\n}', '{"content":"text\n"',
    '{"content":"text\n\u0000"}', '{"content":"text\n","count":}',
])
def test_json_whitespace_tolerance_does_not_invent_structure_or_accept_control_bytes(text):
    with pytest.raises(ModelInvocationError):
        decode_json_object(text)


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


def test_deepseek_field_repair_keeps_original_wire_prefix_and_current_schema():
    runtime = OpenAICompatibleRuntime(
        manifest=CapabilityManifest(capabilityId="ds", kind=CapabilityKind.MODEL,
            displayName="DS", provider="deepseek", capabilities=["deepseek-flash"]),
        transport=_JsonTransport(),
    )
    original_schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    patch_schema = {"type": "object", "properties": {"patch": {"type": "object"}}}
    original_messages = [{"role": "system", "content": "stable authority"},
                         {"role": "user", "content": "stable source materials"}]
    original = runtime._build_payload(ModelInvocationRequest(requestId="original", model="deepseek-flash",
        messages=original_messages, responseSchema=original_schema), "deepseek-flash")
    repaired = runtime._build_payload(ModelInvocationRequest(requestId="repair", model="deepseek-flash",
        messages=original_messages + [{"role": "assistant", "content": "prior generated data"},
                                      {"role": "user", "content": "bounded runtime operation"}],
        responseSchema=patch_schema, prefixResponseSchema=original_schema), "deepseek-flash")
    assert repaired["messages"][:2] == original["messages"]
    assert repaired["messages"][-1]["role"] == "user"
    assert repaired["messages"][-2]["role"] == "system"
    assert '"patch"' in repaired["messages"][-2]["content"]
    assert original_messages[0]["content"] == "stable authority"
    assert "prefixResponseSchema" not in repaired
    assert repaired["response_format"] == {"type": "json_object"}


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
    assert response.metadata["finishReason"] == "stop"
    assert response.metadata["requestDiagnostics"]["messageCount"] == 1
    assert response.metadata["requestDiagnostics"]["totalCharacters"] == len("只返回 JSON")
    assert transport.idempotency_key == "commit:run-1:step-1:0"


@pytest.mark.parametrize("provider", ["glm", "zhipu", "deepseek", "openai_compatible"])
@pytest.mark.parametrize("streaming", [False, True])
def test_tool_turn_allows_native_actions_before_validating_final_json(provider, streaming):
    call = {"id": "list-root", "type": "function", "function": {
        "name": "fs__list", "arguments": '{"path":"."}'}}
    tools = [{"type": "function", "function": {"name": "fs__list", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]

    class Transport:
        def __init__(self):
            self.payloads = []
            self.turns = iter([
                {"finish_reason": "tool_calls", "message": {
                    "content": "Inspecting the workspace.", "tool_calls": [call]}},
                {"finish_reason": "stop", "message": {"content": '{"answer":"observed"}'}},
                {"finish_reason": "stop", "message": {"content": '{"answer":'}},
            ])

        async def post_json(self, *, payload, **kwargs):
            self.payloads.append(payload)
            return {"choices": [next(self.turns)]}

        async def stream_json(self, *, payload, **kwargs):
            self.payloads.append(payload)
            turn = next(self.turns)
            yield {"choices": [{"delta": turn["message"], "finish_reason": turn["finish_reason"]}]}

    transport = Transport()
    runtime = OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="model.actions", kind=CapabilityKind.MODEL, displayName="Actions",
        provider=provider, capabilities=["actions-model"]), transport=transport)
    messages = [{"role": "system", "content": "shared authority"},
                {"role": "user", "content": "shared mission"},
                {"role": "system", "content": "current node policy"},
                {"role": "user", "content": "Inspect the authorized workspace before answering."}]
    request = ModelInvocationRequest(requestId="action", model="actions-model", messages=messages,
        responseSchema={"type": "object", "properties": {"answer": {"type": "string"}}},
        schemaMessageIndex=2, options={"tools": tools, "reasoning_effort": "medium"})

    async def invoke(current):
        if not streaming:
            return await runtime.invoke(current)
        events = [event async for event in runtime.astream(current)]
        return next(event.response for event in events if event.event_type == "completed")

    async def exercise():
        action = await invoke(request)
        continuation = request.model_copy(update={"messages": [*messages, action.assistant_message,
            {"role": "tool", "tool_call_id": "list-root", "content": '{"entries":[]}'}]})
        return action, await invoke(continuation), await invoke(continuation)

    action, final, malformed = asyncio.run(exercise())
    assert action.tool_calls == [call] and action.content == {}
    assert action.assistant_message["content"] == "Inspecting the workspace."
    assert final.content == {"answer": "observed"} and not final.tool_calls
    assert malformed.output_error == "MODEL_OUTPUT_INVALID_JSON"
    assert malformed.assistant_message["content"] == '{"answer":'
    for payload in transport.payloads:
        assert "response_format" not in payload and "tool_choice" not in payload
        assert payload["tools"] == tools
        assert payload["messages"][:2] == messages[:2]
        assert "This schema applies only to the final assistant text" in payload["messages"][2]["content"]
        assert '"answer":{"type":"string"}' in payload["messages"][2]["content"]
        if provider in {"glm", "zhipu", "deepseek"}:
            assert payload["thinking"] == {"type": "enabled"}
            assert payload["reasoning_effort"] == ("high" if provider == "deepseek" else "medium")
        else:
            assert "reasoning_effort" not in payload and "thinking" not in payload
    assert messages[2]["content"] == "current node policy"


@pytest.mark.parametrize("provider", ["glm", "openai_compatible"])
def test_empty_tool_catalog_keeps_provider_json_output_mode(provider):
    runtime = OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="model.no-actions", kind=CapabilityKind.MODEL, displayName="No actions",
        provider=provider, capabilities=["test"]), transport=_JsonTransport())
    payload = runtime._build_payload(ModelInvocationRequest(requestId="no-actions", model="test",
        responseSchema={"type": "object"}, options={"tools": []}), "test")
    assert payload["response_format"]["type"] == ("json_object" if provider == "glm" else "json_schema")


@pytest.mark.parametrize("provider", ["glm", "openai_compatible"])
def test_tool_turn_preserves_prefix_schema_and_bounds_continuation_schema_to_final_text(provider):
    runtime = OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="model.continuation", kind=CapabilityKind.MODEL, displayName="Continuation",
        provider=provider, capabilities=["test"]), transport=_JsonTransport())
    original = {"type": "object", "properties": {"answer": {"type": "string"}}}
    patch = {"type": "object", "properties": {"patch": {"type": "object"}}}
    payload = runtime._build_payload(ModelInvocationRequest(requestId="repair", model="test",
        messages=[{"role": "system", "content": "stable authority"},
                  {"role": "user", "content": "current operation"}],
        responseSchema=patch, prefixResponseSchema=original,
        options=_boundary_request(tools=True).options), "test")
    assert "response_format" not in payload
    assert '"answer"' in payload["messages"][0]["content"]
    assert '"patch"' not in payload["messages"][0]["content"]
    assert '"patch"' in payload["messages"][-2]["content"]
    assert "native tool calls remain available before completion" in payload["messages"][-2]["content"]


@pytest.mark.parametrize("provider", ["glm", "openai_compatible"])
@pytest.mark.parametrize("schema_index", [0, 5])
def test_tool_schema_never_enters_user_message_or_out_of_range_target(provider, schema_index):
    runtime = OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="model.invalid-schema-target", kind=CapabilityKind.MODEL,
        displayName="Invalid schema target", provider=provider, capabilities=["test"]),
        transport=_JsonTransport())
    with pytest.raises(ModelInvocationError, match="schema target"):
        runtime._build_payload(ModelInvocationRequest(requestId="bad-target", model="test",
            messages=[{"role": "user", "content": "untrusted data"}],
            responseSchema={"type": "object"}, schemaMessageIndex=schema_index,
            options=_boundary_request(tools=True).options), "test")


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


def _response_boundary_runtime():
    return OpenAICompatibleRuntime(
        manifest=CapabilityManifest(
            capabilityId="model.compat.boundary", kind=CapabilityKind.MODEL,
            displayName="Boundary model", provider="openai_compatible", capabilities=["local-chat"],
        ),
        transport=_JsonTransport(),
    )


def _boundary_request(*, tools=False):
    return ModelInvocationRequest(
        requestId="boundary", model="local-chat",
        options={"tools": [{"type": "function", "function": {"name": "read", "parameters": {}}}]} if tools else {},
    )


def test_final_json_error_has_specific_code_and_safe_diagnostics(caplog):
    raw = '{"answer":"PRIVATE-MODEL-CONTENT" "other":1}'
    with pytest.raises(ModelInvocationError) as caught:
        _response_boundary_runtime()._parse_response(
            request=_boundary_request(), model="local-chat", response={
                "choices": [{"finish_reason": "stop", "message": {"content": raw}}],
                "usage": {"completion_tokens": 11},
            },
        )
    assert caught.value.code == "MODEL_OUTPUT_INVALID_JSON"
    assert caught.value.usage == {"completion_tokens": 11}
    assert caught.value.metadata["finishReason"] == "stop"
    assert caught.value.metadata["responseDiagnostics"]["reason"] == "Expecting ',' delimiter"
    assert "PRIVATE-MODEL-CONTENT" not in str(caught.value) + json.dumps(caught.value.metadata) + caplog.text


def test_tool_turn_retains_malformed_final_candidate_only_in_private_transcript(caplog):
    raw = '{"answer":"PRIVATE-MODEL-CONTENT" "other":1}'
    candidate = _response_boundary_runtime()._parse_response(
        request=_boundary_request(tools=True), model="local-chat", response={
            "choices": [{"finish_reason": "stop", "message": {
                "content": raw, "reasoning_content": "PRIVATE-REASONING",
            }}],
            "usage": {"completion_tokens": 11},
        },
    )
    assert candidate.content == {}
    assert candidate.output_error == "MODEL_OUTPUT_INVALID_JSON"
    assert candidate.tool_calls == []
    assert candidate.assistant_message == {
        "role": "assistant", "content": raw, "reasoning_content": "PRIVATE-REASONING",
    }
    assert candidate.usage == {"completion_tokens": 11}
    assert candidate.metadata["responseDiagnostics"]["length"] == len(raw)
    safe = json.dumps(candidate.metadata) + caplog.text
    assert "PRIVATE-MODEL-CONTENT" not in safe
    assert "PRIVATE-REASONING" not in safe


@pytest.mark.parametrize("body", [None, [], {}, {"choices": []}, {"choices": [{"message": None}]}])
def test_protocol_errors_never_become_repairable_final_candidates(body):
    with pytest.raises(ModelInvocationError) as caught:
        _response_boundary_runtime()._parse_response(
            request=_boundary_request(tools=True), model="local-chat", response=body,
        )
    assert caught.value.code == "MODEL_RESPONSE_INVALID"


@pytest.mark.parametrize("finish", ["length", "max_tokens", "max_output_tokens"])
def test_tool_turn_truncation_never_becomes_json_repair_candidate(finish):
    with pytest.raises(ModelInvocationError) as caught:
        _response_boundary_runtime()._parse_response(
            request=_boundary_request(tools=True), model="local-chat", response={
                "choices": [{"finish_reason": finish, "message": {"content": '{"answer":'}}],
            },
        )
    assert caught.value.code == "MODEL_OUTPUT_EXHAUSTED"


def test_invalid_tool_call_never_becomes_json_repair_candidate():
    with pytest.raises(ModelInvocationError) as caught:
        _response_boundary_runtime()._parse_response(
            request=_boundary_request(tools=True), model="local-chat", response={
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "content": "", "tool_calls": [{"id": "missing-function"}],
                }}],
            },
        )
    assert caught.value.code == "MODEL_TOOL_CALL_INVALID"


@pytest.mark.parametrize("calls", [{}, "", 0, False])
def test_falsy_non_list_tool_calls_never_become_json_repair_candidates(calls):
    with pytest.raises(ModelInvocationError) as caught:
        _response_boundary_runtime()._parse_response(
            request=_boundary_request(tools=True), model="local-chat", response={
                "choices": [{"finish_reason": "stop", "message": {
                    "content": '{"answer":', "tool_calls": calls,
                }}],
                "usage": {"completion_tokens": 2},
            },
        )
    assert caught.value.code == "MODEL_TOOL_CALL_INVALID"
    assert caught.value.usage == {"completion_tokens": 2}


@pytest.mark.parametrize("message", [{"content": ""}, {"content": "", "tool_calls": None},
                                     {"content": "", "tool_calls": []}])
def test_tool_call_finish_without_actual_calls_is_a_protocol_error(message):
    with pytest.raises(ModelInvocationError) as caught:
        _response_boundary_runtime()._parse_response(
            request=_boundary_request(tools=True), model="local-chat", response={
                "choices": [{"finish_reason": "tool_calls", "message": message}],
            },
        )
    assert caught.value.code == "MODEL_TOOL_CALL_INVALID"


def test_empty_tool_call_list_with_normal_finish_keeps_valid_content():
    value = _response_boundary_runtime()._parse_response(
        request=_boundary_request(tools=True), model="local-chat", response={
            "choices": [{"finish_reason": "stop", "message": {
                "content": '{"answer":"ok"}', "tool_calls": [],
            }}],
        },
    )
    assert value.content == {"answer": "ok"}
    assert value.output_error is None
    assert value.tool_calls == []


@pytest.mark.parametrize("finish,refusal", [("content_filter", None), ("stop", "PRIVATE-REFUSAL")])
def test_provider_refusal_never_becomes_json_repair_candidate(finish, refusal):
    with pytest.raises(ModelInvocationError) as caught:
        _response_boundary_runtime()._parse_response(
            request=_boundary_request(tools=True), model="local-chat", response={
                "choices": [{"finish_reason": finish, "message": {"content": None, "refusal": refusal}}],
                "usage": {"completion_tokens": 2},
            },
        )
    assert caught.value.code == "MODEL_RESPONSE_REFUSED"
    assert caught.value.usage == {"completion_tokens": 2}
    assert "PRIVATE-REFUSAL" not in str(caught.value) + json.dumps(caught.value.metadata)


def test_streamed_tool_turn_retains_invalid_candidate_usage_and_safe_diagnostics():
    class _StreamTransport:
        async def stream_json(self, **_kwargs):
            yield {"choices": [{"delta": {"content": '{"answer":'}, "finish_reason": "stop"}]}
            yield {"choices": [], "usage": {"completion_tokens": 3}}

    runtime = _response_boundary_runtime()
    runtime._transport = _StreamTransport()

    async def collect():
        return [event async for event in runtime.astream(_boundary_request(tools=True))]

    events = asyncio.run(collect())
    final = events[-1]
    assert final.event_type == "completed"
    assert final.response.output_error == "MODEL_OUTPUT_INVALID_JSON"
    assert final.response.assistant_message["content"] == '{"answer":'
    assert final.response.usage == {"completion_tokens": 3}
    assert final.response.metadata["responseDiagnostics"]["length"] == 10
    assert final.response.metadata["requestDiagnostics"]["messageCount"] >= 0


@pytest.mark.parametrize("calls", [{}, "", 0, False, [None], ["invalid"]])
def test_invalid_streamed_tool_fragments_are_never_silently_discarded(calls):
    class _StreamTransport:
        async def stream_json(self, **_kwargs):
            yield {"choices": [{"delta": {"tool_calls": calls}}]}
            yield {"choices": [{"delta": {"content": '{"answer":'}, "finish_reason": "stop"}]}

    runtime = _response_boundary_runtime()
    runtime._transport = _StreamTransport()

    async def collect():
        return [event async for event in runtime.astream(_boundary_request(tools=True))]

    with pytest.raises(ModelInvocationError) as caught:
        asyncio.run(collect())
    assert caught.value.code == "MODEL_TOOL_CALL_INVALID"


def test_streamed_tool_finish_without_calls_is_not_a_json_repair_candidate():
    class _StreamTransport:
        async def stream_json(self, **_kwargs):
            yield {"choices": [{"delta": {"tool_calls": []}, "finish_reason": "tool_calls"}]}

    runtime = _response_boundary_runtime()
    runtime._transport = _StreamTransport()

    async def collect():
        return [event async for event in runtime.astream(_boundary_request(tools=True))]

    with pytest.raises(ModelInvocationError) as caught:
        asyncio.run(collect())
    assert caught.value.code == "MODEL_TOOL_CALL_INVALID"


@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("finish,refusal", [("content_filter", None), ("stop", "PRIVATE-REFUSAL")])
@pytest.mark.parametrize("usage_with_finish", [False, True])
def test_streamed_provider_refusal_is_not_a_json_error(tools, finish, refusal, usage_with_finish):
    class _StreamTransport:
        async def stream_json(self, **_kwargs):
            yield {"choices": [{"delta": {"refusal": refusal}, "finish_reason": finish}],
                **({"usage": {"completion_tokens": 2}} if usage_with_finish else {})}
            yield {"choices": [], "usage": {"completion_tokens": 2}}

    runtime = _response_boundary_runtime()
    runtime._transport = _StreamTransport()

    async def collect():
        return [event async for event in runtime.astream(_boundary_request(tools=tools))]

    with pytest.raises(ModelInvocationError) as caught:
        asyncio.run(collect())
    assert caught.value.code == "MODEL_RESPONSE_REFUSED"
    assert caught.value.usage == ({"completion_tokens": 2} if usage_with_finish else {})
    assert "PRIVATE-REFUSAL" not in str(caught.value) + json.dumps(caught.value.metadata)


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


@pytest.mark.parametrize("requested,expected", [("medium", "high"), ("low", "low"), ("high", "high"), ("max", "max")])
def test_deepseek_runtime_preserves_supported_effort_and_enables_thinking(requested: str, expected: str) -> None:
    """Preserve low/high/max and normalize the legacy medium alias to high."""
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
    assert system.startswith("General operating rules:")
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
