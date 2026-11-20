"""Classified model transport recovery preserves a single tool-turn identity."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from contextlib import asynccontextmanager
from http.client import IncompleteRead
import json
from urllib.error import HTTPError

import pytest

from adapters.model.guarded import GuardedModelRuntime, ModelCallGateRegistry
from adapters.agent.tool_session import AgentToolSession
from adapters.transport.http import HttpJsonTransport, HttpTransportError
from adapters.model.protocols import StructuredGenerationError
from adapters.model.compatibility import ModelCompatibilityRegistry
from adapters.model.registered_runtime import RegisteredModelRuntime
from adapters.model.openai_runtime import ModelInvocationError, OpenAICompatibleRuntime
from contracts.capability import (
    CapabilityKind, CapabilityManifest, ModelInvocationRequest, ModelInvocationResponse,
)
from support.model_stream_policy import ModelStreamPolicy


TOOLS = [{'type': 'function', 'function': {'name': 'fs__read',
    'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}]
USAGE = {'prompt_tokens': 23, 'completion_tokens': 7, 'total_tokens': 30}


def sse(chunk):
    return [("data: " + json.dumps(chunk) + "\n").encode(), b'\n']


def network_failure(kind):
    return IncompleteRead(b'PRIVATE_PARTIAL_BYTES', expected=100) if kind is IncompleteRead else kind('PRIVATE_SOCKET_DETAIL')


class ReadlineResponse:
    status = 200

    def __init__(self, lines):
        self.lines = iter(lines)
        self.closed = False

    def readline(self):
        value = next(self.lines, b'')
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        self.closed = True


def transport_for(response):
    return HttpJsonTransport(base_url='https://offline.invalid/v1',
        opener=lambda *_args, **_kwargs: response)


def adapter_for(transport):
    return OpenAICompatibleRuntime(manifest=CapabilityManifest(capabilityId='offline-model',
        kind=CapabilityKind.MODEL, displayName='Offline fixture', provider='offline', capabilities=['fixture'],
        metadata={'modelCapabilities': {'fixture': {'features': {'tools': True, 'streaming': True}}}}),
        transport=transport)


def request():
    return ModelInvocationRequest(requestId='offline-turn', model='fixture',
        messages=[{'role': 'user', 'content': 'Inspect authorized evidence.'}],
        responseSchema={'type': 'object'}, options={'tools': TOOLS}, commitId='commit:node:tools:2')


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [OSError, TimeoutError, IncompleteRead])
async def test_sse_readline_network_failure_is_classified_and_does_not_expose_socket_detail(failure):
    response = ReadlineResponse(sse({'choices': []}) + [network_failure(failure)])
    transport = transport_for(response)
    with pytest.raises(HttpTransportError) as captured:
        async for _ in transport.stream_json(path='/chat/completions', payload={}):
            pass

    assert captured.value.code == 'MODEL_TEMPORARY_UNAVAILABLE'
    assert captured.value.diagnostics['phase'] == 'stream_read'
    assert captured.value.diagnostics['exceptionType'] == failure.__name__
    assert 'PRIVATE' not in str(captured.value)
    assert response.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_turn', [False, True])
@pytest.mark.parametrize('usage_received', [False, True])
@pytest.mark.parametrize('failure', [OSError, IncompleteRead])
async def test_finished_turn_survives_usage_tail_transport_interruption(tool_turn, usage_received, failure):
    if tool_turn:
        delta = {'tool_calls': [{'index': 0, 'id': 'read-call', 'type': 'function',
            'function': {'name': 'fs__read', 'arguments': '{"path":"note.txt"}'}}]}
        finish = 'tool_calls'
    else:
        delta, finish = {'content': '{"answer":"verified"}'}, 'stop'
    lines = sse({'choices': [{'delta': delta, 'finish_reason': finish}]})
    if usage_received:
        lines += sse({'choices': [], 'usage': USAGE})
    response = ReadlineResponse(lines + [network_failure(failure)])
    adapter = adapter_for(transport_for(response))
    events = [event async for event in adapter.astream(request())]

    assert [event.event_type for event in events].count('completed') == 1
    final = events[-1].response
    assert final is not None and final.metadata['finishReason'] == finish
    if tool_turn:
        assert final.tool_calls[0]['id'] == 'read-call'
        assert json.loads(final.tool_calls[0]['function']['arguments']) == {'path': 'note.txt'}
    else:
        assert final.content == {'answer': 'verified'}
    assert final.usage == (USAGE if usage_received else {})
    assert final.metadata['streamDiagnostics']['completionObserved'] is True
    assert 'PRIVATE' not in json.dumps(final.metadata)
    assert response.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize('tail,code', [('disconnect', 'MODEL_TEMPORARY_UNAVAILABLE'), ('eof', 'MODEL_STREAM_INCOMPLETE')])
@pytest.mark.parametrize('finish', [None, ''])
async def test_valid_content_without_finish_does_not_become_a_completed_turn(tail, code, finish):
    lines = sse({'choices': [{'delta': {'content': '{"answer":"looks complete"}'}, 'finish_reason': finish}]})
    if tail == 'disconnect':
        lines.append(TimeoutError('PRIVATE_UNFINISHED_STREAM'))
    response = ReadlineResponse(lines)
    seen = []
    with pytest.raises(ModelInvocationError) as captured:
        async for event in adapter_for(transport_for(response)).astream(request()):
            seen.append(event)

    assert captured.value.code == code
    assert not any(event.event_type == 'completed' for event in seen)
    assert captured.value.metadata['streamDiagnostics']['completionObserved'] is False
    assert response.closed is True


@pytest.mark.asyncio
async def test_malformed_sse_after_finish_is_not_hidden_by_transport_tail_recovery():
    lines = sse({'choices': [{'delta': {'content': '{"answer":"valid before malformed tail"}'},
        'finish_reason': 'stop'}]})
    response = ReadlineResponse(lines + [b'data: PRIVATE_NOT_JSON\n', b'\n'])
    seen = []
    with pytest.raises(ModelInvocationError) as captured:
        async for event in adapter_for(transport_for(response)).astream(request()):
            seen.append(event)

    assert captured.value.code == 'MODEL_RESPONSE_INVALID'
    assert not any(event.event_type == 'completed' for event in seen)
    assert 'PRIVATE' not in str(captured.value)
    assert response.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize('finish,code', [('length', 'MODEL_OUTPUT_EXHAUSTED'), ('content_filter', 'MODEL_RESPONSE_REFUSED')])
async def test_usage_tail_recovery_preserves_terminal_output_rejection(finish, code):
    lines = sse({'choices': [{'delta': {'content': '{"answer":"valid JSON alone is insufficient"}'},
        'finish_reason': finish}]})
    response = ReadlineResponse(lines + [OSError('PRIVATE_TAIL')])
    with pytest.raises(ModelInvocationError) as captured:
        async for _ in adapter_for(transport_for(response)).astream(request()):
            pass
    assert captured.value.code == code
    assert response.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['MODEL_TEMPORARY_UNAVAILABLE', 'MODEL_RATE_LIMITED', 'MODEL_STREAM_INCOMPLETE',
    'MODEL_TIMEOUT', 'MODEL_TTFT_TIMEOUT', 'MODEL_IDLE_TIMEOUT', 'MODEL_TOTAL_TIMEOUT'])
async def test_classified_transient_tool_turn_retries_keep_all_request_arguments_and_commit_id(monkeypatch, code):
    observed, delays = [], []
    real_sleep = asyncio.sleep
    result = ModelInvocationResponse(requestId='same-turn', provider='offline', model='fixture',
        content={'answer': 'verified'}, usage=USAGE)

    async def cooperative_delay(seconds):
        delays.append(seconds)
        await real_sleep(0)

    class Delegate:
        manages_tool_turn_timeout = True

        async def generate_tool_turn(self, **kwargs):
            observed.append(deepcopy(kwargs))
            if len(observed) <= 8:
                raise StructuredGenerationError(code, 'classified temporary transport condition')
            return result

    monkeypatch.setattr('adapters.model.guarded.asyncio.sleep', cooperative_delay)
    wrapper = GuardedModelRuntime(delegate=Delegate(), retries=0)
    arguments = {'messages': [{'role': 'user', 'content': 'same node conversation'}],
        'tools': TOOLS, 'schema': {'type': 'object'}, 'commit_id': 'commit:node:tools:7',
        'request_budget': {'mode': 'unknown'}, 'schema_message_index': 1, 'reasoning_effort': 'low'}
    before = deepcopy(arguments)

    assert await wrapper.generate_tool_turn(timeout_seconds=10, **arguments) is result
    assert len(observed) == 9 and len(delays) == 8
    assert all(value == {**before, 'timeout_seconds': 10} for value in observed)
    assert arguments == before
    assert all(delay > 0 for delay in delays)


@pytest.mark.asyncio
async def test_repeated_transient_tool_turn_retry_can_be_cancelled_during_backoff(monkeypatch):
    waiting = asyncio.Event()
    observed = []

    async def blocked_delay(_seconds):
        waiting.set()
        await asyncio.Event().wait()

    class Delegate:
        async def generate_tool_turn(self, **kwargs):
            observed.append(kwargs)
            raise StructuredGenerationError('MODEL_TEMPORARY_UNAVAILABLE', 'offline interruption')

    monkeypatch.setattr('adapters.model.guarded.asyncio.sleep', blocked_delay)
    task = asyncio.create_task(GuardedModelRuntime(delegate=Delegate()).generate_tool_turn(
        messages=[], tools=TOOLS, schema={}, commit_id='same-turn', timeout_seconds=10))
    await asyncio.wait_for(waiting.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(observed) == 1


@pytest.mark.asyncio
async def test_shared_model_capacity_is_available_to_another_turn_during_retry_backoff(monkeypatch):
    backoff_started, release_backoff = asyncio.Event(), asyncio.Event()
    calls = []

    async def blocked_backoff(_seconds):
        backoff_started.set()
        await release_backoff.wait()

    class Delegate:
        manages_tool_turn_timeout = True

        async def generate_tool_turn(self, **kwargs):
            identity = kwargs['commit_id']
            calls.append(identity)
            if identity == 'retrying-turn' and calls.count(identity) == 1:
                raise StructuredGenerationError('MODEL_TEMPORARY_UNAVAILABLE', 'retry only this model turn')
            return ModelInvocationResponse(requestId=identity, provider='offline', model='fixture',
                content={'turn': identity})

    monkeypatch.setattr('adapters.model.guarded.asyncio.sleep', blocked_backoff)
    delegate = Delegate()
    gate = ModelCallGateRegistry().gate_for('same-route', max_concurrency=1, min_interval_seconds=0)
    first, second = (GuardedModelRuntime(delegate=delegate, max_concurrency=1, _gate=gate) for _ in range(2))
    pending = asyncio.create_task(first.generate_tool_turn(messages=[], tools=TOOLS, schema={},
        commit_id='retrying-turn', timeout_seconds=10))
    try:
        await asyncio.wait_for(backoff_started.wait(), 2)
        independent = await asyncio.wait_for(second.generate_tool_turn(messages=[], tools=TOOLS, schema={},
            commit_id='independent-turn', timeout_seconds=10), 2)
        assert independent.content == {'turn': 'independent-turn'} and not pending.done()
        release_backoff.set()
        assert (await pending).content == {'turn': 'retrying-turn'}
        assert calls == ['retrying-turn', 'independent-turn', 'retrying-turn']
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['MODEL_PROVIDER_FAILED', 'MODEL_AUTH_INVALID', 'MODEL_RESPONSE_REFUSED',
    'MODEL_TOOL_CALL_INVALID', 'MODEL_RESPONSE_INVALID'])
async def test_permanent_tool_turn_failure_is_not_retried(monkeypatch, code):
    observed = []

    async def forbidden_delay(_seconds):
        pytest.fail('permanent model failures must not enter retry backoff')

    class Delegate:
        async def generate_tool_turn(self, **kwargs):
            observed.append(kwargs)
            raise StructuredGenerationError(code, 'permanent provider condition')

    monkeypatch.setattr('adapters.model.guarded.asyncio.sleep', forbidden_delay)
    with pytest.raises(StructuredGenerationError) as captured:
        await GuardedModelRuntime(delegate=Delegate(), retries=5).generate_tool_turn(
            messages=[], tools=TOOLS, schema={}, commit_id='same-turn', timeout_seconds=10)
    assert captured.value.code == code and len(observed) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403])
async def test_http_client_error_is_permanent_through_the_registered_tool_runtime(monkeypatch, status):
    openings = []

    def opener(_request, **_kwargs):
        openings.append(status)
        raise HTTPError('https://offline.invalid', status, 'PRIVATE_HTTP_BODY', {}, None)

    async def forbidden_delay(_seconds):
        pytest.fail('HTTP client errors must not enter transient retry backoff')

    monkeypatch.setattr('adapters.model.guarded.asyncio.sleep', forbidden_delay)
    adapter = adapter_for(HttpJsonTransport(base_url='https://offline.invalid/v1', opener=opener))
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    runtime = GuardedModelRuntime(delegate=RegisteredModelRuntime(registry=registry, provider='offline', model='fixture'))

    async def progress(*_args):
        pass

    with pytest.raises(StructuredGenerationError) as captured:
        await runtime.generate_tool_turn(messages=[], tools=TOOLS, schema={}, commit_id='same-turn',
            progress_callback=progress, timeout_seconds=10)
    assert captured.value.code == 'MODEL_PROVIDER_FAILED' and openings == [status]
    assert 'PRIVATE_HTTP_BODY' not in str(captured.value)


@pytest.mark.parametrize('has_completed_turn', [False, True])
def test_failed_turn_audit_preserves_safe_diagnostics_with_or_without_prior_success(has_completed_turn):
    completed = {'provider': 'offline', 'model': 'fixture', 'usage': USAGE, 'finishReason': 'tool_calls'}
    session = AgentToolSession.__new__(AgentToolSession)
    session.actions = 2
    session.invocations = [deepcopy(completed)] if has_completed_turn else []
    stream = {'streamStarted': True, 'completionObserved': False, 'deltaCount': 3,
        'elapsedMs': 200, 'streamTerminationReason': 'MODEL_TEMPORARY_UNAVAILABLE'}
    transport = {'phase': 'stream_read', 'exceptionType': 'OSError', 'httpStatus': 503}
    failure = StructuredGenerationError('MODEL_TEMPORARY_UNAVAILABLE', 'safe classified failure', audit={
        'provider': 'offline', 'model': 'fixture', 'usage': {'prompt_tokens': 11},
        'streamDiagnostics': {**stream, 'rawBody': 'PRIVATE_MODEL_BODY', 'unrecognized': {'nested': 'PRIVATE'}},
        'transportDiagnostics': {**transport, 'responseBody': 'PRIVATE_PROVIDER_BODY',
            'headers': {'Authorization': 'PRIVATE_AUTHORITY'}},
    })

    session._attach_failure_audit(failure)

    turns = failure.audit['modelInvocations']
    assert len(turns) == (2 if has_completed_turn else 1)
    assert turns[-1]['streamDiagnostics'] == stream
    assert turns[-1]['transportDiagnostics'] == transport
    assert turns[-1]['usage'] == {'prompt_tokens': 11}
    assert failure.audit['toolActionsExecuted'] == 2
    assert 'PRIVATE' not in json.dumps(failure.audit)
    if has_completed_turn:
        assert turns[0] == completed


class SealedTailTransport:
    def __init__(self, *, usage=False, stall=True, extra=None):
        self.usage, self.stall, self.extra = usage, stall, extra
        self.calls = 0
        self.closed = False
        self.waiting = asyncio.Event()

    async def stream_json(self, **_kwargs):
        self.calls += 1
        try:
            yield {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'sealed-read', 'type': 'function',
                'function': {'name': 'fs__read', 'arguments': '{"path":"PRIVATE_PATH"}'}}]},
                'finish_reason': 'tool_calls'}]}
            if self.usage:
                yield {'choices': [], 'usage': USAGE}
            if self.extra is not None:
                yield self.extra
            self.waiting.set()
            if self.stall:
                await asyncio.Event().wait()
        finally:
            self.closed = True


def sealed_runtime(transport):
    registry = ModelCompatibilityRegistry()
    registry.register(adapter_for(transport))
    return RegisteredModelRuntime(registry=registry, provider='offline', model='fixture')


async def call_sealed_runtime(runtime, *, timeout=.2):
    async def progress(*_args):
        pass

    return await runtime.generate_tool_turn(messages=[], tools=TOOLS, schema={}, commit_id='sealed-turn',
        progress_callback=progress, timeout_seconds=timeout)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['idle', 'total', 'overall'])
@pytest.mark.parametrize('usage_received', [False, True])
async def test_sealed_turn_survives_hanging_usage_tail_without_provider_retry(monkeypatch, phase, usage_received):
    policy = ModelStreamPolicy(first_response=1, idle=.01 if phase == 'idle' else 1,
        total=.02 if phase == 'total' else 1)
    monkeypatch.setattr(ModelStreamPolicy, 'from_environment', classmethod(lambda cls: policy))

    async def forbidden_backoff(_seconds):
        pytest.fail('a sealed response must not incur a repeated model request')

    monkeypatch.setattr('adapters.model.guarded.asyncio.sleep', forbidden_backoff)
    transport = SealedTailTransport(usage=usage_received)
    runtime = GuardedModelRuntime(delegate=sealed_runtime(transport))
    result = await call_sealed_runtime(runtime, timeout=.03 if phase == 'overall' else .2)

    assert transport.calls == 1 and transport.closed is True
    assert result.tool_calls[0]['id'] == 'sealed-read'
    assert result.usage == (USAGE if usage_received else {})
    assert result.metadata['streamDiagnostics']['completionObserved'] is True
    assert result.metadata['streamDiagnostics']['streamTerminationReason'] == 'completed_after_usage_timeout'
    assert result.metadata['usageTailTimeoutCode'] == {
        'idle': 'MODEL_IDLE_TIMEOUT', 'total': 'MODEL_TOTAL_TIMEOUT', 'overall': 'MODEL_TIMEOUT'}[phase]


@pytest.mark.asyncio
async def test_sealed_and_completed_usage_settle_one_quota_charge_without_duplicate_tokens():
    from components.resource.model_quota import _Charge

    settled = []

    @asynccontextmanager
    async def quota(_request, _timeout):
        charge = _Charge()
        try:
            yield charge
        finally:
            settled.append(charge.tokens)

    transport = SealedTailTransport(usage=True, stall=False)
    runtime = sealed_runtime(transport)
    runtime._call_quota = quota
    result = await call_sealed_runtime(runtime)
    assert result.usage == USAGE
    assert settled == [USAGE['total_tokens']]
    assert transport.calls == 1 and transport.closed is True


@pytest.mark.asyncio
async def test_sealed_event_keeps_response_excluded_from_serialized_event():
    transport = SealedTailTransport(stall=False)
    events = [event async for event in adapter_for(transport).astream(request())]
    sealed = next(event for event in events if event.event_type == 'sealed')
    assert sealed.response is not None and sealed.response.tool_calls
    assert 'response' not in sealed.model_dump()
    assert 'PRIVATE_PATH' not in sealed.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize('delta', [{'content': 'PRIVATE_LATE_CONTENT'}, {'reasoning_content': 'PRIVATE_LATE_REASONING'},
    {'tool_calls': [{'function': {'arguments': 'PRIVATE_LATE_ARGUMENTS'}}]}, {'refusal': 'PRIVATE_REFUSAL'}])
async def test_answer_fragments_after_seal_are_rejected_before_dispatch(delta):
    transport = SealedTailTransport(stall=False, extra={'choices': [{'delta': delta}]})
    with pytest.raises(StructuredGenerationError) as caught:
        await call_sealed_runtime(sealed_runtime(transport))
    assert caught.value.code == 'MODEL_RESPONSE_INVALID'
    assert transport.closed is True and transport.calls == 1
    assert 'PRIVATE' not in str(caught.value.audit)


@pytest.mark.asyncio
async def test_external_cancellation_after_seal_remains_cancellation_and_closes_provider():
    transport = SealedTailTransport()
    task = asyncio.create_task(call_sealed_runtime(sealed_runtime(transport)))
    await asyncio.wait_for(transport.waiting.wait(), .1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.closed is True and transport.calls == 1
