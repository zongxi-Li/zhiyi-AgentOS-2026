"""Exercise raw-byte deadlines and real SDK tool-loop retry boundaries."""
import asyncio
import json

import httpx
import pytest
from agents import Agent, OpenAIChatCompletionsModel, RunConfig, Runner, function_tool
from openai import AsyncOpenAI

from app.llm.stream_transport import ModelStreamClient
from support.model_stream_policy import ModelStreamPolicy, ModelStreamTimeout


@pytest.mark.asyncio
async def test_tool_argument_phase_is_observed_before_the_complete_tool_call():
    from app.llm.observable_chat_model import _ObservedChunks
    from types import SimpleNamespace as Obj
    phases = []

    async def chunks():
        for name, arguments in [('write_file', '{"content":"private'), (None, 'file data"}')]:
            yield Obj(choices=[Obj(delta=Obj(tool_calls=[Obj(index=0, function=Obj(name=name, arguments=arguments))]))])

    observer = _ObservedChunks(chunks(), lambda name, data: phases.append((name, data)))
    iterator = observer.__aiter__()
    await anext(iterator)
    assert phases == [('model_phase', {'phase': 'tool_arguments', 'toolName': 'write_file'})]
    await anext(iterator)
    assert len(phases) == 1
    assert 'private' not in str(phases)
    await observer.aclose()


class Bytes(httpx.AsyncByteStream):
    def __init__(self, packets):
        self.packets = packets
        self.closed = 0
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        for delay, data in self.packets:
            self.waiting.set()
            await asyncio.sleep(delay)
            yield data

    async def aclose(self):
        self.closed += 1


async def consume(stream, policy):
    async def handler(request):
        return httpx.Response(200, stream=stream)
    async with ModelStreamClient(policy, transport=httpx.MockTransport(handler)) as client:
        async with client.stream("POST", "https://example.test/chat/completions") as response:
            return [chunk async for chunk in response.aiter_bytes()]


@pytest.mark.asyncio
async def test_provider_activity_including_reasoning_and_tool_arguments_resets_idle():
    stream = Bytes([(.02, data) for data in (b'reasoning', b'tool-args', b'more-args', b'answer')])
    result = await consume(stream, ModelStreamPolicy(first_response=.1, idle=.06, total=1))
    assert result == [b'reasoning', b'tool-args', b'more-args', b'answer']
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_request_size_is_bytes_and_provider_timings_are_separate_from_token_usage():
    contexts, activities, sizes = [], [], []
    async def handler(request):
        sizes.append(len(request.content))
        return httpx.Response(200, stream=Bytes([(.01, b'first'), (.01, b'next')]))
    async with ModelStreamClient(ModelStreamPolicy(first_response=1, idle=1, total=2), transport=httpx.MockTransport(handler)) as client:
        client.on_context = lambda name,data: contexts.append(data)
        client.on_activity = lambda name,data: activities.append(data)
        response = await client.post('https://test.invalid', json={'content':'中文'})
        assert response.content == b'firstnext'
    assert contexts[0]['requestBodyBytes'] == sizes[0]
    assert contexts[0]['contextMeasurement'] == 'request-bytes'
    assert 'contextInputTokens' not in contexts[0]
    assert activities[0]['responseTimings']['providerHeadersMs'] >= 0
    assert activities[1]['responseTimings']['providerFirstByteMs'] >= activities[0]['responseTimings']['providerHeadersMs']


@pytest.mark.asyncio
@pytest.mark.parametrize("packets,policy,phase", [
    ([(.2, b'a')], ModelStreamPolicy(first_response=.04, idle=.1, total=1), 'first_response'),
    ([(0, b'a'), (.2, b'b')], ModelStreamPolicy(first_response=.1, idle=.04, total=1), 'idle'),
    ([(.02, b'a')] * 10, ModelStreamPolicy(first_response=.2, idle=.2, total=.08), 'total'),
])
async def test_deadlines_are_classified_and_close_upstream(packets, policy, phase):
    stream = Bytes(packets)
    with pytest.raises(ModelStreamTimeout) as failure:
        await consume(stream, policy)
    assert failure.value.phase == phase
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_disconnect_cancels_outstanding_provider_read_and_closes_stream():
    stream = Bytes([(60, b'never')])
    task = asyncio.create_task(consume(stream, ModelStreamPolicy()))
    await stream.waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed == 1


def frame(delta, finish=None):
    return b'data: ' + json.dumps({
        'id': 'test', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'glm-5.3-flash',
        'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}],
    }).encode() + b'\n\n'


@pytest.mark.asyncio
@pytest.mark.parametrize('recovers', [False, True])
async def test_sdk_retries_request_failure_but_never_replays_tool_after_partial_stream(recovers):
    requests = []
    effects = []

    @function_tool
    def touch() -> str:
        """Record a completed side effect."""
        effects.append('written')
        return 'file written'

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(503, json={'error': {'message': 'temporary'}})
        if len(requests) == 2:
            packets = [(0, frame({'role': 'assistant', 'tool_calls': [{
                'index': 0, 'id': 'call_touch', 'type': 'function',
                'function': {'name': 'touch', 'arguments': '{}'},
            }]})), (0, frame({}, 'tool_calls')), (0, b'data: [DONE]\n\n')]
        elif len(requests) >= 4 and recovers:
            packets = [(0, frame({'role': 'assistant', 'content': 'recovered response'}, 'stop')), (0, b'data: [DONE]\n\n')]
        else:
            packets = [(0, frame({'role': 'assistant', 'content': 'partial response'})), (1, frame({}, 'stop'))]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Bytes(packets))

    policy = ModelStreamPolicy(first_response=1, idle=.3, total=5)
    client = AsyncOpenAI(api_key='test-key', base_url='https://example.test/v1', max_retries=1,
                         http_client=ModelStreamClient(policy, transport=httpx.MockTransport(handler)))
    from app.llm.observable_chat_model import ObservableChatModel
    model = ObservableChatModel(model='glm-5.3-flash', openai_client=client, buffer_streamed_tool_calls=True)
    phases = []
    model.on_progress = lambda name, data: phases.append((name, data))
    agent = Agent(name='test', model=model, tools=[touch])
    result = Runner.run_streamed(agent, 'write file', run_config=RunConfig(tracing_disabled=True))
    output = []
    try:
        if recovers:
            async for event in result.stream_events():
                output.append(event)
            assert result.final_output == 'recovered response'
        else:
            with pytest.raises(ModelStreamTimeout):
                async for event in result.stream_events():
                    output.append(event)
        assert len(requests) == 4  # Initial 503 retry, plus one bounded retry of the exact continuation input.
        assert requests[2]["messages"] == requests[3]["messages"]
        assert any(data.get("phase") == "retrying" for name, data in phases)
        attempts = [data['attemptId'] for name, data in phases if data.get('phase') == 'waiting']
        assert len(set(attempts)) == 3
        assert effects == ['written']
        assert [data['turn'] for name, data in phases if data.get('phase') == 'waiting'] == [1, 2, 2]
        assert any(data.get('phase') == 'tool_arguments' for name, data in phases)
        assert any(getattr(getattr(e, 'data', None), 'delta', None) == 'partial response' for e in output)
    finally:
        result.cancel()
        task = getattr(result, 'run_loop_task', None)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await client.close()


def test_invalid_model_deadlines_are_rejected():
    with pytest.raises(ValueError):
        ModelStreamPolicy(idle=float('nan'))


@pytest.mark.asyncio
async def test_runtime_forwards_model_phase_and_provider_activity_in_sequence(monkeypatch):
    import app.tools.runtime as runtime_module

    async def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Bytes([
            (0, frame({'role': 'assistant', 'content': 'hello'})),
            (0, frame({}, 'stop')), (0, b'data: [DONE]\n\n'),
        ]))

    monkeypatch.setattr(runtime_module, 'ModelStreamClient', type('Client', (ModelStreamClient,), {
        '__init__': lambda self, policy, **kwargs: ModelStreamClient.__init__(
            self, policy, transport=httpx.MockTransport(handler), **kwargs),
    }))
    runtime = runtime_module.AgentsToolRuntime(allowed_tools=set())
    events = [event async for event in runtime.stream('test', model='glm-5.3-flash',
        base_url='https://example.test/v1', api_key='test-key', request_id='phase-test')]
    names = [event.event.value for event in events]
    assert 'model_phase' in names and 'model_activity' in names
    assert names.index('model_phase') < names.index('content_delta')
    assert names[-1] == 'done'
    usage = next(event.data for event in events if event.event.value == 'usage')
    assert usage['cacheUsageAvailable'] is False
    assert 'cached_tokens' not in usage
    assert [event.sequence for event in events] == sorted({event.sequence for event in events})


def test_tool_timeout_does_not_shorten_model_waits(monkeypatch):
    from app.config import settings
    from app.tools.runtime import AgentsToolRuntime
    monkeypatch.setattr(settings, 'TOOL_TIMEOUT_SECONDS', .01)
    runtime = AgentsToolRuntime(allowed_tools=set())
    agent, client, _ = runtime._build_agent(
        runtime._context(), model='glm-5.3-flash', base_url='https://example.test/v4',
        api_key='test', require_evidence=False, thinking_mode='deep',
    )
    try:
        assert client.timeout.read is None  # The policy, not a shorter socket timer, owns reads.
        assert client._client.policy.idle == settings.MODEL_STREAM_IDLE_TIMEOUT_SECONDS
        assert client.max_retries == settings.MODEL_REQUEST_MAX_RETRIES
    finally:
        asyncio.run(client.close())
