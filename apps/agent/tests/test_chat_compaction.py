"""Manual HTTP -> actual TS engine; summary Provider is deterministic and tool-free."""
import copy
import json

import httpx
import pytest
from fastapi import FastAPI

from app.api import chat_compaction
from app.config import settings
from app.tools.runtime import AgentsToolRuntime


@pytest.fixture
def manual(monkeypatch):
    from app.ai_engine import model_runtime
    calls = []

    async def summarize(**kwargs):
        calls.append(kwargs)
        assert 'tools' not in kwargs
        return {'text': json.dumps({key: ['Keep REST and src/main.ts'] if key == 'facts' else []
                                   for key in ('goals', 'facts', 'constraints', 'completed', 'decisions', 'unresolved', 'references', 'tool_results')}),
                'total_tokens': 50}

    monkeypatch.setattr(model_runtime, 'generate_with_runtime_model', summarize)
    monkeypatch.setattr(chat_compaction, 'get_chat_tool_runtime', lambda: AgentsToolRuntime(allowed_tools=[]))
    monkeypatch.setattr(settings, 'OSCODE_CONTEXT_COMPACTION_ENABLED', False)
    monkeypatch.setattr(settings, 'OSCODE_CONTEXT_COMPACTION_MANUAL_ENABLED', True)
    monkeypatch.setattr(settings, 'OSCODE_CONTEXT_COMPACTION_MODELS', {
        'https://mock.test::mock': {'context_window': 1_000_000}})
    app = FastAPI()
    app.include_router(chat_compaction.router, prefix='/ai')
    return app, calls


def payload(rounds=6):
    return {'context_id': 'ctx-manual', 'model': 'mock', 'base_url': 'https://mock.test', 'api_key': 'not-to-node',
            'context': [m for i in range(rounds) for m in (
                {'role': 'user', 'content': f'Keep REST, inspect src/main.ts {i} ' + 'x' * 1500},
                {'role': 'assistant', 'content': 'Keep API stable ' + 'y' * 1500})]}


async def test_manual_http_forces_below_threshold_without_changing_original(manual):
    app, calls = manual
    body = payload(); original = copy.deepcopy(body)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/ai/chat/compact', json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['status'] == 'summarized'
    assert data['metrics']['summaryCalls'] == len(calls) > 0
    assert data['metrics']['outputTokens'] < data['metrics']['inputTokens']
    assert len(data['messages']) == 1
    assert 'checkpoint' in data['messages'][0]['content']
    assert data['contextTokenMethod'] == 'utf8-upper-bound'
    assert data['contextFixedTokens'] > 0
    assert body == original
    assert '/compact' not in str(calls)


@pytest.mark.parametrize('rounds', [1, 2])
async def test_manual_completed_turns_can_be_compacted(manual, rounds):
    app, calls = manual
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/ai/chat/compact', json=payload(rounds))
    assert response.status_code == 200
    assert response.json()['status'] == 'summarized'
    assert response.json()['metrics']['outputTokens'] < response.json()['metrics']['inputTokens']
    assert len(calls) > 0


async def test_manual_short_history_is_noop_and_disabled_is_explicit(manual, monkeypatch):
    app, calls = manual
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = payload(1)
        body['context'] = [{'role': 'user', 'content': 'Hi'}, {'role': 'assistant', 'content': 'Hello'}]
        response = await client.post('/ai/chat/compact', json=body)
        assert response.status_code == 200
        assert response.json()['status'] == 'unchanged'
        assert response.json()['metrics']['reasonCode'] == 'INSUFFICIENT_SAVINGS'
        assert not calls
        monkeypatch.setattr(settings, 'OSCODE_CONTEXT_COMPACTION_MANUAL_ENABLED', False)
        assert (await client.post('/ai/chat/compact', json=payload())).status_code == 503


async def test_manual_unknown_budget_rejects_without_provider_call(manual, monkeypatch):
    app, calls = manual
    monkeypatch.setattr(settings, 'OSCODE_CONTEXT_COMPACTION_MODELS', {})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/ai/chat/compact', json=payload())
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'COMPACTION_CONFIG_REQUIRED'
    assert not calls


async def test_manual_provider_failure_returns_original_context(manual, monkeypatch):
    from app.ai_engine import model_runtime
    async def failed(**_):
        raise RuntimeError('provider unavailable')
    app, _ = manual
    monkeypatch.setattr(model_runtime, 'generate_with_runtime_model', failed)
    body = payload()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/ai/chat/compact', json=body)
    assert response.status_code == 200
    assert response.json()['status'] == 'failed_passthrough'
    assert response.json()['metrics']['failureCode'] == 'SUMMARY_PROVIDER_FAILED'
    assert response.json()['messages'] == body['context']


async def test_manual_command_uses_durable_protocol_and_survives_browser_reload(manual, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app.llm import chat_session
    app,calls=manual
    monkeypatch.setattr(chat_session,'APP_DATA_DIR',tmp_path)
    monkeypatch.setattr(chat_session,'current_trusted_user',lambda:SimpleNamespace(user_id='owner',tenant_id='tenant'))
    body=payload(); raw=body['context']
    async with chat_session.open_chat_session(body['context_id'],'mock',body['base_url'],None,raw): pass
    # Old page display context cannot override the protocol journal.
    body['context']=[{'role':'user','content':'stale display data'}]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/ai/chat/compact',json=body)
    assert response.status_code==200, response.text
    data=response.json()
    assert data['durable'] is True and data['projectionVersion']==1 and data['status']=='summarized'
    assert 'stale display data' not in str(calls)
    async with chat_session.open_chat_session(body['context_id'],'mock',body['base_url'],None,[]) as restored:
        assert await restored.get_items()==data['messages']
        assert await chat_session.SQLiteSession.get_items(restored)==raw
