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
from adapters.request_diagnostics import context_usage, request_diagnostics, resolve_request_budget
from contracts.capability import ModelCapabilityEnvelope
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


def test_working_budget_uses_exact_route_allowance_and_only_existing_worksets_can_split():
    capability = ModelCapabilityEnvelope(provider='test', model='mock', contextWindowTokens=10000, maxOutputTokens=2000)
    ordinary = resolve_request_budget(None, capability, 2000)
    split = resolve_request_budget(None, capability, 2000, workset=True)
    assert ordinary.total_tokens == 10000 and ordinary.output_reserve_tokens == 2000
    assert ordinary.working_set_trigger_tokens == 6800
    assert ordinary.working_set_target_tokens == 5200
    payload = {'messages': [{'role': 'user', 'content': 'evidence-' * 2600}]}
    original = json.dumps(payload)
    observed = request_diagnostics(payload, None, ordinary)
    assert observed['requestBudget']['status'] == 'withinBudget'
    assert observed['workingSet']['status'] == 'exceeded'
    OpenAICompatibleRuntime._check_request_budget(observed)
    with pytest.raises(Exception) as failure:
        OpenAICompatibleRuntime._check_request_budget(request_diagnostics(payload, None, split))
    assert failure.value.code == 'MODEL_INPUT_BUDGET_EXCEEDED'
    assert json.dumps(payload) == original  # evidence, failures and approvals are not rewritten


def test_unknown_route_has_no_invented_budget_and_missing_usage_is_not_measured_zero():
    assert resolve_request_budget(None, ModelCapabilityEnvelope.unknown(provider='test', model='mock'), None) is None
    unknown = context_usage({}, {})
    assert unknown['measurement'] == 'unknown' and unknown['inputTokens'] is None
    estimated = context_usage({'requestBudget': {'estimatedInputTokens': 123, 'estimator': 'estimate', 'totalTokens': 1000}}, {})
    assert estimated['measurement'] == 'estimate' and estimated['inputTokens'] == 123
    # This is the latest request, never an accumulated Runner/Run total.
    assert context_usage({}, {'prompt_tokens': 7, 'total_tokens': 99999}, 100)['inputTokens'] == 7
    assert context_usage({}, {'prompt_tokens': True})['measurement'] == 'unknown'


@pytest.mark.parametrize('trigger,target', [(100, 100), (100, 101), (901, 50), (True, 10)])
def test_invalid_working_budgets_fail_before_model_calls(trigger, target):
    with pytest.raises(ValidationError):
        ModelRequestBudget(totalTokens=1000, outputReserveTokens=100,
                           workingSetTriggerTokens=trigger, workingSetTargetTokens=target)


def test_model_route_budget_applies_to_streaming_planning_nodes_and_tool_turns():
    transport = Transport()
    registry = ModelCompatibilityRegistry()
    registry.register(OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId='test', displayName='test', kind=CapabilityKind.MODEL, provider='test', capabilities=['mock'],
        metadata={'modelCapabilities': {'mock': {'contextWindowTokens': 10000, 'maxOutputTokens': 2000,
                    'features': {'tools': True}}}}), transport=transport))
    model = RegisteredModelRuntime(registry=registry, provider='test', model='mock')
    result = asyncio.run(model.generate_json(prompt='small', schema={'type': 'object'}))
    assert result.request_diagnostics['requestBudget']['totalTokens'] == 10000
    assert result.request_diagnostics['workingSet']['mode'] == 'observe'
    assert transport.payloads[-1]['max_tokens'] == 2000
    async def stream():
        return [event async for event in model.stream_generate_json(prompt='small', schema={'type': 'object'}, run_id='run')]
    completed = asyncio.run(stream())[-1]
    assert completed.payload['requestDiagnostics']['requestBudget']['totalTokens'] == 10000
    assert completed.payload['capability']['contextWindowTokens'] == 10000
