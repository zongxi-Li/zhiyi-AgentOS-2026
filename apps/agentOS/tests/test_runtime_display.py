import asyncio
import json

import pytest

from contracts.runtime_events import RuntimeEvent
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
from runtime.live_events import RuntimeEventBroker, RuntimeEventOverflow
from runtime.runtime_display import RuntimeDisplayProjection, public_narrative
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


def event(kind, payload=None, attempt="a1", node="node"):
    return RuntimeEvent(eventType=kind, runId="run", nodeId=node, attemptId=attempt,
                        sequence=0, payload=payload or {})


def store_at(path):
    store = SQLiteWorkflowStore(path)
    store.save_mission(RuntimeMissionRecord(missionId="mission", title="Display"))
    store.save_run(RuntimeRunRecord(runId="run", missionId="mission", workflowId="test", domain="test",
                                   runtimeEngine="acg", executionState={"planningDeferred": True}))
    return store


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
    from runtime import runtime_display
    monkeypatch.setattr(runtime_display, 'monotonic', lambda: 1.0)
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
