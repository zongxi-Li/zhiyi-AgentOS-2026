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
        if callable(value):
            value = value(payload)
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
async def test_large_workspace_receipt_is_paged_by_the_node_and_its_next_attempt(stack, monkeypatch):
    from components.communicator.reader import CommunicationReader

    agent = GeneralAgent()
    runner, state, step, _ = node(stack, agent)
    body = "private source line\n" * 220_000
    stack.service.files[("one", "note.txt")] = body
    step.input["contextPolicy"] = {"requestBudget": {"totalTokens": 16000, "outputReserveTokens": 500}}
    observed_refs = []

    def page_call(reference):
        return reply(None, finish_reason="tool_calls", tool_calls=[{
            "id": "page", "type": "function", "function": {"name": "context__read_page",
                "arguments": json.dumps({"producerStepId": reference, "fields": ["content"]})}}])

    def read_page_after_tool(payload):
        response = json.loads(next(message["content"] for message in payload["messages"] if message["role"] == "tool"))
        output = response["output"]
        assert output["scope"] == "evidence_reference" and "content" not in output
        observed_refs.append(output["receiptRef"])
        return page_call(observed_refs[0])

    def finish_after_page(payload):
        response = json.loads([message["content"] for message in payload["messages"] if message["role"] == "tool"][-1])
        output = response["output"]
        assert output["data"]["content"].startswith("private source line")
        assert output["estimatedTokens"] <= 1024 and output["hasMore"]
        assert output["evidenceRefs"] == observed_refs
        return reply('{"answer":"scoped finding"}')

    initial = bind_raw_model(runner, [read_reply(), read_page_after_tool, finish_after_page])
    result = await runner(step.step_id, state)
    reference = observed_refs[0]
    receipt = runner.value_store.get_output(run_id=runner.run.run_id, output_ref=reference)
    assert receipt["output"]["text"] == body
    assert stack.service.execution_count == 1
    assert len(initial.requests) == 3
    assert len(json.dumps(initial.requests[-1])) < 40_000
    assert result["evidenceRefs"] == [reference]
    assert result["communicationReads"][-1]["outputRef"] == reference
    assert "private source line" not in json.dumps(result)

    def start_recovery(payload):
        assert reference in json.dumps(payload)
        assert "private source line" not in json.dumps(payload)
        return page_call(reference)

    recovered_model = bind_raw_model(runner, [start_recovery, finish_after_page])
    context = context_for(runner, step)
    context.commit_id, context.attempt_id = "recovery-commit", "recovery-attempt"
    context.capability_descriptor = runner.capability_descriptors[step.capability]
    context.tool_runtime = runner.tool_runtime.bind_context(context, lambda: None)
    context.communication_reader = CommunicationReader(broker=runner.communication_broker, run_id=runner.run.run_id,
        consumer_step_id=step.step_id, output_refs={}, max_tokens=None)
    record = next(item for item in result["toolCalls"] if item.get("receiptRef") == reference)
    history = [{"kind": "previous_attempt_tool_observation", "receiptRef": reference,
                "record": record, "result": {"path": "note.txt", "content": body}}]
    context.run.execution_state.update(retryEvidenceContextVersion=1,
        readOnlyRetryProofs={"earlier-operation": {"stepId": step.step_id}})

    async def collect(_context):
        return history

    monkeypatch.setattr(context.tool_runtime, "previous_attempt_observations", collect)
    recovered = await agent.run(context)
    assert recovered.output == {"answer": "scoped finding"}
    assert stack.service.execution_count == 1
    assert len(recovered_model.requests) == 2


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
@pytest.mark.parametrize(("wire", "recovery"), [
    ('{"answer":"file evidence"', "root_close_added"),
    ('{"answer":"file evidence"}}', "duplicate_root_close_removed"),
])
async def test_normal_stop_root_normalization_commits_without_rewriting_completed_evidence(stack, streamed, wire, recovery):
    runner, state, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply(wire)], streamed=streamed)
    result = await runner(step.step_id, state)
    assert runner.value_store.get_output(run_id=runner.run.run_id, output_ref=result["outputRef"]) == {
        "answer": "file evidence"}
    assert len(http.requests) == 2 and stack.service.execution_count == 1
    final = runner.value_store.get_tool_value(run_id=runner.run.run_id,
        key=f"{result['commitId']}:tools:1:model-turn")
    assert final["response"]["metadata"]["jsonRecovery"] == {
        "type": recovery, "rootCompleted": recovery == "root_close_added"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("incomplete", "normalizer"), [
    ('{"answer":"file evidence"', "_complete_root"),
    ('{"answer":"file evidence"}}', "_remove_duplicate_root_close"),
])
async def test_cached_old_invalid_json_can_be_reinterpreted_without_mutating_wal_or_repeating_tools(
        stack, monkeypatch, incomplete, normalizer):
    runner, _, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply(incomplete), reply(incomplete)])
    context = context_for(runner, step)
    with monkeypatch.context() as legacy:
        legacy.setattr("adapters.model.json_output." + normalizer, lambda _: None)
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
@pytest.mark.parametrize("wire", ['{"answer":[]', '{"answer":[]}}'])
async def test_root_normalization_still_requires_original_output_contract(stack, wire):
    runner, state, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply(wire), reply('{"answer":"file evidence"}')])
    result = await runner(step.step_id, state)
    assert runner.value_store.get_output(run_id=runner.run.run_id, output_ref=result["outputRef"]) == {
        "answer": "file evidence"}
    assert len(http.requests) == 3 and stack.service.execution_count == 1
    assert "output contract" in http.requests[-1]["messages"][-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("wire", "normalizer"), [
    ('{"answer":[]', "_complete_root"), ('{"answer":[]}}', "_remove_duplicate_root_close"),
])
async def test_cached_root_recovery_preserves_historical_feedback_when_contract_still_rejects(
        stack, monkeypatch, wire, normalizer):
    runner, _, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [read_reply(), reply(wire), reply('{"answer":"file evidence"}')])
    context = context_for(runner, step)
    with monkeypatch.context() as legacy:
        legacy.setattr("adapters.model.json_output." + normalizer, lambda _: None)
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


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "path", "requirement"), [
    ("fs.read", "note.txt", {"kind": "file", "path": "note.txt"}),
    ("fs.list", ".", {"kind": "directory", "path": ".", "operation": "list", "recursive": False}),
])
async def test_new_session_submits_confirmed_historical_reads_without_reexecuting_tools(
        stack, monkeypatch, tool, path, requirement):
    from contracts.planning import PlannedTask, TaskPlan

    runner, _, step, _ = node(stack, GeneralAgent(), mission_id="mission_aabbccddeeff")
    runner.run.input["workspaceBinding"] = {"workspaceId": "one", "grantId": "grant-one"}
    runner.run.execution_state["workspaceObservations"] = [requirement,
        {"kind": "file", "path": "remaining.txt"}]
    task = PlannedTask(key="source-page", title="Inspect page", objective="Report this page's evidence",
        logicalRole="workspace_acquisition", constraints=[{"workspaceReview": {"targets": [{
            "operation": tool.removeprefix("fs."), "path": path}]}}])
    runner.run.execution_state.update(taskPlan=TaskPlan(missionId=runner.run.mission_id,
        nodes=(task,)).model_dump(by_alias=True, mode="json"),
        taskBindings=[{"planNodeKey": task.key, "acgNodeId": step.step_id}])
    old_context = context_for(runner, step)
    operation = old_context.commit_id + ":tools:0:call:0"
    observed = await old_context.tool_runtime.execute(tool, {"path": path}, operation_key=operation)
    historical = [{"kind": "previous_attempt_tool_observation", "operationKey": operation,
        "record": dict(observed.record), "result": dict(observed.data)}]

    http = bind_raw_model(runner, [reply('{"answer":"verified page; remaining.txt remains unread"}')])
    context = context_for(runner, step)
    context.commit_id = "new-commit"
    context.attempt_id = "new-attempt"
    context.tool_runtime = runner.tool_runtime.bind_context(context, lambda: None)
    collected = []

    async def bound_collector(current):
        assert current is context
        collected.append(current.attempt_id)
        return copy.deepcopy(historical)

    monkeypatch.setattr(context.tool_runtime, "previous_attempt_observations", bound_collector)
    session = AgentToolSession(context)
    result = await session.generate_json(prompt="Submit the supplied historical page and remaining gaps",
        schema=ANSWER, historical_observations=historical)

    assert result.data["answer"] == "verified page; remaining.txt remains unread"
    assert collected == ["new-attempt"]
    assert len(http.requests) == len(stack.service.requests) == stack.service.execution_count == 1
    assert session.actions == 0 and session.records == [] and session.observations == []
    assert session.historical_records == [historical[0]["record"]]
    assert session.historical_records[0]["attemptId"] == old_context.attempt_id
    assert session.historical_records[0]["commitId"] == old_context.commit_id
    workspace_message = next(json.loads(message["content"]) for message in http.requests[0]["messages"]
        if message.get("role") == "user" and '"WorkspaceExecutionContext"' in message["content"])
    assignment = workspace_message["workspace"]["content"]["assignedAcquisition"]
    assert assignment["batchComplete"] is True and assignment["remainingTargets"] == []
    # Reusing an observation neither commits the old node nor settles global gaps.
    assert runner.run.completed_step_ids == []
    assert runner.value_store.list_node_commits(run_id=runner.run.run_id) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["collector_missing", "collector_disagrees"])
async def test_session_rejects_historical_observations_without_bound_collector_confirmation(stack, monkeypatch, defect):
    runner, _, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [])
    context = context_for(runner, step)
    supplied = [{"kind": "previous_attempt_tool_observation", "record": {"tool": "fs.read"},
        "result": {"content": "unconfirmed"}}]

    async def collect(_):
        return None if defect == "collector_missing" else []

    monkeypatch.setattr(context.tool_runtime, "previous_attempt_observations", collect)
    with pytest.raises(StructuredGenerationError) as caught:
        await AgentToolSession(context).generate_json(prompt="inspect", schema=ANSWER,
            historical_observations=supplied)
    assert caught.value.code == "RETRY_EVIDENCE_UNAVAILABLE"
    assert http.requests == [] and stack.service.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("historical", [None, []])
async def test_absent_historical_observations_do_not_touch_the_retry_collector(stack, monkeypatch, historical):
    runner, _, step, _ = node(stack, GeneralAgent())
    http = bind_raw_model(runner, [reply('{"answer":"same session protocol"}')])
    context = context_for(runner, step)

    async def forbidden(_):
        pytest.fail("ordinary sessions must not load historical retry evidence")

    monkeypatch.setattr(context.tool_runtime, "previous_attempt_observations", forbidden)
    result = await AgentToolSession(context).generate_json(prompt="inspect", schema=ANSWER,
        historical_observations=historical)
    assert result.data == {"answer": "same session protocol"}
    assert len(http.requests) == 1 and stack.service.requests == []
