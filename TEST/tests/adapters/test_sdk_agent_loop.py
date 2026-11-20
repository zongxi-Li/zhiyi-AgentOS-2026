"""Offline contracts for the shared SDK loop and its ACG protocol boundary."""
from copy import deepcopy
import asyncio
import json

import pytest

from adapters.model.protocols import StructuredGenerationError
from adapters.agent.sdk_loop import run_agent_loop
from contracts.capability import ModelInvocationResponse


TOOLS = [{"type": "function", "function": {"name": "fs__read", "description": "Read.",
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
PREFIX = [{"role": "system", "content": "fixed policy"},
          {"role": "user", "content": "fixed mission"},
          {"role": "system", "content": "node schema"},
          {"role": "user", "content": "node input"}]


def call(name="fs__read", identifier="read_1", arguments='{"path":"a.py"}'):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": arguments}}


def response(*, calls=None, content=None, assistant=None, as_dict=False):
    value = ModelInvocationResponse(requestId="test-request", provider="offline", model="test-model",
        content=content or {}, toolCalls=calls or [], assistantMessage=assistant)
    return value.model_dump(by_alias=True, mode="json") if as_dict else value


@pytest.mark.asyncio
@pytest.mark.parametrize("as_dict", [False, True])
async def test_exact_transcript_reasoning_and_original_response(as_dict):
    prefix = deepcopy(PREFIX)
    raw_call = call()
    assistant = {"role": "assistant", "content": "Inspecting.", "reasoning_content": "private provider continuation",
                 "tool_calls": [raw_call]}
    final = response(content={"facts": ["confirmed"]}, as_dict=as_dict)
    observed, actions = [], []

    async def model(messages, turn):
        observed.append(messages)
        return response(calls=[raw_call], assistant=assistant, as_dict=as_dict) if turn == 0 else final

    async def execute(raw, turn, index):
        actions.append((raw, turn, index))
        return '{"status":"completed","content":"source"}'

    result = await run_agent_loop(messages=prefix, tools=TOOLS, invoke_model=model, execute_tool=execute)
    assert result is final
    assert prefix == PREFIX
    assert actions == [(raw_call, 0, 0)]
    assert observed[0] == PREFIX
    assert observed[1] == PREFIX + [assistant, {"role": "tool", "tool_call_id": "read_1",
                                              "content": '{"status":"completed","content":"source"}'}]
    assert "agentos_dispatch" not in json.dumps(observed)
    assert "agentos_completion" not in json.dumps(observed)


@pytest.mark.asyncio
async def test_inadequate_candidate_continues_same_runner_with_host_feedback():
    seen, actions = [], []
    final = response(content={"facts": ["actual source"]})

    async def model(messages, turn):
        seen.append(messages)
        return [response(content={"facts": []}), response(calls=[call()]), final][turn]

    async def execute(raw, turn, index):
        actions.append((turn, index))
        return {"status": "completed", "receiptRef": "receipt:test"}

    async def validate(value):
        return None if actions else "The required source has not been read. Read it before completion."

    assert await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
        execute_tool=execute, validate_completion=validate) is final
    assert len(seen) == 3
    assert seen[1][-1] == {"role": "user", "content": "The required source has not been read. Read it before completion."}
    assert all(messages[:len(PREFIX)] == PREFIX for messages in seen)
    assert actions == [(1, 0)]


@pytest.mark.asyncio
async def test_unknown_call_returns_structured_error_without_host_dispatch():
    seen = []

    async def model(messages, turn):
        seen.append(messages)
        return response(calls=[call(name="unregistered_write")]) if turn == 0 else response(content={"ok": True})

    async def forbidden(*args):
        pytest.fail("unknown tool must never reach host dispatch")

    await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=forbidden)
    error = json.loads(seen[1][-1]["content"])
    assert seen[1][-1]["tool_call_id"] == "read_1"
    assert error["status"] == "failed"
    assert error["error"]["code"] == "TOOL_ARGUMENTS_INVALID"


@pytest.mark.asyncio
async def test_multi_call_batch_is_not_rejected_by_legacy_action_limit():
    actions = []

    async def model(messages, turn):
        return response(calls=[call(identifier=f"read-{i}") for i in range(40)]) if turn == 0 else response(content={"done": True})

    async def execute(raw, turn, index):
        actions.append(raw["id"])
        return {"status": "completed", "index": index}

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
                                 execute_tool=execute, max_actions=1)
    assert result.content == {"done": True} and len(actions) == 40


@pytest.mark.asyncio
async def test_unchanged_completion_and_observations_stop_for_no_progress():
    turns = []

    async def model(messages, turn):
        turns.append(turn)
        return response(content={"facts": []})

    async def unused(*args):
        pytest.fail("no external action requested")

    with pytest.raises(StructuredGenerationError) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
            execute_tool=unused, validate_completion=lambda result: "Read required source.", max_feedback=1)
    assert caught.value.code == "AGENT_NO_PROGRESS"
    assert turns == [0, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [StructuredGenerationError("HANDS_OUTCOME_UNKNOWN", "unsettled"),
                                     asyncio.CancelledError("cancelled")])
async def test_tool_settlement_and_cancellation_preserve_original_error(failure):
    async def model(messages, turn):
        return response(calls=[call()])

    async def fail(*args):
        raise failure

    with pytest.raises(type(failure)) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=fail)
    assert caught.value is failure


@pytest.mark.asyncio
async def test_multi_call_order_and_raw_invalid_arguments_are_host_owned():
    seen, actions = [], []
    requested = [call(identifier="one", arguments="not json"), call(identifier="two")]

    async def model(messages, turn):
        seen.append(messages)
        return response(calls=requested) if turn == 0 else response(content={"ok": True})

    async def execute(raw, turn, index):
        actions.append((raw, turn, index))
        if index == 0:
            return {"error": {"code": "TOOL_ARGUMENTS_INVALID"}}
        return {"ok": True}

    await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute)
    assert actions == [(requested[0], 0, 0), (requested[1], 0, 1)]
    assert [item["tool_call_id"] for item in seen[1] if item["role"] == "tool"] == ["one", "two"]
    assert json.loads(seen[1][-2]["content"])["error"]["code"] == "TOOL_ARGUMENTS_INVALID"


@pytest.mark.asyncio
async def test_parallel_nodes_never_share_transcripts_or_action_state():
    transcripts = {}

    async def node(identity):
        async def model(messages, turn):
            await asyncio.sleep(0)
            transcripts.setdefault(identity, []).append(messages)
            return response(calls=[call(identifier=identity)]) if turn == 0 else response(content={"node": identity})

        async def execute(raw, turn, index):
            await asyncio.sleep(0)
            return identity

        return await run_agent_loop(messages=[{"role": "user", "content": identity}],
                                    tools=TOOLS, invoke_model=model, execute_tool=execute)

    results = await asyncio.gather(node("left"), node("right"))
    assert [value.content for value in results] == [{"node": "left"}, {"node": "right"}]
    assert all("right" not in json.dumps(m) for m in transcripts["left"])
    assert all("left" not in json.dumps(m) for m in transcripts["right"])


@pytest.mark.asyncio
async def test_host_wal_can_replay_identical_turns_without_repeating_effects():
    journal, receipts, effects = {}, {}, []

    async def invoke(messages, turn):
        identity = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        if turn in journal:
            old_identity, result = journal[turn]
            assert identity == old_identity
            return result
        result = response(calls=[call()]) if turn == 0 else response(content={"confirmed": True})
        journal[turn] = (identity, result)
        return result

    async def execute(raw, turn, index):
        key = (turn, index)
        if key not in receipts:
            effects.append(raw["id"])
            receipts[key] = '{"receiptRef":"confirmed-read"}'
        return receipts[key]

    options = dict(messages=PREFIX, tools=TOOLS, invoke_model=invoke, execute_tool=execute)
    first = await run_agent_loop(**options)
    second = await run_agent_loop(**options)
    assert first is second
    assert effects == ["read_1"]


@pytest.mark.asyncio
async def test_model_failure_preserves_host_error_without_an_internal_retry():
    failure = StructuredGenerationError("MODEL_STREAM_INCOMPLETE", "stream requires host handling")
    turns = []

    async def fail(messages, turn):
        turns.append(turn)
        raise failure

    async def forbidden(*args):
        pytest.fail("model failure must not execute tools")

    with pytest.raises(StructuredGenerationError) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=fail, execute_tool=forbidden)
    assert caught.value is failure
    assert turns == [0]


@pytest.mark.asyncio
@pytest.mark.parametrize("as_dict", [False, True])
async def test_json_repair_and_completion_feedback_have_independent_budgets(as_dict):
    candidate = ModelInvocationResponse(requestId="invalid", provider="offline", model="test-model",
        outputError="MODEL_OUTPUT_INVALID_JSON", assistantMessage={"role": "assistant", "content": '{"facts":'})
    if as_dict:
        candidate = candidate.model_dump(by_alias=True, mode="json")
    final = response(content={"facts": ["confirmed"]}, as_dict=as_dict)
    turns, validated = [], []

    async def model(messages, turn):
        turns.append(deepcopy(messages))
        return [candidate, response(content={"facts": []}, as_dict=as_dict), final][turn]

    def validate(value):
        validated.append(value)
        return "Supply the confirmed facts." if len(validated) == 1 else None

    async def unused(*args):
        pytest.fail("format repair must not execute external tools")

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=unused,
        validate_completion=validate, max_actions=1, max_feedback=1, max_format_repairs=1)
    assert result is final
    assert len(turns) == 3 and len(validated) == 2
    assert turns[1][-2] == {"role": "assistant", "content": '{"facts":'}
    assert "JSON" in turns[1][-1]["content"]
    assert turns[2][-1] == {"role": "user", "content": "Supply the confirmed facts."}


@pytest.mark.asyncio
@pytest.mark.parametrize("repairs", [0, 1])
async def test_identical_bad_json_stops_for_no_progress_independent_of_legacy_limit(repairs):
    turns = []

    async def model(messages, turn):
        turns.append(turn)
        return ModelInvocationResponse(requestId="invalid", provider="offline", model="test-model",
            outputError="MODEL_OUTPUT_INVALID_JSON", assistantMessage={"role": "assistant", "content": "bad JSON"})

    async def forbidden(*args):
        pytest.fail("unparseable final answers must not reach tools or completion validation")

    with pytest.raises(StructuredGenerationError) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=forbidden,
            validate_completion=forbidden, max_actions=1, max_feedback=0, max_format_repairs=repairs)
    assert caught.value.code == "AGENT_NO_PROGRESS"
    assert turns == [0, 1]


@pytest.mark.asyncio
async def test_unlimited_sdk_turns_and_actions_still_finish_on_accepted_result():
    actions = []

    async def model(messages, turn):
        return response(calls=[call(identifier=f"read-{turn}", arguments=json.dumps({"path": f"{turn}.py"}))]) if turn < 40 else response(content={"done": True})

    async def execute(raw, turn, index):
        actions.append(turn)
        return {"status": "completed", "text": str(turn)}

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
        execute_tool=execute, max_actions=1, max_feedback=0, max_format_repairs=0)
    assert result.content == {"done": True} and actions == list(range(40))


@pytest.mark.asyncio
async def test_distinct_json_corrections_and_completion_feedback_can_continue():
    turns = []

    async def model(messages, turn):
        turns.append(turn)
        if turn < 4:
            return ModelInvocationResponse(requestId="invalid", provider="offline", model="test-model",
                outputError="MODEL_OUTPUT_INVALID_JSON", assistantMessage={"role": "assistant", "content": f'{{"attempt":{turn}'})
        return response(content={"attempt": turn})

    async def unused(*args):
        pytest.fail("no tool action requested")

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=unused,
        validate_completion=lambda value: None if value.content["attempt"] == 8 else f"Missing fact {value.content['attempt']}.",
        max_feedback=0, max_format_repairs=0)
    assert result.content == {"attempt": 8} and turns == list(range(9))


def test_shared_sdk_entrypoints_use_true_none_even_for_legacy_finite_callers(monkeypatch):
    from adapters.agent.sdk_loop import run_sdk_agent, stream_sdk_agent

    captured = []

    async def run(*args, **kwargs):
        captured.append(kwargs["max_turns"])
        return "done"

    def streamed(*args, **kwargs):
        captured.append(kwargs["max_turns"])
        return "streaming"

    monkeypatch.setattr("adapters.agent.sdk_loop.Runner.run", run)
    monkeypatch.setattr("adapters.agent.sdk_loop.Runner.run_streamed", streamed)
    assert asyncio.run(run_sdk_agent(None, [], max_turns=1)) == "done"
    assert stream_sdk_agent(None, [], max_turns=1) == "streaming"
    assert captured == [None, None]


@pytest.mark.asyncio
async def test_external_cancellation_waits_for_host_tool_cleanup():
    started, released = asyncio.Event(), asyncio.Event()
    turns = []

    async def model(messages, turn):
        turns.append(turn)
        return response(calls=[call()])

    async def execute(raw, turn, index):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            # Releasing a host lease may itself require an asynchronous step.
            await asyncio.sleep(0)
            released.set()

    running = asyncio.create_task(run_agent_loop(messages=PREFIX, tools=TOOLS,
        invoke_model=model, execute_tool=execute))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert released.is_set()
    assert turns == [0]
