import asyncio
import sqlite3

import pytest

from storage.v2 import SQLiteV2Storage
from support.stores.workspace_projection import (
    WorkspaceConnection, install_revision_triggers, projection_revision, workspace_changes,
)


def test_versions_commit_atomically_survive_reopen_and_ignore_noops(tmp_path):
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path, factory=WorkspaceConnection)
    conn.execute("CREATE TABLE items(mission_id TEXT, value TEXT)")
    install_revision_triggers(conn, {"items": "{row}.mission_id"})
    with conn:
        conn.execute("INSERT INTO items VALUES('a','one')")
    assert projection_revision(conn, "a") == 1
    assert projection_revision(conn, "b") == 0
    with pytest.raises(ValueError), conn:
        conn.execute("UPDATE items SET value='rollback'")
        raise ValueError("rollback")
    assert projection_revision(conn, "a") == 1
    with conn:
        conn.execute("UPDATE items SET value='one'")
    assert projection_revision(conn, "a") == 1
    with conn:
        conn.execute("UPDATE items SET value='two'")
    conn.close()
    with sqlite3.connect(path) as reopened:
        assert projection_revision(reopened, "a") == 2


def test_commit_wakes_observers_but_rollback_does_not(tmp_path):
    async def run():
        conn = sqlite3.connect(tmp_path / "notify.db", factory=WorkspaceConnection)
        conn.execute("CREATE TABLE items(mission_id TEXT, value TEXT)")
        install_revision_triggers(conn, {"items": "{row}.mission_id"})
        conn.commit()
        async with workspace_changes.subscribe() as queue:
            with pytest.raises(ValueError), conn:
                conn.execute("INSERT INTO items VALUES('a','no')")
                raise ValueError("rollback")
            await asyncio.sleep(0)
            assert queue.empty()
            with conn:
                conn.execute("INSERT INTO items VALUES('a','yes')")
            await asyncio.wait_for(queue.get(), 1)
        conn.close()
    asyncio.run(run())


def test_identity_notifies_only_after_outer_commit(tmp_path, monkeypatch):
    with SQLiteV2Storage(tmp_path / "identity-commit.db") as identity:
        notifications = []
        monkeypatch.setattr(workspace_changes, "notify", lambda: notifications.append(True))
        with identity.transaction() as conn:
            conn.execute("INSERT INTO missions(mission_id,user_id,goal,status,created_at,updated_at) "
                         "VALUES('m','u','goal','created','now','now')")
            with identity.transaction() as nested:
                assert nested is conn
                nested.execute("UPDATE missions SET description='nested' WHERE mission_id='m'")
            assert notifications == []
        assert notifications == [True]
        assert identity.workspace_projection_revision("m") == 2
        with identity.transaction():
            pass
        assert notifications == [True]
        with identity.transaction() as conn:
            conn.execute("UPDATE missions SET description=description WHERE mission_id='m'")
        assert identity.workspace_projection_revision("m") == 2


def test_identity_rollback_never_notifies_and_explicit_commit_notifies_once(tmp_path, monkeypatch):
    with SQLiteV2Storage(tmp_path / "identity-rollback.db") as identity:
        notifications = []
        monkeypatch.setattr(workspace_changes, "notify", lambda: notifications.append(True))
        with pytest.raises(ValueError), identity.transaction() as conn:
            conn.execute("INSERT INTO missions(mission_id,user_id,goal,status,created_at,updated_at) "
                         "VALUES('m','u','goal','created','now','now')")
            with identity.transaction() as nested:
                nested.execute("UPDATE missions SET description='nested' WHERE mission_id='m'")
                raise ValueError("rollback nested writes")
        assert notifications == []
        assert identity.workspace_projection_revision("m") == 0
        with identity.read() as conn:
            assert conn.execute("SELECT 1 FROM missions WHERE mission_id='m'").fetchone() is None
        with identity.transaction():
            pass
        assert notifications == []
        with identity.transaction() as conn:
            conn.execute("INSERT INTO missions(mission_id,user_id,goal,status,created_at,updated_at) "
                         "VALUES('m','u','goal','created','now','now')")
            conn.commit()
            assert notifications == [True]
        assert notifications == [True]
        assert identity.workspace_projection_revision("m") == 1


def test_identity_and_runtime_sources_install_on_existing_databases(tmp_path):
    from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
    identity = SQLiteV2Storage(tmp_path / "identity.db")
    runtime = SQLiteWorkflowStore(tmp_path / "runtime.db", enable_mission_semantics=True)
    with identity.read() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_revision_artifacts_insert'").fetchone()
    with runtime._connect() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_revision_runs_update'").fetchone()
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_revision_mission_semantic_state_update'").fetchone()
    identity.close()


def test_runtime_run_save_advances_the_mission_watermark(tmp_path):
    from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
    from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
    store = SQLiteWorkflowStore(tmp_path / "runtime-events.db")
    mission = RuntimeMissionRecord(missionId="mission_versions", title="Versions")
    store.save_mission(mission)
    initial = store.workspace_projection_revision(mission.mission_id)
    run = RuntimeRunRecord(runId="run_versions", missionId=mission.mission_id,
        workflowId="test", domain="test", runtimeEngine="acg", executionState={"planningDeferred": True})
    store.save_run(run)
    first = store.workspace_projection_revision(mission.mission_id)
    assert first > initial
    run.lifecycle_message = "Planning changed"
    store.save_run(run)
    assert store.workspace_projection_revision(mission.mission_id) > first
    assert SQLiteWorkflowStore(store.db_path).workspace_projection_revision(mission.mission_id) == store.workspace_projection_revision(mission.mission_id)
