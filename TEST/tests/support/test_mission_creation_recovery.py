"""Insert-only creation anchors and initial Run CAS across independent connections."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return MemoryWorkflowStore() if request.param == "memory" else SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")


def mission(identity="mission_candidate", fingerprint="original"):
    return RuntimeMissionRecord(missionId=identity, title="original", creationKey="request-key", creationFingerprint=fingerprint)


def run(identity="run_candidate", mission_id="mission_candidate", fingerprint="original"):
    return RuntimeRunRecord(runId=identity, missionId=mission_id, workflowId="workflow", domain="general",
        runtimeEngine="acg", idempotencyKey="run-key", idempotencyFingerprint=fingerprint)


def test_replay_preserves_updated_records_and_rejects_changed_body(store):
    original = store.create_mission_once(mission())
    original.title = "later title"
    store.save_mission(original)
    replay = store.create_mission_once(mission("mission_other"))
    assert replay.mission_id == original.mission_id and replay.title == "later title"
    with pytest.raises(ValueError, match="conflict"):
        store.create_mission_once(mission("mission_other", "changed"))
    stored = store.save_prepared_run_once(run())
    changed = stored.model_copy(deep=True)
    changed.execution_state["later"] = True
    store.save_run(changed)
    assert store.save_prepared_run_once(run("run_other")).execution_state["later"] is True
    with pytest.raises(ValueError, match="conflict"):
        store.save_prepared_run_once(run("run_other", fingerprint="changed"))


def test_creation_outbox_failure_rolls_back_before_retry(store, monkeypatch):
    name = "_append_lifecycle_event" if isinstance(store, MemoryWorkflowStore) else "_append_outbox"
    original = getattr(store, name)
    def fail(*args, **kwargs):
        raise RuntimeError("injected outbox failure")
    monkeypatch.setattr(store, name, fail)
    with pytest.raises(RuntimeError):
        store.create_mission_once(mission())
    with pytest.raises(KeyError):
        store.get_mission("mission_candidate")
    monkeypatch.setattr(store, name, original)
    assert store.create_mission_once(mission()).mission_id == "mission_candidate"
    run_save = "_save_run_snapshot" if isinstance(store, MemoryWorkflowStore) else "_upsert_run"
    original_run_save = getattr(store, run_save)
    def fail_after_run_write(*args, **kwargs):
        original_run_save(*args, **kwargs)
        raise RuntimeError("injected failure after Run write")
    monkeypatch.setattr(store, run_save, fail_after_run_write)
    with pytest.raises(RuntimeError):
        store.save_prepared_run_once(run())
    assert store.find_run_by_idempotency_key("run-key") is None
    monkeypatch.setattr(store, run_save, original_run_save)
    assert store.save_prepared_run_once(run()).run_id == "run_candidate"


def test_two_connections_allocate_one_mission_and_one_run(tmp_path):
    path = tmp_path / "workflow.sqlite3"
    stores = [SQLiteWorkflowStore(path), SQLiteWorkflowStore(path)]
    barrier = Barrier(2)
    def create(index):
        barrier.wait()
        return stores[index].create_mission_once(mission("mission_" + str(index)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        missions = list(pool.map(create, range(2)))
    assert missions[0].mission_id == missions[1].mission_id
    def prepare(index):
        barrier.wait()
        return stores[index].save_prepared_run_once(run("run_" + str(index), missions[0].mission_id))
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(prepare, range(2)))
    assert runs[0].run_id == runs[1].run_id
    # Reconstruct the store to prove anchors and first persistence survive restart.
    reopened = SQLiteWorkflowStore(path)
    assert reopened.create_mission_once(mission()).mission_id == missions[0].mission_id
    assert reopened.find_run_by_idempotency_key("run-key").run_id == runs[0].run_id
