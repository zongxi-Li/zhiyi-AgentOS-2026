"""Regression guards for durable tool evidence and wrapper authority propagation.

Real Windows service/desktop acceptance is recorded separately; these tests do
not substitute for it.
"""
import pytest
from adapters.audited_tool_runtime import AuditedToolRuntime
from adapters.guarded_tool import GuardedToolRuntime
from components.executor.value_store import SQLiteExecutionValueStore, ExecutionValueAccessError
from types import SimpleNamespace
from adapters.hands_http import receipt_checksum


def test_tool_values_are_immutable_run_owned_and_survive_reopen(tmp_path):
    db = str(tmp_path / 'values.sqlite3')
    store = SQLiteExecutionValueStore(db_path=db)
    ref = store.put_tool_value(run_id='run-a', step_id='step-a', key='op', payload={'executionId':'hands-a'})
    assert ref == store.put_tool_value(run_id='run-a', step_id='step-a', key='op', payload={'executionId':'hands-a'})
    with pytest.raises(ValueError, match='immutable'):
        store.put_tool_value(run_id='run-a', step_id='step-a', key='op', payload={'executionId':'hands-b'})
    with pytest.raises(ExecutionValueAccessError):
        store.get_output(run_id='run-b', output_ref=ref)
    store.close()
    reopened = SQLiteExecutionValueStore(db_path=db)
    assert reopened.get_tool_value(run_id='run-a', key='op') == {'executionId':'hands-a'}
    assert reopened.get_tool_value(run_id='run-b', key='op') is None
    reopened.close()


@pytest.mark.asyncio
async def test_node_context_and_guard_cross_both_wrappers_without_bypassing_audit():
    checks = []
    class Delegate:
        def bind_context(self, context, guard):
            self.context, self.guard = context, guard
            return self
        async def execute(self, name, arguments, **kwargs):
            self.guard()
            return self.context
    delegate = Delegate()
    tools = AuditedToolRuntime(delegate=GuardedToolRuntime(delegate=delegate), allowed_tools=['write_file'])
    bound = tools.bind_context('frozen-node-context', lambda: checks.append('permit'))
    assert await bound.execute('write_file', {}) == 'frozen-node-context'
    assert checks == ['permit']
    assert bound.events == [{'type':'tool_called','tool':'write_file'}]
    with pytest.raises(PermissionError):
        await bound.execute('undeclared_shell', {})


@pytest.mark.asyncio
async def test_receipt_observations_only_consume_declared_context_refs(tmp_path):
    from app.tools.formal_workspace import FormalWorkspaceTools
    store = SQLiteExecutionValueStore(db_path=tmp_path/'values.sqlite3')
    identity={'runId':'r','stepId':'producer','attemptId':'a','commitId':'c'}
    receipt={'identity':identity,'status':'completed','output':{'text':'actual bytes'}}
    receipt['checksum']=receipt_checksum(receipt)
    ref=store.put_tool_value(run_id='r',step_id='producer',key='receipt',payload=receipt)
    store.put_tool_value(run_id='r',step_id='unrelated',key='private',payload={'mustNotAppear':True})
    record={'receiptRef':ref,'receiptChecksum':receipt['checksum'],'executionId':'execution',**identity}
    context=SimpleNamespace(run=SimpleNamespace(run_id='r'),context_pack=SimpleNamespace(data={'execution_receipts':[record]}))
    tools=FormalWorkspaceTools.__new__(FormalWorkspaceTools)
    tools.context=context;tools.guard=lambda:None;tools.runtime=SimpleNamespace(execution_value_store=store)
    observations=await tools.verified_observations(context)
    assert len(observations)==1 and observations[0]['content']==receipt
    context.context_pack.data={}
    assert await tools.verified_observations(context)==[]
    record['receiptChecksum']='invalid'
    context.context_pack.data={'execution_receipts':[record]}
    with pytest.raises(RuntimeError,match='CHECKSUM'):
        await tools.verified_observations(context)
    store.close()


@pytest.mark.asyncio
async def test_workspace_loop_stops_after_real_pytest_without_model_finish(tmp_path):
    """Loop regression only; signed Windows desktop acceptance is separate."""
    import asyncio
    import sys
    from packs.workspace import WorkspaceDeveloper
    store=SQLiteExecutionValueStore(db_path=tmp_path/'values.sqlite3')
    class ModelThatNeverFinishes:
        calls=0
        async def generate_json(self,**kwargs):
            self.calls+=1
            return SimpleNamespace(data={'actions':[
                {'tool':'write_file','arguments':{'path':'sample.py','contentLines':['def twice(x): return x * 2']},'summary':'source'},
                {'tool':'write_file','arguments':{'path':'test_sample.py','contentLines':['from sample import twice','def test_twice(): assert twice(3) == 6']},'summary':'test'},
                {'tool':'run_tests','arguments':{'path':'.'},'summary':'real pytest'}]},audit_record=lambda:{})
    class RealTemporaryFileAndPytestFixture:
        runtime=SimpleNamespace(execution_value_store=store)
        async def execute(self,name,arguments,**kwargs):
            data={'status':'completed'}
            if name=='write_file': (tmp_path/arguments['path']).write_text(arguments['content'],encoding='utf-8')
            elif name=='read_file': data['content']=(tmp_path/arguments['path']).read_text(encoding='utf-8')
            elif name=='run_tests':
                child=await asyncio.create_subprocess_exec(sys.executable,'-m','pytest','-q','test_sample.py',
                    cwd=tmp_path,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                stdout,stderr=await child.communicate()
                data.update(exitCode=child.returncode,stdout=stdout.decode(),stderr=stderr.decode())
            return SimpleNamespace(data=data,record={'tool':name,'status':'completed'})
    model=ModelThatNeverFinishes()
    context=SimpleNamespace(tool_runtime=AuditedToolRuntime(delegate=RealTemporaryFileAndPytestFixture(),
        allowed_tools=['write_file','read_file','run_tests']),model_runtime=model,
        mission_intent_basis=SimpleNamespace(objective='Write source and real pytest tests'),
        run=SimpleNamespace(run_id='loop-regression'),step=SimpleNamespace(step_id='developer',name='implement'),commit_id='commit')
    result=await WorkspaceDeveloper().run(context)
    assert model.calls==1
    assert result.output['test_results'][-1]['exitCode']==0
    assert '1 passed' in result.output['test_results'][-1]['stdout']
    assert [r['tool'] for r in result.tool_executions][-2:]==['read_file','read_file']
    store.close()
