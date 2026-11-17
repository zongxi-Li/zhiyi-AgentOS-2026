"""Offline session deadline contracts; model and tool callbacks are simulated."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

from adapters.agent_tools import AgentToolSession
from adapters.model_adapter import StructuredGenerationError
from contracts.capability import ModelInvocationResponse
from contracts.tools import ToolResult, hands_tools
from support.work_timeouts import work_timeout


USAGE = {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}
SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}
READ = {'id': 'read-once', 'type': 'function', 'function': {
    'name': 'fs__read', 'arguments': '{"path":"note.txt"}'}}


@pytest.fixture
def expire_session_budget(monkeypatch):
    timers = []

    @asynccontextmanager
    async def observed_budget(seconds):
        async with work_timeout(seconds) as timer:
            timers.append(timer)
            yield timer

    monkeypatch.setattr('adapters.agent_tools.work_timeout', observed_budget)

    def expire():
        # Trigger the actual deadline only after the target callback starts,
        # independent of SDK import/startup speed or machine scheduling.
        timers[-1].reschedule(asyncio.get_running_loop().time())

    return expire


def response(*, calls=None, invalid=False):
    return ModelInvocationResponse(requestId='offline', provider='offline', model='fixture',
        content={} if calls or invalid else {'answer': 'complete'}, toolCalls=calls or [], usage=USAGE,
        outputError='MODEL_OUTPUT_INVALID_JSON' if invalid else None,
        assistantMessage={'role': 'assistant', 'content': 'PRIVATE_INVALID_REPLY'} if invalid else None)


class SimulatedModel:
    provider = 'offline'

    def __init__(self, callback):
        self.callback = callback
        self.requests = []

    async def generate_tool_turn(self, **kwargs):
        turn = len(self.requests)
        self.requests.append(kwargs['messages'])
        return await self.callback(turn, kwargs['messages'])


class SimulatedTools:
    def __init__(self, callback=None):
        self.callback = callback
        self.calls = []

    def list_tools(self):
        return (hands_tools()[0],)

    async def execute(self, name, arguments, **kwargs):
        self.calls.append((name, arguments))
        if self.callback:
            return await self.callback()
        return ToolResult(name=name, source='fixture', status='succeeded',
                          output={'content': 'PRIVATE_FILE_BODY'})


def session_for(callback, tools=None):
    model = SimulatedModel(callback)
    tools = tools or SimulatedTools()
    context = SimpleNamespace(model_runtime=model, tool_runtime=tools, commit_id='commit:offline',
        attempt_id='attempt:offline', run=SimpleNamespace(run_id='run:offline', input={}, execution_state={}),
        step=SimpleNamespace(step_id='node', name='offline node', capability='analysis', input={}))
    return AgentToolSession(context), model, tools


@pytest.mark.asyncio
async def test_deadline_after_invalid_candidate_has_stable_code_and_completed_usage(expire_session_budget):
    blocked = asyncio.Event()

    async def model(turn, messages):
        if turn == 0:
            return response(invalid=True)
        blocked.set()
        expire_session_budget()
        await asyncio.Event().wait()

    session, model_runtime, tools = session_for(model)
    with pytest.raises(StructuredGenerationError) as captured:
        await session.generate_json(prompt='PRIVATE_INPUT', schema=SCHEMA, timeout_seconds=10)

    assert blocked.is_set() and len(model_runtime.requests) == 2
    assert captured.value.code == 'AGENT_WORK_TIMEOUT'
    assert captured.value.audit['toolActionsExecuted'] == 0
    assert [item['usage'] for item in captured.value.audit['modelInvocations']] == [USAGE]
    assert captured.value.audit['modelInvocations'][0]['effectiveReason'] == 'invalid_json_before_repair'
    assert 'PRIVATE' not in json.dumps(captured.value.audit)
    assert tools.calls == []


@pytest.mark.asyncio
async def test_deadline_after_completed_tool_preserves_usage_without_repeating_tool(expire_session_budget):
    async def model(turn, messages):
        if turn == 0:
            return response(calls=[READ])
        assert messages[-1]['role'] == 'tool'
        assert 'PRIVATE_FILE_BODY' in messages[-1]['content']
        expire_session_budget()
        await asyncio.Event().wait()

    session, model_runtime, tools = session_for(model)
    with pytest.raises(StructuredGenerationError) as captured:
        await session.generate_json(prompt='inspect', schema=SCHEMA, timeout_seconds=10)

    assert captured.value.code == 'AGENT_WORK_TIMEOUT'
    assert len(model_runtime.requests) == 2
    assert tools.calls == [('fs.read', {'path': 'note.txt'})]
    assert captured.value.audit['toolActionsExecuted'] == 1
    assert [item['usage'] for item in captured.value.audit['modelInvocations']] == [USAGE]
    assert 'PRIVATE_FILE_BODY' not in json.dumps(captured.value.audit)


@pytest.mark.asyncio
@pytest.mark.parametrize('external_cancel,workspace', [(False, False), (True, False), (True, True)])
async def test_deadline_or_external_cancel_waits_for_inflight_tool_cleanup(external_cancel, workspace, expire_session_budget):
    started, released = asyncio.Event(), asyncio.Event()

    async def model(turn, messages):
        assert turn == 0
        return response(calls=[READ])

    async def execute():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(.01)
            released.set()

    session, _, tools = session_for(model, SimulatedTools(execute))
    if workspace:
        session.context.run.input['workspaceBinding'] = {'workspaceId': 'one', 'grantId': 'grant-one'}
    task = asyncio.create_task(session.generate_json(prompt='inspect', schema=SCHEMA, timeout_seconds=10))
    await asyncio.wait_for(started.wait(), 1)
    if external_cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        expire_session_budget()
        with pytest.raises(StructuredGenerationError) as captured:
            await task
        assert captured.value.code == 'AGENT_WORK_TIMEOUT'
    assert released.is_set()
    assert len(tools.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('workspace', [False, True])
async def test_delegate_timeout_before_session_deadline_keeps_its_identity(workspace):
    failure = TimeoutError('delegate timeout')

    async def model(turn, messages):
        if turn == 0:
            return response(invalid=True)
        raise failure

    session, model_runtime, _ = session_for(model)
    if workspace:
        session.context.run.input['workspaceBinding'] = {'workspaceId': 'one', 'grantId': 'grant-one'}
    with pytest.raises(TimeoutError) as captured:
        await session.generate_json(prompt='inspect', schema=SCHEMA, timeout_seconds=10)

    assert captured.value is failure
    assert not isinstance(captured.value, StructuredGenerationError)
    assert len(model_runtime.requests) == 2


@pytest.mark.asyncio
async def test_tool_internal_timeout_is_an_observation_not_session_deadline():
    async def model(turn, messages):
        if turn == 0:
            return response(calls=[READ])
        result = json.loads(messages[-1]['content'])
        assert result['status'] == 'failed'
        assert result['error']['code'] == 'TOOL_EXECUTION_FAILED'
        return response()

    async def execute():
        raise TimeoutError('tool local timeout')

    session, _, tools = session_for(model, SimulatedTools(execute))
    result = await session.generate_json(prompt='inspect', schema=SCHEMA, timeout_seconds=10)

    assert result.data == {'answer': 'complete'}
    assert len(tools.calls) == 1


@pytest.mark.asyncio
async def test_workspace_conversation_outlives_individual_io_budget_without_repeating_reads():
    timeouts = []

    async def model(turn, messages):
        await asyncio.sleep(.02)
        if turn < 2:
            call = {**READ, 'id': f'read-{turn}', 'function': {
                **READ['function'], 'arguments': json.dumps({'path': f'note-{turn}.txt'})}}
            return response(calls=[call])
        return response()

    class TimedTools(SimulatedTools):
        async def execute(self, name, arguments, **kwargs):
            timeouts.append(kwargs['timeout_seconds'])
            async with asyncio.timeout(kwargs['timeout_seconds']):
                await asyncio.sleep(.02)
                return await super().execute(name, arguments, **kwargs)

    class TimedModel(SimulatedModel):
        async def generate_tool_turn(self, **kwargs):
            timeouts.append(kwargs['timeout_seconds'])
            async with asyncio.timeout(kwargs['timeout_seconds']):
                return await super().generate_tool_turn(**kwargs)

    session, _, tools = session_for(model, TimedTools())
    session.context.model_runtime = TimedModel(model)
    session.context.run.input['workspaceBinding'] = {'workspaceId': 'one', 'grantId': 'grant-one'}
    result = await session.generate_json(prompt='inspect', schema=SCHEMA, timeout_seconds=.05)

    assert result.data == {'answer': 'complete'}
    assert timeouts == [.05] * 5
    assert tools.calls == [('fs.read', {'path': f'note-{i}.txt'}) for i in range(2)]


@pytest.mark.asyncio
async def test_workspace_tool_io_timeout_still_requires_settlement():
    async def model(turn, messages):
        assert turn == 0
        return response(calls=[READ])

    async def execute():
        raise StructuredGenerationError('TOOL_TIMEOUT', 'individual I/O timed out')

    session, model_runtime, tools = session_for(model, SimulatedTools(execute))
    session.context.run.input['workspaceBinding'] = {'workspaceId': 'one', 'grantId': 'grant-one'}
    with pytest.raises(StructuredGenerationError) as captured:
        await session.generate_json(prompt='inspect', schema=SCHEMA, timeout_seconds=10)

    assert captured.value.code == 'TOOL_TIMEOUT'
    assert len(model_runtime.requests) == 1 and len(tools.calls) == 1

\n