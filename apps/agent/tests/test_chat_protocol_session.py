import json
from types import SimpleNamespace

import httpx
import pytest
from agents import function_tool

from app.llm import chat_session
from app.llm.stream_transport import ModelStreamClient
from app.tools import runtime as runtime_module


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_session, 'APP_DATA_DIR', tmp_path)
    user = SimpleNamespace(user_id='user-a', tenant_id='tenant-a')
    monkeypatch.setattr(chat_session, 'current_trusted_user', lambda: user)
    return user


def session(model='glm-5.3-flash', history=None, projection=False):
    return chat_session.open_chat_session('conversation', model,
        'https://open.bigmodel.cn/api/coding/paas/v4', None, history, projection)


@pytest.mark.asyncio
async def test_restore_keeps_full_tool_cycle_and_never_reimports_ui_history(journal):
    items = [{'type': 'function_call', 'call_id': 'c1', 'name': 'read_file', 'arguments': '{"path":"a.txt"}'},
             {'type': 'function_call_output', 'call_id': 'c1', 'output': 'file contents'}]
    async with session(history=[{'role': 'user', 'content': 'read file'}]) as first:
        await first.add_items(items)
    async with session(history=[{'role': 'assistant', 'content': 'wrong UI reconstruction'}]) as restored:
        restored_items = await restored.get_items()
        assert restored_items[1:] == items
        assert 'wrong UI' not in str(restored_items)
    async with session(model='other-model') as isolated:
        assert await isolated.get_items() == []
    journal.user_id = 'user-b'
    async with session() as isolated:
        assert await isolated.get_items() == []


@pytest.mark.asyncio
async def test_open_checks_one_raw_journal_row_instead_of_loading_the_full_history(journal, monkeypatch):
    original = chat_session.SQLiteSession.get_items
    limits = []
    async def read(self, limit=None):
        limits.append(limit)
        return await original(self, limit)
    monkeypatch.setattr(chat_session.SQLiteSession, 'get_items', read)
    async with session(history=[{'role':'user','content':'synthetic history'}]):
        pass
    async with session(history=[{'role':'user','content':'must not be reimported'}]) as restored:
        assert limits == [1, 1]
        items = await restored.get_items()
        assert items == [{'role':'user','content':'synthetic history'}]


@pytest.mark.asyncio
async def test_busy_lease_and_delete_are_scoped_to_authenticated_conversation(journal):
    async with session() as active:
        await active.add_items([{'role': 'user', 'content': 'hello'}])
        with pytest.raises(RuntimeError, match='CHAT_SESSION_BUSY'):
            async with session(): pass
        with pytest.raises(RuntimeError, match='CHAT_SESSION_BUSY'):
            chat_session.forget_chat_sessions('conversation')
    chat_session.forget_chat_sessions('conversation')
    async with session() as cleared:
        assert await cleared.get_items() == []


def test_unrecorded_tool_outcome_is_unknown_not_a_fabricated_success():
    view = chat_session.balanced_view([{'type': 'function_call', 'name': 'write_file', 'call_id': 'c1', 'arguments': '{}'}])
    assert json.loads(view[1]['output'])['error'] == 'TOOL_OUTCOME_UNKNOWN'


@pytest.mark.asyncio
async def test_compaction_projects_a_balanced_tail_without_rewriting_journal(journal):
    raw = [{'role': 'user', 'content': 'old'}, {'role': 'assistant', 'content': 'old reply'},
           {'role': 'user', 'content': 'tail'},
           {'type': 'function_call', 'call_id': 'c', 'name': 'read_file', 'arguments': '{}'},
           {'type': 'function_call_output', 'call_id': 'c', 'output': 'actual file'},
           {'role': 'assistant', 'content': 'tail reply'}]
    async with session() as source:
        await source.add_items(raw)
    projection = [{'role': 'system', 'content': 'summary'}, {'role': 'user', 'content': 'tail'},
                  {'role': 'assistant', 'content': 'tail reply'}]
    async with session(history=projection, projection=True) as projected:
        assert await projected.get_items() == projection[:1] + raw[2:]
    async with session() as restored:
        assert await restored.get_items() == raw


def frame(delta, finish=None, usage=None):
    return ('data: ' + json.dumps({'id': 'test', 'object': 'chat.completion.chunk', 'created': 0,
      'model': 'glm-5.3-flash', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}],
      **({'usage': usage} if usage else {})}) + '\n\n').encode()


@pytest.mark.asyncio
async def test_next_user_turn_restores_tool_result_after_interruption_without_reexecuting(journal, monkeypatch):
    requests, effects = [], []

    @function_tool
    def touch() -> str:
        """Perform one recorded test operation."""
        effects.append('written')
        return 'confirmed file write'

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            import asyncio
            yield frame({'content': 'partial'})
            await asyncio.sleep(.03)
            raise httpx.ReadTimeout('interrupted')

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            data = frame({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_touch',
              'type': 'function', 'function': {'name': 'touch', 'arguments': '{}'}}]}) + frame({}, 'tool_calls')
        elif len(requests) in {2, 3}:
            # Exhaust both request-level attempts before testing a new user turn.
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream())
        else:
            data = frame({'role': 'assistant', 'content': ''}) + frame({'content': 'complete'}, 'stop', {
                'prompt_tokens': 100, 'completion_tokens': 1, 'total_tokens': 101,
                'prompt_tokens_details': {'cached_tokens': 64}})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              stream=httpx.ByteStream(data + b'data: [DONE]\n\n'))

    class Client(ModelStreamClient):
        def __init__(self, policy, **kwargs):
            super().__init__(policy, transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(runtime_module, 'ModelStreamClient', Client)
    runtime = runtime_module.AgentsToolRuntime(allowed_tools=set())
    build = runtime._build_agent
    def with_tool(*args, **kwargs):
        agent, client, metadata = build(*args, **kwargs)
        agent.tools = [touch]
        return agent, client, metadata
    monkeypatch.setattr(runtime, '_build_agent', with_tool)
    options = dict(model='glm-5.3-flash', base_url='https://open.bigmodel.cn/api/coding/paas/v4',
                   api_key='test-key', session_id='conversation', request_id='r1')
    with pytest.raises(httpx.ReadTimeout):
        async for event in runtime.stream('write file', **options): pass
    events = [event async for event in runtime.stream('continue', **{**options, 'request_id': 'r2'})]
    messages = requests[-1]['messages']
    assert messages[:len(requests[1]['messages'])] == requests[1]['messages']
    assert any(m.get('role') == 'tool' and m.get('content') == 'confirmed file write' for m in messages)
    assert any('回复中断' in str(m.get('content', '')) for m in messages)
    assert effects == ['written']
    usage = next(e.data for e in events if e.event.value == 'usage')
    assert usage['protocolSession'] is True and usage['cached_tokens'] == 64
    assert usage['last_input_tokens'] == 100
    assert any(e.event.value == 'model_context' and e.data['requestBodyBytes'] > 0 for e in events)
    timings = usage['responseTimings']
    assert 0 <= timings['contextPreparationMs'] <= timings['firstContentMs'] <= usage['latencyMs']
    assert 0 <= timings['providerHeadersMs'] <= timings['providerFirstByteMs']
    assert all(e.data['delta'] for e in events if e.event.value == 'content_delta')
