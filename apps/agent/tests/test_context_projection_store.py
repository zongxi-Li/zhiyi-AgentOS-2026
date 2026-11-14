"""Scoped durable cursors/CAS and actual SDK delivery, no live provider requests."""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
from agents import Agent, Runner
from agents.run import RunConfig

from app.llm import chat_session
from app.config import settings
from app.context_compaction.runtime import TypeScriptInputFilter
from app.tools.chat_catalog import ChatToolCatalog
from agents.run import ModelInputData
from test_compaction_protocol_delivery import RecordingModel


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_session,'APP_DATA_DIR',tmp_path)
    user=SimpleNamespace(user_id='owner',tenant_id='tenant')
    monkeypatch.setattr(chat_session,'current_trusted_user',lambda:user)
    monkeypatch.setattr(settings,'OSCODE_CONTEXT_COMPACTION_MODELS',{})
    return user


def session(history=None, model='mock'):
    return chat_session.open_chat_session('ctx',model,'https://mock.test',None,history)


def source():
    return [{'role':role,'content':f'{i} historical evidence '+'x'*2000}
            for i in range(8) for role in ('user','assistant')]


async def summarize(**_):
    return {'text':json.dumps({k:['keep REST'] if k=='facts' else [] for k in
        ('goals','facts','constraints','completed','decisions','unresolved','references','tool_results')})}


def hook(target, invoke=summarize):
    return TypeScriptInputFilter(context_id='ctx',model='mock',base_url='https://mock.test',api_key='unused',
        budget={'contextWindow':100000,'outputReserve':1000,'safetyMargin':500,
                'workingSetTriggerTokens':16000,'workingSetTargetTokens':10000},
        config={'retainTurns':1,'retainRatio':0,'maxSummaryCalls':2},tools=[],session=target,invoke=invoke)


async def test_sdk_filter_commit_survives_new_session_and_only_reads_suffix(journal):
    model=RecordingModel(); agent=Agent(name='test',instructions='fixed rules',model=model)
    calls=[]
    async def counted(**kwargs):
        calls.append(True); return await summarize(**kwargs)
    raw=source()
    async with session(raw) as target:
        projection=hook(target,counted)
        try:
            await Runner.run(agent,input='continue',session=target,run_config=RunConfig(call_model_input_filter=projection))
            assert await target.flush_projection()
            assert target.last_view.version==1
        finally: await projection.close()
    async with session([{'role':'user','content':'wrong UI bootstrap'}]) as restored:
        working=await restored.get_items()
        assert 'checkpoint' in working[0]['content']
        assert restored.last_view.metadata['journalReadItems']==1 # only the latest model reply
        assert await chat_session.SQLiteSession.get_items(restored)==raw+[
            {'role':'user','content':'continue'}, *[i for i in await chat_session.SQLiteSession.get_items(restored) if i.get('id')=='reply']]
        projection=hook(restored,counted)
        try:
            await Runner.run(agent,input='next',session=restored,run_config=RunConfig(call_model_input_filter=projection))
            await restored.flush_projection()
        finally: await projection.close()
        assert 'checkpoint' in model.inputs[-1][0]['content']
        assert len(calls)==1 # the same archived prefix is not summarized again


async def test_tail_append_allowed_stale_branch_and_cas_rejected(journal):
    async with session(source()) as target:
        source_view=await target.get_items(); snapshot=target.last_view
        await target.add_items([{'role':'user','content':'later append'}])
        projected=[{'role':'user','content':'synthetic projection'}]
        assert await asyncio.to_thread(target.projection_store.commit,snapshot,source_view,projected,{})
        assert not await asyncio.to_thread(target.projection_store.commit,snapshot,source_view,projected,{})
        await target.get_items(); old=target.last_view
        with sqlite3.connect(target.db_path) as db:
            db.execute("UPDATE agent_messages SET message_data=? WHERE session_id=? AND id=(SELECT min(id) FROM agent_messages WHERE session_id=?)",
                       (json.dumps({'role':'user','content':'branch edit'}),target.session_id,target.session_id))
        assert not await asyncio.to_thread(target.projection_store.commit,old,old.messages,projected,{})
        current=await target.get_items()
        assert current[0]['content']=='branch edit'; assert target.last_view.metadata['projectionVersion']==0


async def test_policy_identity_delete_and_authenticated_bounded_archive(journal,monkeypatch):
    raw=[{'type':'function_call','name':'read_file','call_id':'evidence','arguments':'{}'},
         {'type':'function_call_output','call_id':'evidence','output':'0123456789'*3000}]
    async with session(raw) as target:
        original=await target.get_items()
        assert await target.commit_projection(original,[{'role':'user','content':'checkpoint fixture'}],{})
        payload=await ChatToolCatalog().execute('read_archived_tool_result',{'reference':'journal:evidence','offset':10,'limit':15},protocol_session=target)
        assert payload.data['text']=='012345678901234'; assert payload.data['truncated']
        with pytest.raises(ValueError): target.projection_store.result('evidence',0,20000)
    async with session(model='other') as target:
        with pytest.raises(ValueError,match='NOT_FOUND'): target.projection_store.result('evidence')
    journal.user_id='intruder'
    async with session() as target:
        with pytest.raises(ValueError,match='NOT_FOUND'): target.projection_store.result('evidence')
    journal.user_id='owner'
    monkeypatch.setattr(settings,'OSCODE_CONTEXT_COMPACTION_MODELS',{'https://mock.test::mock':{'working_set_trigger_tokens':64000}})
    async with session() as target:
        assert await target.get_items()==raw # old-policy view cannot be adopted
    chat_session.forget_chat_sessions('ctx')
    async with session() as target:
        assert await target.get_items()==[]


async def test_new_input_cancels_idle_candidate_before_acquiring_session(journal):
    entered=asyncio.Event(); closed=asyncio.Event()
    async with session() as target: identity=target.session_id
    async def idle():
        try:
            async with session():
                entered.set(); await asyncio.Future()
        finally: closed.set()
    chat_session.prepare_when_idle(identity,idle)
    await asyncio.wait_for(entered.wait(),3)
    async with session() as target:
        assert closed.is_set()
        await target.add_items([{'role':'user','content':'new input'}])
    assert identity not in chat_session._idle_jobs


async def test_single_request_usage_anchor_survives_reload_and_rejects_changed_envelope(journal):
    async with session([{'role':'user','content':'old input'}]) as target:
        data=await target.get_items()
        projection=hook(target)
        await projection(SimpleNamespace(model_data=ModelInputData(input=data,instructions='rules')))
        projection.record_usage(SimpleNamespace(prompt_tokens=500))
        await projection.save_usage_anchor()
    async with session() as restored:
        data=await restored.get_items()
        projection=hook(restored)
        try:
            await projection.project(ModelInputData(input=data+[{'role':'user','content':'new'}],instructions='rules'))
            assert projection.last_metrics['tokenMethod']=='single-request-usage+utf8-delta-upper-bound'
            assert projection.last_metrics['inputTokens']>=500
            await projection.project(ModelInputData(input=data,instructions='different rules'))
            assert projection.last_metrics['tokenMethod']=='utf8-upper-bound'
        finally: await projection.close()


async def test_completed_response_is_persisted_as_the_shared_watermark_and_not_counted_twice(journal):
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText
    from agents.models.interface import ModelResponse
    from agents.usage import Usage
    raw = [{'role':'user','content':'question'}]
    response = SimpleNamespace(id='response',output=[ResponseOutputMessage(id='answer',role='assistant',type='message',
        status='completed',content=[ResponseOutputText(type='output_text',text='response '*1000,annotations=[])])])
    replay = ModelResponse(response.output,Usage(),response.id).to_input_items()
    async with session(raw) as target:
        projection = hook(target)
        await target.get_items()
        await projection(SimpleNamespace(model_data=ModelInputData(input=raw,instructions='rules')))
        state = projection.record_usage(SimpleNamespace(prompt_tokens=500,completion_tokens=80))
        assert state['usedTokens']==580
        await projection.record_response(response)
        await target.add_items(replay)
        # The readonly snapshot does not cancel or acquire the active session.
        assert (await chat_session.read_context_usage('ctx','mock','https://mock.test',None))['usedTokens']==580
    async with session() as restored:
        data=await restored.get_items()
        projection=hook(restored)
        measured, method=projection.measure_input(ModelInputData(input=data,instructions='rules'))
        assert measured==580 # response text is covered by the actual completion count
        assert method.startswith('single-request-usage')
        assert restored.last_view.metadata['contextUsage']['source']=='model'
        assert projection.measure_input(ModelInputData(input=data,instructions='changed rules'))[1]=='utf8-upper-bound'
        assert projection.record_usage(SimpleNamespace(prompt_tokens=None)) is None


async def test_provider_baseline_reaches_worker_even_when_full_utf8_input_exceeds_hard_limit(journal):
    import hashlib
    from app.context_compaction.runtime import _wire
    raw=[{'role':'user','content':'large content '*12000}]
    async with session(raw) as target:
        await target.get_items()
        projection=hook(target)
        projection.anchor={'count':1,'prefixHash':hashlib.sha256(_wire(raw).encode()).hexdigest(),
            'fixedHash':projection.fixed_hash('rules'),'inputTokens':20000}
        try:
            result=await projection.project(ModelInputData(input=raw,instructions='rules'))
            assert result.input==raw
            assert projection.last_metrics['inputTokens']==20000
            assert projection.last_metrics['outputTokens']==20000
            assert projection.context_usage['usedTokens']==20000
            assert projection.last_metrics['tokenMethod'].startswith('single-request-usage')
        finally: await projection.close()


async def test_compact_boundary_replaces_the_previous_provider_watermark(journal):
    async with session([{'role':'user','content':'old'}]) as target:
        raw=await target.get_items()
        projection=hook(target)
        await projection(SimpleNamespace(model_data=ModelInputData(input=raw,instructions='rules')))
        projection.record_usage(SimpleNamespace(prompt_tokens=500,completion_tokens=80))
        await projection.save_usage_anchor()
        compact={'usedTokens':100,'maxTokens':100000,'measurement':'upper-bound','source':'compaction'}
        assert await target.commit_projection(raw,[{'role':'user','content':'checkpoint'}],{'contextUsage':compact})
        state=await chat_session.read_context_usage('ctx','mock','https://mock.test',None)
        assert state['usedTokens']==100
        assert state['source']=='compaction'
        assert state['projectionVersion']==1


async def test_corrupt_projection_recovers_from_original_journal(journal):
    raw=source()
    async with session(raw) as target:
        original=await target.get_items()
        assert await target.commit_projection(original,[{'role':'user','content':'fixture'}],{})
        with sqlite3.connect(target.db_path) as db:
            db.execute('UPDATE oscode_context_projections SET projection_json=? WHERE session_id=?',('{broken',target.session_id))
    async with session() as restored:
        assert await restored.get_items()==raw
        assert restored.last_view.metadata['projectionVersion']==0
