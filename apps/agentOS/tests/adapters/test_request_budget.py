import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from adapters.model_adapter import StructuredGenerationError
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.openai_runtime import OpenAICompatibleRuntime
from contracts.capability import CapabilityKind, CapabilityManifest
from contracts.request_budget import ModelRequestBudget
from adapters.agent_tools import AgentToolSession
from contracts.tools import ToolDefinition, ToolResult


class Transport:
    def __init__(self):
        self.payloads = []

    async def post_json(self, **kwargs):
        self.payloads.append(kwargs["payload"])
        return {"choices": [{"finish_reason": "stop", "message": {"content": '{"answer":"ok"}'}}]}

    async def stream_json(self, **kwargs):
        self.payloads.append(kwargs["payload"])
        yield {"choices": [{"delta": {"content": '{"answer":"ok"}'}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}


def runtime(provider="deepseek"):
    transport = Transport()
    registry = ModelCompatibilityRegistry()
    registry.register(OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="test", displayName="test", kind=CapabilityKind.MODEL, provider=provider, capabilities=["mock"],
        metadata={"modelCapabilities": {"mock": {"features": {"tools": True}}}}), transport=transport))
    return RegisteredModelRuntime(registry=registry, provider=provider, model="mock"), transport


@pytest.mark.parametrize("large_part,streaming", [
    ("prompt", False), ("prompt", True), ("schema", False), ("schema", True), ("continuation", False),
])
def test_budget_checks_final_request_including_schema_and_continuation_before_transport(streaming, large_part):
    model, transport = runtime()
    kwargs = dict(prompt="small", schema={"type": "object"}, prompt_metadata={
        "requestBudget": {"totalTokens": 500, "outputReserveTokens": 100}})
    secret = "private material " * 1000
    if large_part == "prompt":
        kwargs["prompt"] = secret
    elif large_part == "schema":
        kwargs["schema"]["description"] = secret
    else:
        kwargs["continuation"] = [{"role": "assistant", "content": secret}, {"role": "user", "content": "Repair JSON"}]

    async def scenario():
        if streaming:
            return [event async for event in model.stream_generate_json(**kwargs, run_id="run")]
        return await model.generate_json(**kwargs)

    with pytest.raises(StructuredGenerationError) as failure:
        asyncio.run(scenario())
    assert failure.value.code == "MODEL_INPUT_BUDGET_EXCEEDED"
    diagnostics = failure.value.audit["requestDiagnostics"]["requestBudget"]
    assert diagnostics["status"] == "exceeded"
    assert diagnostics["estimatedTotalTokens"] == diagnostics["estimatedInputTokens"] + 100
    assert not transport.payloads
    assert "private material" not in json.dumps(failure.value.audit)


@pytest.mark.parametrize("large_part", ["definitions", "toolResult", "toolArguments"])
def test_tool_conversation_budget_includes_definitions_results_and_arguments(large_part):
    model, transport = runtime("test")
    tools = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]
    messages = [{"role": "user", "content": "small"}]
    if large_part == "definitions":
        tools[0]["function"]["description"] = "definition " * 2000
    elif large_part == "toolResult":
        messages.append({"role": "tool", "tool_call_id": "c1", "content": "result " * 3000})
    else:
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "argument " * 3000}}]})
    with pytest.raises(StructuredGenerationError) as failure:
        asyncio.run(model.generate_tool_turn(messages=messages, tools=tools, schema={"type": "object"},
                                            request_budget={"totalTokens": 500, "outputReserveTokens": 100}))
    assert failure.value.code == "MODEL_INPUT_BUDGET_EXCEEDED"
    assert failure.value.audit["requestDiagnostics"]["requestBudget"]["status"] == "exceeded"
    assert not transport.payloads


@pytest.mark.parametrize("budget", [None, {"totalTokens": 10000, "outputReserveTokens": 1000}])
def test_budget_is_internal_and_does_not_cap_output_or_change_wire_input(budget):
    model, transport = runtime()
    result = asyncio.run(model.generate_json(prompt="small", schema={"type": "object"},
        prompt_metadata={"requestBudget": budget} if budget else None))
    payload = transport.payloads[0]
    assert "requestBudget" not in payload and "request_budget" not in payload
    assert "max_tokens" not in payload
    assert result.request_diagnostics["requestBudget"]["status"] == ("withinBudget" if budget else "notConfigured")


@pytest.mark.parametrize("budget", [
    {"totalTokens": True, "outputReserveTokens": 1}, {"totalTokens": 100, "outputReserveTokens": 0},
    {"totalTokens": 100, "outputReserveTokens": 100}, {"totalTokens": 100, "outputReserveTokens": 101},
])
def test_invalid_or_unreserved_request_budgets_are_rejected(budget):
    with pytest.raises(ValidationError):
        ModelRequestBudget.model_validate(budget)


def test_tool_session_keeps_frozen_budget_after_one_large_tool_result():
    class ToolTransport(Transport):
        stream_json = None

        async def post_json(self, **kwargs):
            self.payloads.append(kwargs["payload"])
            return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]}}]}

    class Tools:
        calls = 0

        def list_tools(self):
            return [ToolDefinition(name="read", source="test", description="Read", parameters={"type": "object"})]

        async def execute(self, *args, **kwargs):
            self.calls += 1
            return ToolResult(name="read", source="test", status="succeeded", output={"text": "large source " * 1000})

    transport, tools = ToolTransport(), Tools()
    registry = ModelCompatibilityRegistry()
    registry.register(OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="test", displayName="test", kind=CapabilityKind.MODEL, provider="test", capabilities=["mock"],
        metadata={"modelCapabilities": {"mock": {"features": {"tools": True}}}}), transport=transport))
    ctx = SimpleNamespace(model_runtime=RegisteredModelRuntime(registry=registry, provider="test", model="mock"),
        tool_runtime=tools, step=SimpleNamespace(input={"contextPolicy": {"requestBudget": {
            "totalTokens": 1000, "outputReserveTokens": 100}}}, step_id="node", name="node"),
        run=SimpleNamespace(run_id="run"), attempt_id="attempt", commit_id="commit")
    with pytest.raises(StructuredGenerationError) as failure:
        asyncio.run(AgentToolSession(ctx).generate_json(prompt="read", schema={"type": "object"}))
    assert failure.value.code == "MODEL_INPUT_BUDGET_EXCEEDED"
    assert failure.value.audit["toolActionsExecuted"] == 1
    assert len(transport.payloads) == tools.calls == 1
