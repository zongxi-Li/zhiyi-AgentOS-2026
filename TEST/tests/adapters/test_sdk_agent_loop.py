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
    tool_message = next(item for item in seen[1] if item["role"] == "tool")
    error = json.loads(tool_message["content"])
    assert tool_message["tool_call_id"] == "read_1"
    assert error["status"] == "failed"
    assert error["error"]["code"] == "TOOL_ARGUMENTS_INVALID"


@pytest.mark.asyncio
async def test_authorized_multi_call_batch_completes_without_count_limit():
    actions = []

    async def model(messages, turn):
        return response(calls=[call(identifier=f"read-{i}") for i in range(40)]) if turn == 0 else response(content={"done": True})

    async def execute(raw, turn, index):
        actions.append(raw["id"])
        return {"status": "completed", "index": index}

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model,
                                 execute_tool=execute)
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
            execute_tool=unused, validate_completion=lambda result: "Read required source.")
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
    first_tool = next(item for item in seen[1] if item["role"] == "tool")
    assert json.loads(first_tool["content"])["error"]["code"] == "TOOL_ARGUMENTS_INVALID"


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
async def test_json_repair_and_completion_feedback_continue_independently(as_dict):
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
        validate_completion=validate)
    assert result is final
    assert len(turns) == 3 and len(validated) == 2
    assert turns[1][-2] == {"role": "assistant", "content": '{"facts":'}
    assert "JSON" in turns[1][-1]["content"]
    assert turns[2][-1] == {"role": "user", "content": "Supply the confirmed facts."}


@pytest.mark.asyncio
async def test_identical_bad_json_stops_for_no_progress():
    turns = []

    async def model(messages, turn):
        turns.append(turn)
        return ModelInvocationResponse(requestId="invalid", provider="offline", model="test-model",
            outputError="MODEL_OUTPUT_INVALID_JSON", assistantMessage={"role": "assistant", "content": "bad JSON"})

    async def forbidden(*args):
        pytest.fail("unparseable final answers must not reach tools or completion validation")

    with pytest.raises(StructuredGenerationError) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=forbidden,
            validate_completion=forbidden)
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
        execute_tool=execute)
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
        validate_completion=lambda value: None if value.content["attempt"] == 8 else f"Missing fact {value.content['attempt']}.")
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


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_same_failed_tool_state_gets_guidance_then_stops_despite_fresh_call_ids(unknown):
    seen, actions = [], []

    async def model(messages, turn):
        seen.append(messages)
        return response(calls=[call(name="unknown" if unknown else "fs__read", identifier=f"call-{turn}",
            arguments='{"path": "a.py"}' if turn == 0 else '{ "path":"a.py" }')])

    async def execute(raw, turn, index):
        assert not unknown
        actions.append(turn)
        return {"status": "failed", "error": {"code": "TOOL_ARGUMENTS_INVALID", "requestId": str(turn)}}

    with pytest.raises(StructuredGenerationError) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute)
    assert caught.value.code == "AGENT_NO_PROGRESS"
    assert len(seen) == 2 and actions == ([] if unknown else [0, 1])
    assert seen[1][-2]["role"] == "tool"
    assert seen[1][-1]["role"] == "user"
    assert "existing output contract" in seen[1][-1]["content"]
    assert "unresolved scope" in seen[1][-1]["content"]


@pytest.mark.asyncio
async def test_corrected_actions_and_legitimate_repeated_success_have_no_count_limit():
    seen, actions = [], []

    async def model(messages, turn):
        seen.append(messages)
        if turn == 80:
            return response(content={"done": True})
        path = f"corrected-{turn}.py" if turn < 40 else "source.py"
        return response(calls=[call(identifier=f"call-{turn}", arguments=json.dumps({"path": path}))])

    async def execute(raw, turn, index):
        actions.append(turn)
        if turn < 40:
            return {"status": "failed", "error": {"code": "TOOL_ARGUMENTS_INVALID"}}
        return {"status": "completed", "output": {"text": "same confirmed content"}, "receiptRef": str(turn)}

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute)
    assert result.content == {"done": True}
    assert actions == list(range(80)) and len(seen) == 81


@pytest.mark.asyncio
async def test_new_successful_evidence_permits_reconsidering_an_earlier_failed_action():
    seen = []

    async def model(messages, turn):
        seen.append(messages)
        if turn == 3:
            return response(content={"facts": ["verified source"], "gaps": ["unreadable a.py"]})
        return response(calls=[call(identifier=str(turn), arguments=json.dumps({"path": "b.py" if turn == 1 else "a.py"}))])

    async def execute(raw, turn, index):
        return ({"status": "completed", "output": {"text": "verified source"}} if turn == 1 else
                {"status": "failed", "error": {"code": "TOOL_EXECUTION_FAILED"}})

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute)
    assert result.content["gaps"] == ["unreadable a.py"]
    assert len(seen) == 4


@pytest.mark.asyncio
async def test_fresh_receipt_metadata_without_new_business_evidence_does_not_reset_failure_state():
    turns = []

    async def model(messages, turn):
        turns.append(turn)
        return response(calls=[call(identifier=str(turn), arguments=json.dumps({"path": "a.py" if turn % 2 else "b.py"}))])

    async def execute(raw, turn, index):
        if turn % 2:
            return {"status": "failed", "error": {"code": "TOOL_EXECUTION_FAILED"}}
        return {"status": "completed", "output": {"text": "same evidence"}, "receiptRef": f"receipt-{turn}"}

    with pytest.raises(StructuredGenerationError) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute)
    assert caught.value.code == "AGENT_NO_PROGRESS"
    assert turns == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_exact_legacy_failed_tool_replay_suppresses_new_guidance_until_first_new_turn():
    seen, allowed = [], []

    async def model(messages, turn):
        seen.append(messages)
        return response(calls=[call(identifier=f"call-{turn}")]) if turn < 4 else response(content={"gaps": ["a.py"]})

    async def execute(raw, turn, index):
        return {"status": "failed", "error": {"code": "TOOL_EXECUTION_FAILED"}}

    def feedback_allowed(messages, turn):
        allowed.append((turn, deepcopy(messages)))
        return turn >= 4

    result = await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute,
        feedback_allowed=feedback_allowed)
    assert result.content == {"gaps": ["a.py"]}
    assert [turn for turn, _ in allowed] == [1, 2, 3, 4]
    for turn in (1, 2, 3):
        assert seen[turn] == allowed[turn - 1][1]
        assert seen[turn][-1]["role"] == "tool"
    assert seen[4][-1]["role"] == "user"


@pytest.mark.asyncio
@pytest.mark.parametrize("continue_after_failure", [True, False])
async def test_sdk_cannot_swallow_host_failure_and_resume_model_or_return_success(monkeypatch, continue_after_failure):
    failure = StructuredGenerationError("HANDS_OUTCOME_UNKNOWN", "must settle")
    calls = []

    async def model(messages, turn):
        calls.append(turn)
        return response(calls=[call()])

    async def execute(*args):
        raise failure

    async def swallowing_runner(agent, *args, **kwargs):
        dispatch = (await agent.model.get_response()).output[0]
        try:
            await agent.tools[0].on_invoke_tool(None, dispatch.arguments)
        except StructuredGenerationError as caught:
            assert caught is failure
        if continue_after_failure:
            with pytest.raises(StructuredGenerationError) as caught:
                await agent.model.get_response()
            assert caught.value is failure
            with pytest.raises(StructuredGenerationError) as caught:
                await agent.tools[0].on_invoke_tool(None, dispatch.arguments)
            assert caught.value is failure
        return "SDK swallowed failure"

    monkeypatch.setattr("adapters.agent.sdk_loop.Runner.run", swallowing_runner)
    with pytest.raises(StructuredGenerationError) as caught:
        await run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute)
    assert caught.value is failure
    assert calls == [0]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["model", "tool"])
async def test_pending_owner_cancellation_blocks_sdk_callbacks_even_after_sdk_swallows_it(monkeypatch, boundary):
    model_calls, tool_calls = [], []

    async def model(messages, turn):
        model_calls.append(turn)
        return response(calls=[call()])

    async def execute(*args):
        tool_calls.append(True)
        return {"status": "completed", "output": {"text": "source"}}

    async def swallowing_runner(agent, *args, **kwargs):
        dispatch = (await agent.model.get_response()).output[0] if boundary == "tool" else None
        asyncio.current_task().cancel("host cancellation")
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        async def late_child():
            if boundary == "model":
                return await agent.model.get_response()
            return await agent.tools[0].on_invoke_tool(None, dispatch.arguments)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(late_child())
        return "SDK swallowed cancellation"

    monkeypatch.setattr("adapters.agent.sdk_loop.Runner.run", swallowing_runner)
    running = asyncio.create_task(run_agent_loop(messages=PREFIX, tools=TOOLS, invoke_model=model, execute_tool=execute))
    with pytest.raises(asyncio.CancelledError):
        await running
    assert model_calls == ([0] if boundary == "tool" else [])
    assert tool_calls == []
