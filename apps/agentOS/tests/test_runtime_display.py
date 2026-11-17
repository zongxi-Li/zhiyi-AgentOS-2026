import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from contracts.runtime_events import RuntimeEvent
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
from runtime.live_events import RuntimeEventBroker, RuntimeEventOverflow
from runtime.runtime_display import RuntimeDisplayProjection, public_narrative
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


def event(kind, payload=None, attempt="a1", node="node"):
    return RuntimeEvent(eventType=kind, runId="run", nodeId=node, attemptId=attempt,
                        sequence=0, payload=payload or {})


@pytest.mark.parametrize("modules", [
    "import components.planner.complexity; import runtime.live_events",
    "import runtime.live_events; import components.planner.complexity",
])
def test_planner_and_display_can_be_imported_independently(modules):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", modules], cwd=root,
                            env={**os.environ, "PYTHONPATH": str(root / "src")}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def store_at(path):
    store = SQLiteWorkflowStore(path)
    store.save_mission(RuntimeMissionRecord(missionId="mission", title="Display"))
    store.save_run(RuntimeRunRecord(runId="run", missionId="mission", workflowId="test", domain="test",
                                   runtimeEngine="acg", executionState={"planningDeferred": True}))
    return store


def test_paused_authority_diagnostic_survives_restart_without_mutating_run(tmp_path):
    store = store_at(tmp_path / "paused.db")
    original = store.get_run("run").model_dump_json()
    revision = store.workspace_projection_revision("mission")
    broker = RuntimeEventBroker(store=store)
    safe = {"stage": "workspace_review", "status": "blocked", "errorCode": "INVALID_PROPOSAL",
        "errorType": "_TransitionRejected", "activationId": "activation:2", "observationId": "observation:1",
        "graphVersion": 2, "authorityReason": "current origin differs from accepted frozen provenance"}
    broker.publish_from_thread("run", event("workspace.review.blocked", {
        **safe, "patch": {"private": "PRIVATE"}, "arguments": {"secret": "PRIVATE"},
        "rawResponse": "PRIVATE"}, attempt=None, node=None))
    restarted = SQLiteWorkflowStore(store.db_path)
    saved = restarted.get_runtime_display("run")
    assert saved["events"][-1]["payload"] == safe
    assert "PRIVATE" not in json.dumps(saved)
    assert restarted.get_run("run").model_dump_json() == original
    assert restarted.workspace_projection_revision("mission") == revision


def test_planner_reasoning_reaches_live_subscribers_without_entering_display_checkpoints(tmp_path):
    async def run():
        store = store_at(tmp_path / 'reasoning.db')
        broker = RuntimeEventBroker(store=store)
        stream = broker.subscribe('run')
        await anext(stream)
        await broker.publish('run', event('planner.model.reasoning.delta',
            {'delta': '先核对约束', 'callKey': 'outline', 'stage': 'outline'}, attempt=None, node=None))
        live = await anext(stream)
        assert live.event_type == 'planner.model.reasoning.delta'
        assert live.payload['delta'] == '先核对约束'
        broker.flush()
        saved = store.get_runtime_display('run')
        assert '先核对' not in json.dumps(saved, ensure_ascii=False)
        assert all(item['eventType'] != 'planner.model.reasoning.delta' for item in saved['events'])
        await stream.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("source, expected", [
    ('{"content":"hello', 'hello'),
    ('{"content":"hi\\nworld", "reasoning_content":"PRIVATE"}', 'hi\nworld'),
    ('{"action":{"kind":"rerun","arguments":"PRIVATE"},"content":"公开"}', '公开'),
    ('{"content":"\\u4f60\\u597d\\u', '你好'),
    ('{"reasoning":{"content":"PRIVATE"},"summary":"公开"}', '公开'),
])
def test_only_public_narrative_is_checkpointed(source, expected):
    assert public_narrative(source) == expected


def test_restart_recovers_public_text_and_watermark_without_run_mutation(tmp_path):
    async def run():
        store = store_at(tmp_path / 'runs.db')
        revision = store.workspace_projection_revision('mission')
        original = store.get_run('run').model_dump_json()
        broker = RuntimeEventBroker(store=store)
        await broker.publish('run', event('model.started'))
        await broker.publish('run', event('model.output.delta', {'delta': '{"content":"公开","reasoning_content":"PRIVATE"}'}))
        await broker.publish('run', event('model.completed', {'data': {'secret': 'PRIVATE'}}))
        saved = store.get_runtime_display('run')
        assert 'PRIVATE' not in json.dumps(saved)
        restarted = RuntimeEventBroker(store=SQLiteWorkflowStore(store.db_path))
        stream = restarted.subscribe('run')
        baseline = await anext(stream)
        assert baseline.sequence == saved['sequence']
        output = next(e for e in baseline.payload['events'] if e['eventType'] == 'model.output.delta')
        assert output['payload']['publicText'] == '公开'
        await restarted.publish('run', event('node.completed'))
        assert (await anext(stream)).sequence > baseline.sequence
        assert store.get_run('run').model_dump_json() == original
        assert store.workspace_projection_revision('mission') == revision
        await stream.aclose()
    asyncio.run(run())


def test_validation_diagnostics_survive_snapshot_restore_without_model_text(tmp_path):
    async def run():
        store = store_at(tmp_path / 'runs.db')
        broker = RuntimeEventBroker(store=store)
        issue = {'stage': 'repair', 'callKey': 'repair', 'code': 'acceptance_criteria_required',
                 'fieldPath': ['tasks', 0, 'acceptanceCriteria'], 'message': 'PRIVATE_MODEL_TEXT'}
        await broker.publish('run', event('planner.failed', {'validationFailures': [issue]}, attempt=None, node=None))
        broker.flush()
        restarted = RuntimeEventBroker(store=SQLiteWorkflowStore(store.db_path))
        stream = restarted.subscribe('run')
        baseline = await anext(stream)
        failure = next(item for item in baseline.payload['events'] if item['eventType'] == 'planner.failed')
        expected = {key: value for key, value in issue.items() if key != 'message'}
        assert failure['payload']['validationFailures'] == [expected]
        assert 'PRIVATE_MODEL_TEXT' not in json.dumps(baseline.payload)
        await stream.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("kind,status", [
    ("workspace.review.blocked", "blocked"),
    ("workspace.review.retry", "retrying"),
    ("workspace.review.resumed", "resumed"),
])
def test_workspace_review_diagnostics_replay_independently_with_only_safe_fields(tmp_path, kind, status):
    async def run():
        store = store_at(tmp_path / 'review.db')
        original = store.get_run('run').model_dump_json()
        revision = store.workspace_projection_revision('mission')
        broker = RuntimeEventBroker(store=store)
        await broker.publish('run', event('planner.model.started',
            {'stage': 'outline', 'callKey': 'outline'}, attempt=None, node=None))
        await broker.publish('run', event('planner.model.output.delta',
            {'publicText': '已收到的公开规划', 'callKey': 'outline'}, attempt=None, node=None))
        await broker.publish('run', event('workspace.review.blocked', {
            'stage': 'workspace_review', 'status': 'blocked', 'errorCode': 'OLD_REVIEW_FAILURE',
        }, attempt=None, node=None))
        expected = {'stage': 'workspace_review', 'status': status}
        if kind != 'workspace.review.resumed':
            expected['errorCode'] = 'REVIEW_EVIDENCE_MISSING'
        await broker.publish('run', event(kind, {
            **expected,
            'callKey': 'PRIVATE_CALL', 'delta': 'PRIVATE_MODEL_TEXT',
            'nodes': [{'key': 'PRIVATE_NODE', 'title': 'PRIVATE_TITLE'}],
            'validationFailures': [{'code': 'PRIVATE_DIAGNOSTIC'}],
            'agentRegistration': {'agentId': 'PRIVATE_AGENT'},
        }, attempt=None, node=None))
        broker.flush()
        saved = store.get_runtime_display('run')
        projection = RuntimeDisplayProjection(saved)
        assert projection.current['planner'] == 'outline'
        assert projection.current['workspace_review'] == 'workspace_review'
        assert 'PRIVATE' not in json.dumps(saved)
        restarted = RuntimeEventBroker(store=SQLiteWorkflowStore(store.db_path))
        stream = restarted.subscribe('run')
        baseline = await anext(stream)
        diagnostic = next(item for item in baseline.payload['events'] if item['eventType'] == kind)
        assert diagnostic['payload'] == expected
        planning = next(item for item in baseline.payload['events']
                        if item['eventType'] == 'planner.model.output.delta')
        assert planning['payload']['publicText'] == '已收到的公开规划'
        assert store.get_run('run').model_dump_json() == original
        assert store.workspace_projection_revision('mission') == revision
        await stream.aclose()
    asyncio.run(run())


def test_handshake_has_no_gap_and_slow_consumer_rebaselines_all_text(tmp_path):
    async def run():
        store = store_at(tmp_path / 'runs.db')
        broker = RuntimeEventBroker(max_queue_size=1, store=store)
        stream = broker.subscribe('run')
        assert (await anext(stream)).event_type == 'runtime.display.snapshot'
        await broker.publish('run', event('model.output.delta', {'delta': '{"content":"A'}))
        await broker.publish('run', event('model.output.delta', {'delta': 'B'}))
        await broker.publish('run', event('model.activity'))
        with pytest.raises(RuntimeEventOverflow):
            await anext(stream)
        replacement = broker.subscribe('run')
        baseline = await anext(replacement)
        output = next(e for e in baseline.payload['events'] if e['eventType'] == 'model.output.delta')
        assert output['payload']['publicText'] == 'AB'
        await broker.publish('run', event('model.output.delta', {'delta': 'C"}'}))
        live = await anext(replacement)
        assert live.payload['publicText'] == 'ABC'
        assert live.sequence > baseline.sequence
        await replacement.aclose()
        broker.flush()
    asyncio.run(run())


def test_attempt_identity_terminal_and_bounds(tmp_path):
    projection = RuntimeDisplayProjection()
    sequence = 0
    def apply(value):
        nonlocal sequence
        sequence += 1
        return projection.apply(value.model_copy(update={'sequence': sequence}))
    apply(event('model.started'))
    apply(event('model.output.delta', {'delta': '{"content":"old"}'}))
    apply(event('model.started', attempt='a2'))
    apply(event('model.output.delta', {'delta': '{"content":"new"}'}, attempt='a2'))
    assert apply(event('model.output.delta', {'delta': 'late'}, attempt='a1')) is None
    for i in range(40):
        apply(event('model.started', attempt=f'new-{i}'))
        apply(event('model.output.delta', {'delta': '{"content":"' + 'x' * 65536}, attempt=f'new-{i}'))
    assert len(projection.events) <= 256
    assert sum(len(e['payload'].get('publicText', '')) for e in projection.events) <= 262144
    apply(event('run.cancelled', attempt=None, node=None))
    assert apply(event('model.output.delta', {'delta': 'late'})) is None


def test_same_run_formal_resume_rebases_terminal_and_retires_old_attempts(tmp_path):
    from contracts.workflow import WorkflowStatus, WorkflowStep
    store = store_at(tmp_path / 'resume.db')
    broker = RuntimeEventBroker(store=store)
    broker.publish_from_thread('run', event('model.started'))
    broker.publish_from_thread('run', event('model.output.delta', {'publicText': 'previous evidence'}))
    broker.publish_from_thread('run', event('node.failed'))
    run = store.get_run('run')
    run.status = WorkflowStatus.FAILED
    store.save_run(run)
    broker.publish_from_thread('run', event('run.failed', node=None, attempt=None))
    terminal = broker.snapshot('run')
    assert terminal.payload['events'][-1]['eventType'] == 'run.failed'

    run.status = WorkflowStatus.RETRYING
    run.steps = [WorkflowStep(stepId='node', name='Review', agentName='agent', status='retrying')]
    run.execution_state['attemptIds'] = {'node:1:root': 'a1'}
    store.save_run(run)
    broker.bind_run('run', store)
    resumed = broker.snapshot('run')
    assert resumed.sequence > terminal.sequence
    assert not any(item['eventType'] == 'run.failed' for item in resumed.payload['events'])
    assert any(item['eventType'] == 'node.failed' for item in resumed.payload['events'])
    assert resumed.payload['retiredAttempts']['node'] == ['a1']
    broker.flush()

    # Restart before the next Attempt emits anything; the old identity stays retired.
    restarted = RuntimeEventBroker(store=SQLiteWorkflowStore(store.db_path))
    restarted.bind_run('run', store)
    restarted.publish_from_thread('run', event('run.failed', node=None, attempt=None))
    restarted.publish_from_thread('run', event('model.output.delta', {'publicText': 'late old output'}))
    restarted.publish_from_thread('run', event('model.started', attempt='a2'))
    restarted.publish_from_thread('run', event('model.output.delta', {'publicText': 'new evidence'}, attempt='a2'))
    restarted.publish_from_thread('run', event('model.completed', attempt='a2'))
    values = restarted.snapshot('run').payload['events']
    assert not any(item['eventType'] == 'run.failed' for item in values)
    assert 'late old output' not in json.dumps(values)
    assert any(item['payload'].get('publicText') == 'new evidence' for item in values)
    restarted.flush()


def test_model_activity_cannot_reopen_a_durably_failed_run(tmp_path):
    from contracts.workflow import WorkflowStatus
    store = store_at(tmp_path / 'failed.db')
    run = store.get_run('run')
    run.status = WorkflowStatus.FAILED
    store.save_run(run)
    broker = RuntimeEventBroker(store=store)
    broker.publish_from_thread('run', event('run.failed', node=None, attempt=None))
    broker.bind_run('run', store)
    broker.publish_from_thread('run', event('model.output.delta', {'publicText': 'late output'}))
    assert broker.snapshot('run').payload['events'][-1]['eventType'] == 'run.failed'
    broker.flush()


def test_rebased_stream_drops_all_retired_attempt_frames(tmp_path):
    async def run():
        store = store_at(tmp_path / 'retired.db')
        store.save_runtime_display('run', {'sequence': 4, 'events': [], 'retiredAttempts': {'node': ['a1']}})
        broker = RuntimeEventBroker(store=store)
        stream = broker.subscribe('run')
        await anext(stream)
        for kind in ('model.started', 'model.completed', 'node.failed', 'tool.execution_completed'):
            await broker.publish('run', event(kind))
        await broker.publish('run', event('model.started', attempt='a2'))
        received = await anext(stream)
        assert received.event_type == 'model.started'
        assert received.attempt_id == 'a2'
        await stream.aclose()
        broker.flush()
    asyncio.run(run())


def test_checkpoint_cas_rollback_and_deleted_run_cannot_resurrect(tmp_path):
    store = store_at(tmp_path / 'runs.db')
    store.save_runtime_display('run', {'sequence': 2, 'events': []})
    store.save_runtime_display('run', {'sequence': 1, 'events': ['stale']})
    assert store.get_runtime_display('run')['sequence'] == 2
    with pytest.raises(RuntimeError), store._connect() as conn:
        conn.execute("UPDATE run_runtime_display SET sequence=3 WHERE run_id='run'")
        raise RuntimeError('rollback')
    assert store.get_runtime_display('run')['sequence'] == 2
    with store._connect() as conn:
        conn.execute("DELETE FROM runs WHERE run_id='run'")
        conn.execute("DELETE FROM run_runtime_display WHERE run_id='run'")
    store.save_runtime_display('run', {'sequence': 4, 'events': []})
    assert store.get_runtime_display('run') is None


def test_display_checkpoint_does_not_wake_mission_projection_readers(tmp_path, monkeypatch):
    from support.stores.workspace_projection import workspace_changes
    store = store_at(tmp_path / 'runs.db')
    notifications = []
    monkeypatch.setattr(workspace_changes, 'notify', lambda: notifications.append(True))
    broker = RuntimeEventBroker(store=store)
    broker.publish_from_thread('run', event('model.started'))
    broker.publish_from_thread('run', event('model.output.delta', {'delta': '{"content":"public"}'}))
    broker.publish_from_thread('run', event('model.completed'))
    assert notifications == []


def test_small_chunks_fold_in_bounded_batches_and_terminal_flushes_the_tail(monkeypatch):
    from runtime import live_events, runtime_display
    monkeypatch.setattr(runtime_display, 'monotonic', lambda: 1.0)
    # Exercise chunk and terminal boundaries independently of wall-clock
    # checkpoint timers, which may fire mid-loop on a busy test machine.
    class ManualTimer:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def cancel(self): pass
    monkeypatch.setattr(live_events, 'Timer', ManualTimer)
    original = runtime_display.public_narrative
    folds = []
    def fold(raw):
        folds.append(len(raw))
        return original(raw)
    monkeypatch.setattr(runtime_display, 'public_narrative', fold)
    class Store:
        saved = None
        def get_runtime_display(self, run_id): return None
        def save_runtime_display(self, run_id, value): self.saved = value
    store = Store()
    broker = RuntimeEventBroker(store=store)
    broker.publish_from_thread('run', event('model.started'))
    broker.publish_from_thread('run', event('model.output.delta', {'delta': '{"content":"'}))
    for _ in range(5000):
        broker.publish_from_thread('run', event('model.output.delta', {'delta': '字'}))
    broker.publish_from_thread('run', event('node.completed'))
    public = next(item for item in store.saved['events'] if item['eventType'] == 'model.output.delta')
    assert public['payload']['publicText'] == '字' * 5000
    assert len(folds) <= 3


def test_checkpoint_io_does_not_hold_the_cross_run_publication_lock():
    from threading import Event, Thread
    entered, release = Event(), Event()
    class Store:
        def get_runtime_display(self, run_id): return None
        def save_runtime_display(self, run_id, value):
            if run_id == 'run':
                entered.set()
                assert release.wait(2)
    broker = RuntimeEventBroker(store=Store())
    worker = Thread(target=broker.publish_from_thread, args=('run', event('model.started')))
    worker.start()
    try:
        assert entered.wait(1)
        other = event('model.activity').model_copy(update={'run_id': 'other'})
        broker.publish_from_thread('other', other)
        assert broker.snapshot('other').sequence == 1
    finally:
        release.set()
        worker.join(timeout=2)
        broker.flush()
    assert not worker.is_alive()


def test_display_replays_agent_instance_and_each_tool_operation():
    display = RuntimeDisplayProjection()
    display.apply(event('node.started', {'agentName': 'Analyzer', 'agentRegistration':
        {'agentId': 'analyzer', 'instanceId': 'instance-2', 'generation': 3, 'definitionDigest': 'internal'}}))
    display.apply(event('model.started', {'model': 'glm', 'callId': 'turn-1'}))
    for index in range(2):
        display.apply(event('tool.execution_completed', {'tool': 'fs.read', 'executionId': f'exec-{index}',
            'operationKey': f'turn-1:call:{index}', 'status': 'completed', 'target': f'{index}.py',
            'approvalDecision': {'source': 'policy', 'decidedAt': '2026-11-17T06:00:00+00:00',
                'policyRevision': 3, 'actor': {'userId': 'user', 'tenantId': None, 'secret': 'PRIVATE'},
                'command': 'PRIVATE'},
            'resultPreview': 'read complete', 'arguments': {'token': 'PRIVATE'}}))
    tools = [e for e in display.events if e['eventType'] == 'tool.execution_completed']
    assert len(tools) == 2
    assert [e['payload']['target'] for e in tools] == ['0.py', '1.py']
    assert tools[0]['payload']['approvalDecision'] == {'source': 'policy', 'decidedAt': '2026-11-17T06:00:00+00:00',
        'policyRevision': 3, 'actor': {'userId': 'user', 'tenantId': None}}
    assert display.events[0]['payload']['agentRegistration'] == {
        'agentId': 'analyzer', 'instanceId': 'instance-2', 'generation': 3}
    assert 'PRIVATE' not in json.dumps(display.events)
