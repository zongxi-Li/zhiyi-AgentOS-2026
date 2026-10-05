from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from openai.resources.chat.completions import Completions

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.prompt_runtime import planner_prompt_metadata
from app.execution.wiring import GatewayIntentLLM, RegisteredPlannerLLM, bind_registered_planner_llm
from app.llm.gateway import LLMGateway
from app.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from contracts.capability import (
    CapabilityKind, CapabilityManifest, ModelCapabilityEnvelope, ModelInvocationResponse,
)


@pytest.mark.parametrize("mode", ["json", "text"])
def test_gateway_translates_system_message_without_leaking_internal_arguments(mode):
    captured = {}

    def create(**kwargs):
        # Unlike a permissive mock, the real SDK signature rejects internal kwargs.
        inspect.signature(Completions.create).bind(None, **kwargs)
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"ok":true}'), finish_reason="stop",
            )], id="test-response", usage=None,
        )

    provider = object.__new__(OpenAICompatibleProvider)
    provider.model = "deepseek-flash"
    provider.base_url = "https://api.deepseek.com/v1"
    provider.default_thinking_mode = "disabled"
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    gateway = LLMGateway(provider=provider)
    kwargs = dict(system_prompt="Trusted planner policy", prompt_metadata={"preset": "planner"}, timeout_seconds=45)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    result = (gateway.generate_json("User task", schema, **kwargs) if mode == "json"
              else gateway.generate_text("User task", **kwargs))

    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][0]["content"].startswith("Trusted planner policy")
    assert captured["messages"][1] == {"role": "user", "content": "User task"}
    assert captured["timeout"] == 45
    assert result["prompt_metadata"] == {"preset": "planner"}
    if mode == "json":
        assert "JSON Schema:" in captured["messages"][0]["content"]
        assert captured["response_format"] == {"type": "json_object"}
        assert result["data"] == {"ok": True}


class _ModelAdapter:
    manifest = CapabilityManifest(
        capabilityId="model.test.planner", kind=CapabilityKind.MODEL,
        displayName="Planner model", provider="test-provider", capabilities=["test-model"], version="1",
    )

    def __init__(self):
        self.requests = []

    def is_available(self):
        return True

    def describe_model(self, model):
        return ModelCapabilityEnvelope.unknown(provider="test-provider", model=model, version="1")

    async def invoke(self, request):
        self.requests.append(request)
        return ModelInvocationResponse(
            requestId=request.request_id, content={"ok": True},
            provider="test-provider", model=request.model, usage={"completion_tokens": 3},
        )

    async def astream(self, request):
        self.requests.append(request)
        yield SimpleNamespace(event_type="delta", delta='{"ok":true}', metadata={})
        yield SimpleNamespace(event_type="completed", delta="", metadata={
            "finishReason": "stop", "usage": {"completion_tokens": 3},
        })


def test_planner_uses_registered_model_for_sync_and_real_stream_calls(monkeypatch):
    monkeypatch.setattr("app.llm.gateway.get_llm_gateway", lambda: pytest.fail("Planner bypassed model registry"))
    registry = ModelCompatibilityRegistry()
    adapter = _ModelAdapter()
    registry.register(adapter)
    runtime = SimpleNamespace(
        model_registry=registry, default_model_binding={"provider": "test-provider", "model": "test-model", "version": "1"},
        _intent_llm=GatewayIntentLLM(),
    )
    runtime.set_intent_llm = lambda llm: setattr(runtime, "_intent_llm", llm)
    assert bind_registered_planner_llm(runtime)
    planner = runtime._intent_llm
    assert isinstance(planner, RegisteredPlannerLLM)
    kwargs = dict(system_prompt="Trusted planner policy", prompt_metadata=planner_prompt_metadata())
    result = planner.generate_json("User task", {"type": "object"}, max_tokens=64, **kwargs)
    assert result["data"] == {"ok": True}
    assert result["usage"] == {"completion_tokens": 3}

    async def consume():
        return [event async for event in planner.stream_generate_json(
            prompt="User task", schema={"type": "object"}, run_id="test-run", **kwargs,
        )]

    events = asyncio.run(consume())
    assert "model.output.delta" in [event.event_type for event in events]
    assert events[-1].event_type == "model.completed"
    assert events[-1].payload["data"] == {"ok": True}
    assert events[-1].payload["streaming"] is True
    assert len(adapter.requests) == 2
    assert adapter.requests[0].options == {"max_tokens": 64}
    for request in adapter.requests:
        assert request.messages[0] == {"role": "system", "content": "Trusted planner policy"}
        assert "system_prompt" not in request.options
        assert "prompt_metadata" not in request.options
