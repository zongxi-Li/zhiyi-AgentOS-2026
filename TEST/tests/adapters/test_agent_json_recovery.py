"""Offline node/session regressions for recoverable final JSON candidates.

The model's HTTP envelope and signed Hands service are simulated. Agent,
SDK Runner, tool WAL, permissions, model parsing and node commits remain real.
"""
from __future__ import annotations

import copy
import json

import pytest

from adapters.agent.tool_session import AgentToolSession
from adapters.model.guarded import GuardedModelRuntime
from adapters.model.protocols import StructuredGenerationError
from adapters.model.compatibility import ModelCompatibilityRegistry
from adapters.model.registered_runtime import RegisteredModelRuntime
from adapters.model.openai_runtime import OpenAICompatibleRuntime
from contracts.capability import CapabilityKind, CapabilityManifest
from TEST.tests.adapters.test_unified_tools import ANSWER, GeneralAgent, context_for, node, stack as _hands_stack


stack = _hands_stack
MALFORMED = '{"answer":"PRIVATE_MALFORMED_REPLY" "missing_comma":true}'
USAGE = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}


def reply(content, *, finish_reason="stop", **message_fields):
    return {"choices": [{"finish_reason": finish_reason, "message": {
        "role": "assistant", "content": content, **message_fields}}], "usage": dict(USAGE)}


def read_reply():
    return reply(None, finish_reason="tool_calls", reasoning_content="inspect actual evidence",
        tool_calls=[{"id": "read-once", "type": "function", "function": {
            "name": "fs__read", "arguments": '{"path":"note.txt"}'}}])


class RawModelHTTP:
    """Return exact wire replies rather than serializing malformed text away."""

    def __init__(self, replies, *, streamed=False):
        self.replies = iter(replies)
        self.requests = []
        if streamed:
            self.stream_json = self.stream

    async def post_json(self, *, payload, **kwargs):
        self.requests.append(copy.deepcopy(payload))
        value = next(self.replies)
        if isinstance(value, BaseException):
            raise value
        return copy.deepcopy(value)

    async def stream(self, *, payload, **kwargs):
        value = await self.post_json(payload=payload, **kwargs)
        choice = value["choices"][0]
        message = choice["message"]
        if message.get("tool_calls"):
            yield {"choices": [{"delta": {"reasoning_content": message["reasoning_content"]}}]}
            for index, call in enumerate(message["tool_calls"]):
                yield {"choices": [{"delta": {"tool_calls": [{"index": index, **call}]}}]}
        elif isinstance(message.get("content"), str):
            text = message["content"]
            midpoint = len(text) // 2
            yield {"choices": [{"delta": {"content": text[:midpoint]}}]}
            yield {"choices": [{"delta": {"content": text[midpoint:]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": choice["finish_reason"]}]}
        yield {"choices": [], "usage": value["usage"]}


def bind_raw_model(runner, replies, *, streamed=False):
    http = RawModelHTTP(replies, streamed=streamed)
    adapter = OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="json-recovery-model", kind=CapabilityKind.MODEL,
        displayName="offline", provider="test", capabilities=["mock"],
        metadata={"modelCapabilities": {"mock": {"features": {"tools": True}}}}), transport=http)
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    runner.model_runtime = GuardedModelRuntime(delegate=RegisteredModelRuntime(
        registry=registry, provider="test", model="mock"))
    return http


def forbid_plain_generation(monkeypatch, runner):
    async def forbidden(**kwargs):
        pytest.fail("tool-session format repair must not restart ordinary JSON generation")
    monkeypatch.setattr(runner.model_runtime, "generate_json", forbidden)


def assert_three_invocations(invocations):
    assert len(invocations) == 3
    assert [record["usage"] for record in invocations] == [USAGE, USAGE, USAGE]
    assert "PRIVATE_MALFORMED_REPLY" not in json.dumps(invocations)


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_node_repairs_final_json_in_place_without_repeating_completed_read(stack, monkeypatch, streamed):
    runner, state, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply(MALFORMED), reply('{"answer":"file evidence"}')],
                          streamed=streamed)
    forbid_plain_generation(monkeypatch, runner)

    result = await runner(step.step_id, state)

    assert runner.value_store.get_output(run_id=runner.run.run_id,
        output_ref=result["outputRef"]) == {"answer": "file evidence"}
    assert len(http.requests) == 3
    assert stack.service.execution_count == 1
    assert len(stack.service.requests) == 1
    messages = http.requests[-1]["messages"]
    assert any(message.get("role") == "assistant" and message.get("content") == MALFORMED
               for message in messages)
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "read-once"
    assert json.loads(tool_messages[0]["content"])["output"]["content"] == "file evidence"
    assert messages[-1]["role"] == "user"
    assert "json" in messages[-1]["content"].lower()
    assert_three_invocations(result["modelInvocations"])
    assert "PRIVATE_MALFORMED_REPLY" not in json.dumps(result)
    assert stack.runtime.resource_binder.coordinator.active_slots("hands") == 0

    await runner(step.step_id, state)
    assert len(http.requests) == 3 and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_private_wal_replays_malformed_candidate_and_repair_without_new_calls(stack):
    runner, _, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply(MALFORMED), reply('{"answer":"file evidence"}')])
    context = context_for(runner, step)
    first_session = AgentToolSession(context)
    first = await first_session.generate_json(prompt="read once and answer", schema=ANSWER)
    second_session = AgentToolSession(context)
    second = await second_session.generate_json(prompt="read once and answer", schema=ANSWER)

    assert first.data == second.data == {"answer": "file evidence"}
    assert len(http.requests) == 3
    assert len(stack.service.requests) == stack.service.execution_count == 1
    assert_three_invocations(first_session.invocations)
    assert_three_invocations(second_session.invocations)
    candidate = runner.value_store.get_tool_value(run_id=runner.run.run_id,
        key=f"{context.commit_id}:tools:1:model-turn")
    assert candidate["response"]["outputError"] == "MODEL_OUTPUT_INVALID_JSON"
    assert candidate["response"]["assistantMessage"]["content"] == MALFORMED


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_normal_stop_missing_root_close_commits_without_rewriting_completed_evidence(stack, streamed):
    runner, state, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply('{"answer":"file evidence"')], streamed=streamed)
    result = await runner(step.step_id, state)
    assert runner.value_store.get_output(run_id=runner.run.run_id, output_ref=result["outputRef"]) == {
        "answer": "file evidence"}
    assert len(http.requests) == 2 and stack.service.execution_count == 1


@pytest.mark.asyncio
async def test_cached_old_invalid_json_can_be_reinterpreted_without_mutating_wal_or_repeating_tools(stack, monkeypatch):
    runner, _, step, _ = node(stack, GeneralAgent())
    incomplete = '{"answer":"file evidence"'
    http = bind_raw_model(runner, [read_reply(), reply(incomplete), reply(incomplete)])
    context = context_for(runner, step)
    with monkeypatch.context() as legacy:
        legacy.setattr("adapters.model.json_output._complete_root", lambda _: None)
        with pytest.raises(StructuredGenerationError) as caught:
            await AgentToolSession(context).generate_json(prompt="read once and answer", schema=ANSWER)
        assert caught.value.code == "AGENT_NO_PROGRESS"
    key = f"{context.commit_id}:tools:1:model-turn"
    original = runner.value_store.get_tool_value(run_id=runner.run.run_id, key=key)
    assert original["response"]["outputError"] == "MODEL_OUTPUT_INVALID_JSON"
    replay = await AgentToolSession(context).generate_json(prompt="read once and answer", schema=ANSWER)
    assert replay.data == {"answer": "file evidence"}
    assert len(http.requests) == 3 and stack.service.execution_count == 1
    assert runner.value_store.get_tool_value(run_id=runner.run.run_id, key=key) == original


@pytest.mark.asyncio
async def test_root_completion_still_requires_original_output_contract(stack):
    runner, state, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply('{"answer":[]'), reply('{"answer":"file evidence"}')])
    result = await runner(step.step_id, state)
    assert runner.value_store.get_output(run_id=runner.run.run_id, output_ref=result["outputRef"]) == {
        "answer": "file evidence"}
    assert len(http.requests) == 3 and stack.service.execution_count == 1
    assert "output contract" in http.requests[-1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_cached_root_recovery_preserves_historical_feedback_when_contract_still_rejects(stack, monkeypatch):
    runner, _, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply('{"answer":[]'), reply('{"answer":"file evidence"}')])
    context = context_for(runner, step)
    with monkeypatch.context() as legacy:
        legacy.setattr("adapters.model.json_output._complete_root", lambda _: None)
        first = await AgentToolSession(context).generate_json(prompt="read once and answer", schema=ANSWER)
    second = await AgentToolSession(context).generate_json(prompt="read once and answer", schema=ANSWER)
    assert first.data == second.data == {"answer": "file evidence"}
    assert len(http.requests) == 3 and stack.service.execution_count == 1


@pytest.mark.asyncio
async def test_repeated_bad_json_stops_on_unchanged_state_without_plain_generation_fallback(stack, monkeypatch):
    runner, state, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply(MALFORMED), reply(MALFORMED)])
    forbid_plain_generation(monkeypatch, runner)

    with pytest.raises(StructuredGenerationError) as caught:
        await runner(step.step_id, state)

    assert caught.value.code == "AGENT_NO_PROGRESS"
    assert len(http.requests) == 3
    assert len(stack.service.requests) == stack.service.execution_count == 1
    assert_three_invocations(caught.value.audit["modelInvocations"])
    assert "PRIVATE_MALFORMED_REPLY" not in json.dumps(caught.value.audit)
    assert stack.runtime.resource_binder.coordinator.active_slots("hands") == 0
    assert not [commit for commit in runner.value_store.list_node_commits(run_id=runner.run.run_id)
                if commit.get("stage") == "committed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("wire", "code"), [
    ({"choices": [], "usage": dict(USAGE)}, "MODEL_RESPONSE_INVALID"),
    (reply(None, refusal="The provider refused this response."), "MODEL_RESPONSE_REFUSED"),
    (reply(None, finish_reason="content_filter"), "MODEL_RESPONSE_REFUSED"),
    (reply(MALFORMED, finish_reason="length"), "MODEL_OUTPUT_EXHAUSTED"),
    (reply(None, finish_reason="tool_calls", tool_calls=[{"type": "function"}]), "MODEL_TOOL_CALL_INVALID"),
])
async def test_non_json_failures_do_not_enter_format_repair_or_repeat_tools(stack, monkeypatch, wire, code):
    runner, state, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), wire])
    forbid_plain_generation(monkeypatch, runner)

    with pytest.raises(StructuredGenerationError) as caught:
        await runner(step.step_id, state)

    assert caught.value.code == code
    assert len(http.requests) == 2
    assert len(stack.service.requests) == stack.service.execution_count == 1
    assert stack.runtime.resource_binder.coordinator.active_slots("hands") == 0
