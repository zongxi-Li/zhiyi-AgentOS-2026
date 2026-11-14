"""Actual TS checkpoint -> durable SDK journal -> subsequent model requests."""
import copy
import json
from types import SimpleNamespace

import pytest
from agents import Agent, Runner
from agents.models.interface import Model, ModelResponse
from agents.run import ModelInputData
from agents.usage import Usage
from openai.types.responses import ResponseOutputMessage, ResponseOutputText

from app.context_compaction.protocol import FIELDS, is_checkpoint
from app.context_compaction.runtime import TypeScriptInputFilter
from app.llm import chat_session


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_session, 'APP_DATA_DIR', tmp_path)
    monkeypatch.setattr(chat_session, 'current_trusted_user', lambda: SimpleNamespace(user_id='test', tenant_id='test'))


def session(history=None, projection=False):
    return chat_session.open_chat_session('test', 'mock', 'https://test.invalid', None, history, projection)


def history():
    return [{'role': role, 'content': f'{turn} ' + 'historical data ' * 100}
            for turn in range(4) for role in ('user', 'assistant')]


async def compact(raw):
    async def summarize(**kwargs):
        assert kwargs['parameters']['response_format'] == {'type': 'json_object'}
        assert 'tools' not in kwargs
        summary = {key: ['Confirmed old file write; inspect actual state before changing it.'] if key == 'facts' else []
                   for key in FIELDS}
        return {'text': '```json\n' + json.dumps(summary) + '\n```'}
    projection = TypeScriptInputFilter(context_id='test', model='mock', base_url='https://test.invalid', api_key='',
        budget={'contextWindow': 64000, 'outputReserve': 2048, 'safetyMargin': 512},
        config={}, tools=[], invoke=summarize)
    try:
        result = await projection.project(ModelInputData(input=raw, instructions='trusted rules'), force=True)
        assert projection.last_metrics['status'] == 'summarized'
        assert is_checkpoint(result.input[0])  # Detect TS/Python contract drift.
        return result.input
    finally:
        await projection.close()


class RecordingModel(Model):
    def __init__(self):
        self.inputs = []

    async def get_response(self, system_instructions, input, *args, **kwargs):
        self.inputs.append(copy.deepcopy(input))
        return ModelResponse(output=[ResponseOutputMessage(id='reply', role='assistant', type='message', status='completed',
            content=[ResponseOutputText(type='output_text', text='ok', annotations=[])])],
            usage=Usage(requests=1, input_tokens=10, output_tokens=1, total_tokens=11), response_id='response')

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


async def test_real_checkpoint_is_delivered_across_turns_without_rewriting_or_replaying_tools(journal):
    raw = history()
    raw[1:1] = [
        {'type': 'function_call', 'call_id': 'write', 'name': 'write_file', 'arguments': '{"path":"old.txt"}'},
        {'type': 'function_call_output', 'call_id': 'write', 'output': 'confirmed write'},
    ]
    original = copy.deepcopy(raw)
    async with session(history=raw):
        pass
    projection = await compact(raw)
    assert len(projection) == 1 and projection[0]['role'] == 'user'
    model = RecordingModel()
    agent = Agent(name='test', instructions='trusted rules', model=model)
    async with session(history=projection, projection=True) as target:
        result = await Runner.run(agent, input='continue', session=target)
    assert result.final_output == 'ok'
    assert model.inputs[0][0] == projection[0]
    assert model.inputs[0][-1] == {'role': 'user', 'content': 'continue'}
    assert not any(item.get('type') in {'function_call', 'function_call_output'} for item in model.inputs[0])
    async with session() as source:
        saved = await source.get_items()
    assert saved[:len(original)] == original
    assert not any(is_checkpoint(item) for item in saved)
    following = projection + [{'role': 'user', 'content': 'continue'}, {'role': 'assistant', 'content': 'ok'}]
    async with session(history=following, projection=True) as target:
        await Runner.run(agent, input='next', session=target)
    assert model.inputs[1][0] == projection[0]
    assert [item['content'] for item in model.inputs[1] if item.get('role') == 'user'][1:] == ['continue', 'next']
    async with session() as source:
        assert (await source.get_items())[:len(original)] == original


async def test_real_checkpoint_retains_the_full_confirmed_tool_tail_and_rejects_changed_users(journal):
    raw = history() + [{'role': 'user', 'content': 'protected current turn'},
        {'type': 'function_call', 'call_id': 'read', 'name': 'read_file', 'arguments': '{}'},
        {'type': 'function_call_output', 'call_id': 'read', 'output': 'confirmed result'}]
    async with session(history=raw):
        pass
    projection = await compact(raw)
    async with session(history=projection, projection=True) as target:
        assert await target.get_items() == projection[:1] + raw[-3:]
    changed = copy.deepcopy(projection)
    changed[1]['content'] = 'changed current turn'
    async with session(history=changed, projection=True) as target:
        with pytest.raises(ValueError, match='CHAT_CONTEXT_PROJECTION_STALE'):
            await target.get_items()
