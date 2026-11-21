"""Live instruction delivery preserves admitted model/tool history on recovery."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adapters.execution_guidance import SessionExecutionGuidance
from adapters.model_adapter import StructuredGenerationError
from adapters.prompt_runtime import canonical_hash
from adapters.sdk_agent_loop import run_agent_loop
from components.executor.value_store import InMemoryExecutionValueStore
from contracts.capability import ModelInvocationResponse
from contracts.execution_guidance import ExecutionGuidance


PREFIX = [{"role": "system", "content": "fixed policy"}, {"role": "user", "content": "fixed Step"}]
TOOLS = [{"type": "function", "function": {"name": "fs__read", "description": "read",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]


def guidance(text="Deliver the available evidence and report uncertainty", *, owner="run"):
    return ExecutionGuidance(runId=owner, stepId="report", graphVersion=2, userInputs=({
        "sourceRunId": owner, "operationId": "input:" + text, "content": text,
        "submittedAt": "2026-11-19T10:00:00Z"},)).model_dump(by_alias=True, mode="json")


def context(reader):
    return SimpleNamespace(run=SimpleNamespace(run_id="run"),
        step=SimpleNamespace(step_id="report", name="Report"), commit_id="commit", attempt_id="attempt",
        execution_guidance_reader=reader)


def response(*, calls=None):
    return ModelInvocationResponse(requestId="response", provider="test", model="test",
        content={} if calls else {"report": "confirmed findings; remaining scope unknown"}, toolCalls=calls or [])


def tool(identifier):
    return {"id": identifier, "type": "function", "function": {"name": "fs__read", "arguments": '{"path":"a"}'}}


def updates(messages):
    result = []
    for message in messages:
        if message.get("role") != "user":
            continue
        try:
            value = json.loads(message["content"])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("requestType") == "ExecutionGuidanceUpdate":
            result.append(value["guidance"])
    return result


@pytest.mark.asyncio
async def test_live_update_is_delivered_after_complete_tool_batch_then_model_can_finish():
    state = {"guidance": None}
    session = SessionExecutionGuidance(context(lambda: state["guidance"]), InMemoryExecutionValueStore(), "commit")
    seen, actions = [], []

    async def model(messages, turn):
        seen.append(deepcopy(messages))
        return response(calls=[tool("a"), tool("b")]) if turn == 0 else response()

    async def execute(call, turn, index):
        actions.append(call["id"])
        state["guidance"] = guidance()
        return '{"status":"completed","data":"saved evidence"}'

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
        execute_tool=execute, model_input_feedback=session.before_model)
    assert result.content["report"] and actions == ["a", "b"]
    assert not updates(seen[0]) and updates(seen[1]) == [session._validate(guidance())]
    assert [m["role"] for m in seen[1][-3:]] == ["tool", "tool", "user"]
    assert PREFIX == [{"role": "system", "content": "fixed policy"}, {"role": "user", "content": "fixed Step"}]


@pytest.mark.asyncio
async def test_no_duplicate_delivery_without_changed_guidance():
    session = SessionExecutionGuidance(context(lambda: guidance()), InMemoryExecutionValueStore(), "commit")
    first = await session.before_model(PREFIX, 0)
    messages = PREFIX + [{"role": "user", "content": first}]
    assert first and await session.before_model(messages, 1) is None
    assert await session.before_model(messages, 2) is None


@pytest.mark.asyncio
async def test_legacy_cached_turns_remain_identical_before_first_new_delivery():
    store = InMemoryExecutionValueStore()
    for turn in (0, 1):
        store.put_tool_value(run_id="run", step_id="report", key=f"commit:tools:{turn}:model-turn",
            payload={"requestHash": canonical_hash(PREFIX)})
    reader_calls = []
    def read():
        reader_calls.append(True)
        return guidance()
    session = SessionExecutionGuidance(context(read), store, "commit")
    assert await session.before_model(PREFIX, 0) is None
    assert await session.before_model(PREFIX, 1) is None
    assert reader_calls == []
    assert await session.before_model(PREFIX, 2)
    assert reader_calls == [True]


@pytest.mark.asyncio
async def test_model_failure_replays_frozen_delivery_and_confirmed_tool_without_repeating_effect():
    store = InMemoryExecutionValueStore()
    state = {"guidance": guidance("Investigate"), "fail": True}
    requests, actions = [], []

    async def model(messages, turn):
        requests.append((turn, deepcopy(messages)))
        if turn == 1 and state["fail"]:
            raise RuntimeError("transport failed after guidance was sealed")
        key = f"commit:tools:{turn}:model-turn"
        cached = store.get_tool_value(run_id="run", key=key)
        if cached:
            assert cached["requestHash"] == canonical_hash(messages)
            return ModelInvocationResponse.model_validate(cached["response"])
        value = response(calls=[tool("read")]) if turn == 0 else response()
        store.put_tool_value(run_id="run", step_id="report", key=key,
            payload={"requestHash": canonical_hash(messages), "response": value.model_dump(by_alias=True, mode="json")})
        return value

    async def execute(call, turn, index):
        cached = store.get_tool_value(run_id="run", key="confirmed-read")
        if not cached:
            actions.append(call["id"])
            store.put_tool_value(run_id="run", step_id="report", key="confirmed-read", payload={"result": "evidence"})
        state["guidance"] = guidance("Deliver now")
        return '{"status":"completed","data":"evidence"}'

    async def run():
        delivery = SessionExecutionGuidance(context(lambda: state["guidance"]), store, "commit")
        return await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
            execute_tool=execute, model_input_feedback=delivery.before_model)

    with pytest.raises(RuntimeError):
        await run()
    before = deepcopy(requests)
    state.update(fail=False, guidance=guidance("Newer instruction after failure"))
    assert (await run()).content["report"]
    assert actions == ["read"]
    assert requests[0:2] == before and requests[2:4] == before


@pytest.mark.asyncio
async def test_receipt_cannot_be_replayed_against_changed_transcript():
    store = InMemoryExecutionValueStore()
    first = SessionExecutionGuidance(context(lambda: guidance()), store, "commit")
    await first.before_model(PREFIX, 0)
    second = SessionExecutionGuidance(context(lambda: guidance()), store, "commit")
    with pytest.raises(StructuredGenerationError, match="frozen delivery"):
        await second.before_model(PREFIX + [{"role": "user", "content": "tampered"}], 0)


@pytest.mark.asyncio
async def test_other_run_guidance_is_rejected_before_it_enters_model_history():
    session = SessionExecutionGuidance(context(lambda: guidance(owner="other")), InMemoryExecutionValueStore(), "commit")
    with pytest.raises(StructuredGenerationError):
        await session.before_model(PREFIX, 0)


@pytest.mark.asyncio
async def test_sdk_cancellation_during_guidance_prevents_model_request():
    async def feedback(messages, turn):
        raise asyncio.CancelledError("cancelled before delivery")
    async def forbidden(*args):
        pytest.fail("no model or tool may be invoked after cancellation")
    with pytest.raises(asyncio.CancelledError):
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=forbidden,
            execute_tool=forbidden, model_input_feedback=feedback)


@pytest.mark.asyncio
async def test_instruction_arriving_during_final_generation_is_delivered_before_acceptance():
    state = {"guidance": guidance("Investigate")}
    delivery = SessionExecutionGuidance(context(lambda: state["guidance"]), InMemoryExecutionValueStore(), "commit")
    seen = []

    async def model(messages, turn):
        seen.append(updates(messages))
        if turn == 0:
            state["guidance"] = guidance("Deliver existing evidence now")
        return response()

    async def forbidden(*args):
        pytest.fail("updated guidance needs no repeated tool action")

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
        execute_tool=forbidden, validate_completion=delivery.completion_feedback,
        model_input_feedback=delivery.before_model)
    assert result.content["report"] and len(seen) == 2
    assert [item["userInputs"][0]["content"] for item in seen[-1]] == [
        "Investigate", "Deliver existing evidence now"]


@pytest.mark.asyncio
async def test_empty_guidance_is_frozen_before_model_failure_and_newer_input_waits_for_next_boundary():
    store = InMemoryExecutionValueStore()
    first = SessionExecutionGuidance(context(lambda: None), store, "commit")
    assert await first.before_model(PREFIX, 0) is None
    recovered = SessionExecutionGuidance(context(lambda: guidance()), store, "commit")
    assert await recovered.before_model(PREFIX, 0) is None
    assert await recovered.completion_feedback(response())
    assert await recovered.before_model(PREFIX, 1)


@pytest.mark.asyncio
async def test_completion_deferral_replays_even_when_current_inbox_changes_after_crash():
    store = InMemoryExecutionValueStore()
    state = {"guidance": guidance("Investigate")}
    first = SessionExecutionGuidance(context(lambda: state["guidance"]), store, "commit")
    message = await first.before_model(PREFIX, 0)
    state["guidance"] = guidance("Deliver now")
    feedback = await first.completion_feedback(response())
    store.put_tool_value(run_id="run", step_id="report", key="commit:tools:0:model-turn",
        payload={"requestHash": canonical_hash(PREFIX + [{"role": "user", "content": message}])})
    state["guidance"] = guidance("A later update")
    recovered = SessionExecutionGuidance(context(lambda: state["guidance"]), store, "commit")
    assert await recovered.before_model(PREFIX, 0) == message
    assert await recovered.completion_feedback(response()) == feedback
    assert await recovered.before_model(PREFIX, 1)


@pytest.mark.asyncio
async def test_rendered_guidance_replays_original_policy_after_policy_code_changes(monkeypatch):
    from adapters import execution_guidance as module

    store = InMemoryExecutionValueStore()
    first = SessionExecutionGuidance(context(lambda: guidance()), store, "commit")
    message = await first.before_model(PREFIX, 0)
    monkeypatch.setattr(module, "EXECUTION_GUIDANCE_POLICY", "Updated policy for new deliveries")
    recovered = SessionExecutionGuidance(context(lambda: guidance()), store, "commit")
    assert await recovered.before_model(PREFIX, 0) == message
