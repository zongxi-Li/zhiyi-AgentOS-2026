"""Workbench metrics read existing call records without replaying model work."""
import json
from types import SimpleNamespace

from app.api.agentos_v2 import _model_call_projection
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from runtime import ExecutionRuntime
from runtime.compatibility import RunLockManager
from components.auditor.governance.trace import TraceStore


def test_missing_usage_is_unknown_and_latest_input_is_separate_from_total():
    trace = [SimpleNamespace(event_type='model_called', event_id='one', step_id='node',
        created_at='2026-11-14T00:00:00Z', payload={'model': 'first', 'usage': {'prompt_tokens': 17, 'total_tokens': 9999},
        'capability': {'contextWindowTokens': 1000}}),
        SimpleNamespace(event_type='model_called', event_id='two', step_id=None,
        created_at='2026-11-14T00:00:01Z', payload={'scope': 'planning', 'usage': {},
        'requestDiagnostics': {'requestBudget': {'estimatedInputTokens': 123, 'estimator': 'test', 'totalTokens': 2000}}})]
    calls = _model_call_projection(SimpleNamespace(trace=trace))
    assert calls[0]['contextUsage']['inputTokens'] == 17
    assert calls[0]['contextUsage']['measurement'] == 'provider'
    assert calls[0]['usage']['totalTokens'] == 9999
    assert calls[1]['contextUsage']['inputTokens'] == 123
    assert calls[1]['contextUsage']['measurement'] == 'estimate'
    assert calls[1]['usageReported'] is False
    trace[-1].payload = {}
    assert _model_call_projection(SimpleNamespace(trace=trace))[-1]['contextUsage']['inputTokens'] is None


def test_copilot_call_projection_is_not_limited_by_chat_pages_or_mixed_across_runs(tmp_path):
    for store in (MemoryWorkflowStore(), SQLiteWorkflowStore(tmp_path / 'runs.db')):
        runtime = SimpleNamespace(workflow_store=store, run_lock_manager=RunLockManager(), trace_store=TraceStore())
        store.save_mission(RuntimeMissionRecord(missionId='mission', title='Metrics'))
        for run_id in ('a', 'b'):
            store.save_run(RuntimeRunRecord(runId=run_id, missionId='mission', workflowId='test', domain='test',
                runtimeEngine='acg', executionState={'planningDeferred': True}))
        for i in range(105):
            store.save_copilot_exchange('a', str(i), {'createdAt': f'2026-11-14T00:{i//60:02}:{i%60:02}Z',
                'user': 'PRIVATE-CONVERSATION', 'assistant': 'PRIVATE-CONTENT'})
            ExecutionRuntime.record_model_invocations(runtime, 'a', [{'model': 'mock',
                'usage': {'prompt_tokens': i + 1, 'completion_tokens': 1}, 'prompt': 'PRIVATE-PROMPT'}], scope='copilot')
        ExecutionRuntime.record_model_invocations(runtime, 'b', [{'model': 'FOREIGN'}], scope='copilot')
        calls = _model_call_projection(store.get_run('a'))
        assert len(calls) == 105 and len({call['callId'] for call in calls}) == 105
        assert 'PRIVATE' not in json.dumps(calls, default=str) and 'FOREIGN' not in json.dumps(calls, default=str)
        assert calls[-1]['contextUsage']['inputTokens'] == 105
        assert sum(call['usage']['inputTokens'] for call in calls) == sum(range(1, 106))
        assert all(call['scope'] == 'copilot' for call in calls)
