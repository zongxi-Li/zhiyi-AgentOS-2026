"""Offline warm-path measurement. Constructs clients; never sends HTTP/model input."""
import json
from pathlib import Path
import time
from types import SimpleNamespace

from agents.run import ModelInputData

from app.llm import chat_session
from app.tools.runtime import AgentsToolRuntime
from app.context_compaction.runtime import build_input_filter


async def test_warm_preparation_reads_only_the_working_suffix(tmp_path,monkeypatch):
    monkeypatch.setattr(chat_session,'APP_DATA_DIR',tmp_path)
    monkeypatch.setattr(chat_session,'current_trusted_user',lambda:SimpleNamespace(user_id='profile',tenant_id='offline'))
    model='glm-5.3-flash'; base='https://open.bigmodel.cn/api/coding/paas/v4'
    def session(): return chat_session.open_chat_session('offline-profile',model,base,None,None)
    raw=[{'role':'user','content':'synthetic input'}]
    for i in range(100): raw.extend([
        {'type':'function_call','call_id':f'c{i}','name':'read_file','arguments':'{}'},
        {'type':'function_call_output','call_id':f'c{i}','output':'x'*8192}])
    checkpoint={'role':'user','content':'Historical checkpoint fixture; no model was called.'}
    async with session() as target:
        await target.add_items(raw)
        original=await target.get_items()
        assert await target.commit_projection(original,[checkpoint]+raw[-10:],{})
    runtime=AgentsToolRuntime(allowed_tools=[])
    spans=[]; client_spans=[]
    for _ in range(21):
        started=time.perf_counter()
        async with session() as target:
            working=await target.get_items()
            assert target.last_view.metadata['journalReadItems']==0
            context=runtime._context(provider='glm',session_id='offline-profile')
            agent,client,metadata=runtime._build_agent(context,model=model,base_url=base,api_key='offline-unused',
                require_evidence=False,thinking_mode='deep',parameters={'reasoning_effort':'max'})
            projection=build_input_filter(agent=agent,context_id='offline-profile',model=model,base_url=base,api_key='offline-unused')
            async def forbidden(**_): raise AssertionError('This profile must not call a model')
            projection.invoke=forbidden
            try:
                result=await projection.project(ModelInputData(input=working,instructions=agent.instructions),local_only=True)
                assert result.input==working and projection.process is None
                assert agent.model_settings.extra_body.get('reasoning_effort')=='max'
                client_spans.append(metadata['_preparationTimings']['httpClientBuildMs'])
            finally:
                await projection.close(); await client.close()
        spans.append(round((time.perf_counter()-started)*1000,2))
    report={'source':'offline-synthetic-no-model-call','archivedItems':len(raw),'workingItems':len(working),
        'journalReadItems':0,'coldPreparationMs':spans[0], 'warmPreparationP50Ms':sorted(spans[1:])[9],
        'warmPreparationP95Ms':sorted(spans[1:])[18], 'clientConstructionMs':client_spans,
        'scope':'journal-open/projection-read/agent-client-build/local-input-filter; excludes SDK send and provider'}
    (Path(__file__).resolve().parents[3]/'.tmp-tests/oscode-context-preparation-profile.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
