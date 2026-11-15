"""Same semantic contracts on Memory and temporary SQLite, never business DBs."""

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Barrier

import pytest

from contracts.mission_semantic import MissionSemanticOperation, MissionSemanticRequest, SemanticPrincipal
from contracts.workflow import MissionRecordState, RuntimeMissionRecord, RuntimeRunRecord, WorkflowStatus
from components.mission_manager.semantic_service import MissionSemanticService
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.stores.mission_semantic_store import request_fingerprint


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    value = MemoryWorkflowStore() if request.param == "memory" else SQLiteWorkflowStore(tmp_path / "workflows.sqlite3", enable_mission_semantics=True)
    value.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Untrusted title",
                                          input={"taskGoal": "untrusted", "secret": "INPUT_SECRET"}))
    return value


def operation(op="op1", revision=0, objective="Explicit objective", **changes):
    return MissionSemanticOperation.model_validate({"missionId": "mission_test", "operationId": op,
        "expectedMissionRevision": revision, "objective": objective, "constraints": [],
        "actorId": "owner", "tenantId": "tenant", **changes})


def counts(store):
    return len(store.list_semantic_commits("mission_test")), len(store.list_semantic_outbox("mission_test"))


def test_uninitialized_and_missing_do_not_promote_input(store):
    initial = store.get_semantic_snapshot("mission_test")
    assert initial.status == "UNINITIALIZED" and initial.mission_revision == 0 and initial.state is None
    assert store.get_semantic_snapshot("missing").status == "MISSION_NOT_FOUND"
    assert counts(store) == (0, 0)


def test_first_commit_monotonicity_and_lifecycle_isolation(store):
    lifecycle = store.list_outbox()
    first = store.commit_semantics(operation())
    second = store.commit_semantics(operation("op2", 1, "Second objective"))
    assert (first.status, first.mission_revision, second.mission_revision) == ("COMMITTED", 1, 2)
    assert [c.previous_revision for c in store.list_semantic_commits("mission_test")] == [0, 1]
    assert counts(store) == (2, 2)
    assert store.list_outbox() == lifecycle
    for event in store.list_semantic_outbox("mission_test"):
        assert set(event) == {"eventId", "eventType", "missionId", "commitId", "missionRevision", "schemaVersion", "createdAt", "status"}
        assert "INPUT_SECRET" not in json.dumps(event) and "Explicit objective" not in json.dumps(event)
    assert "INPUT_SECRET" not in store.list_semantic_commits("mission_test")[0].model_dump_json()


def test_replay_original_after_later_changes(store):
    first = store.commit_semantics(operation())
    receipt = store.get_semantic_receipt("mission_test", "op1")
    store.commit_semantics(operation("later", 1, "Changed"))
    assert store.commit_semantics(operation()) == first
    assert store.get_semantic_receipt("mission_test", "op1") == receipt
    assert counts(store) == (2, 2)


@pytest.mark.parametrize("change", [{"objective": "Different"}, {"expected_mission_revision": 1},
                                    {"actor_id": "another"}, {"tenant_id": "another"}])
def test_operation_conflict_does_not_overwrite_receipt(store, change):
    store.commit_semantics(operation())
    receipt = store.get_semantic_receipt("mission_test", "op1")
    changed = MissionSemanticOperation.model_validate({**operation().model_dump(), **change})
    assert store.commit_semantics(changed).status == "OPERATION_CONFLICT"
    assert store.get_semantic_receipt("mission_test", "op1") == receipt
    assert counts(store) == (1, 1)


def test_noop_receipt_without_state_history_or_outbox_update(store):
    store.commit_semantics(operation())
    before = store.get_semantic_snapshot("mission_test")
    noop = store.commit_semantics(operation("noop", 1))
    assert noop.status == "NO_OP" and noop.mission_revision == 1 and noop.commit_id is None
    assert store.get_semantic_snapshot("mission_test") == before
    assert store.get_semantic_receipt("mission_test", "noop").result == noop
    store.commit_semantics(operation("later", 1, "Changed"))
    assert store.commit_semantics(operation("noop", 1)) == noop
    assert counts(store) == (2, 2)


def test_cas_conflict_is_durable_and_replayed(store):
    store.commit_semantics(operation())
    assert store.commit_semantics(operation("stale_same", 0)).status == "REVISION_CONFLICT"
    conflict = store.commit_semantics(operation("stale", 0, "Other"))
    assert conflict.status == "REVISION_CONFLICT" and conflict.mission_revision == 1
    assert store.get_semantic_receipt("mission_test", "stale").result == conflict
    store.commit_semantics(operation("later", 1, "Later"))
    assert store.commit_semantics(operation("stale", 0, "Other")) == conflict
    assert counts(store) == (2, 2)


def test_canonical_sets_and_unverified_sources(store):
    op = operation(sourceRefs=["b", "a", "a"], constraints=[
        {"constraintId": "b", "text": "B", "sourceRefs": ["r2", "r1"]},
        {"constraintId": "a", "text": "A"}])
    equivalent = op.model_copy(deep=True)
    equivalent.source_refs = ["a", "b"]
    equivalent.constraints.reverse()
    equivalent.constraints[1].source_refs.reverse()
    assert request_fingerprint(op) == request_fingerprint(equivalent)
    first = store.commit_semantics(op)
    assert store.commit_semantics(equivalent) == first
    snap = store.get_semantic_snapshot("mission_test")
    assert snap.source_status == "UNVERIFIED"
    assert snap.state.source_refs == ["a", "b"]


def test_reads_and_results_are_detached(store):
    op = operation(sourceRefs=["ref"])
    result = store.commit_semantics(op)
    op.source_refs.append("injected")
    result.mission_revision = 100
    snap = store.get_semantic_snapshot("mission_test")
    snap.state.source_refs.append("injected")
    store.list_semantic_commits("mission_test")[0].state.objective = "injected"
    store.get_semantic_receipt("mission_test", "op1").result.mission_revision = 99
    store.list_semantic_outbox("mission_test")[0]["missionRevision"] = 99
    assert store.get_semantic_snapshot("mission_test").state.source_refs == ["ref"]
    assert store.list_semantic_commits("mission_test")[0].state.objective == "Explicit objective"
    assert store.commit_semantics(operation(sourceRefs=["ref"])).mission_revision == 1
    assert store.list_semantic_outbox("mission_test")[0]["missionRevision"] == 1


def test_concurrent_first_commit_one_winner_two_durable_receipts(store):
    other = SQLiteWorkflowStore(store.db_path, enable_mission_semantics=True) if isinstance(store, SQLiteWorkflowStore) else store
    barrier = Barrier(2)
    def submit(adapter, name):
        barrier.wait(timeout=10)
        return adapter.commit_semantics(operation(name))
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(submit, store, "one"), pool.submit(submit, other, "two")]
        results = [job.result(timeout=15) for job in jobs]
    assert sorted(r.status for r in results) == ["COMMITTED", "REVISION_CONFLICT"]
    assert counts(store) == (1, 1)
    assert all(store.get_semantic_receipt("mission_test", name) for name in ["one", "two"])


def test_midway_exception_rolls_back_all_records(store, monkeypatch):
    store.commit_semantics(operation())
    before = store.get_semantic_snapshot("mission_test")
    if isinstance(store, SQLiteWorkflowStore):
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("""CREATE TRIGGER fail_receipt BEFORE INSERT ON mission_semantic_receipts
                BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END""")
        error = sqlite3.IntegrityError
    else:
        def fail(_):
            raise RuntimeError("injected outbox failure")
        monkeypatch.setattr("support.stores.memory_workflow_store.semantic_outbox", fail)
        error = RuntimeError
    with pytest.raises(error, match="injected"):
        store.commit_semantics(operation("broken", 1, "New objective"))
    assert store.get_semantic_snapshot("mission_test") == before
    assert counts(store) == (1, 1)
    assert store.get_semantic_receipt("mission_test", "broken") is None


def terminal_run(store, name="run_test"):
    store.save_run(RuntimeRunRecord(runId=name, missionId="mission_test", workflowId="workflow-1",
                                   domain="general", runtimeEngine="acg", status=WorkflowStatus.COMPLETED))


def test_soft_delete_preserves_history_and_rejects_new_semantics(store):
    store.commit_semantics(operation())
    store.set_mission_record_state("mission_test", MissionRecordState.DELETED)
    assert counts(store) == (1, 1)
    assert store.get_semantic_snapshot("mission_test").mission_revision == 1
    with pytest.raises(ValueError, match="deleted mission"):
        store.commit_semantics(operation("new", 1, "Changed"))
    assert store.get_semantic_receipt("mission_test", "new") is None


def test_physical_delete_purges_only_when_mission_removed(store):
    store.commit_semantics(operation())
    terminal_run(store)
    terminal_run(store, "run_two")
    assert not store.delete_run("run_test").mission_deleted
    assert counts(store) == (1, 1)
    assert store.delete_run("run_two").mission_deleted
    assert store.get_semantic_snapshot("mission_test").status == "MISSION_NOT_FOUND"
    assert counts(store) == (0, 0)
    assert store.get_semantic_receipt("mission_test", "op1") is None


def test_delete_without_orphan_cleanup_preserves_semantics(store):
    store.commit_semantics(operation())
    terminal_run(store)
    assert not store.delete_run("run_test", delete_orphan_mission=False).mission_deleted
    assert counts(store) == (1, 1)


def test_authorization_rechecked_before_replay_and_every_read(store):
    allowed = {("owner", "tenant", "mission_test")}
    calls = []
    def authorize(principal, mission_id, action):
        calls.append(action)
        if (principal.actor_id, principal.tenant_id, mission_id) not in allowed:
            raise PermissionError("semantic access denied")
        return True
    service = MissionSemanticService(store=store, authorize=authorize)
    principal = SemanticPrincipal(actorId="owner", tenantId="tenant")
    request = MissionSemanticRequest.model_validate(operation().model_dump(exclude={"actor_id", "tenant_id"}))
    first = service.commit(principal, request)
    assert service.commit(principal, request) == first
    assert service.get_effective_snapshot(principal, "mission_test").mission_revision == 1
    assert service.list_commits(principal, "mission_test")[0].commit_id == first.commit_id
    assert service.get_receipt(principal, "mission_test", "op1").result == first
    for invalid in [SemanticPrincipal(actorId="other", tenantId="tenant"),
                    SemanticPrincipal(actorId="owner", tenantId="other")]:
        with pytest.raises(PermissionError):
            service.commit(invalid, request)
    allowed.clear()
    for action in [lambda: service.commit(principal, request),
                   lambda: service.get_effective_snapshot(principal, "mission_test"),
                   lambda: service.list_commits(principal, "mission_test"),
                   lambda: service.get_receipt(principal, "mission_test", "op1")]:
        with pytest.raises(PermissionError):
            action()
    assert counts(store) == (1, 1)
    with pytest.raises(TypeError):
        MissionSemanticService(store=store, authorize=None)
    for deny in [False, None]:
        denied = MissionSemanticService(store=store, authorize=lambda *_: deny)
        with pytest.raises(PermissionError):
            denied.commit(principal, request)


def test_restart_recovers_state_and_all_receipt_outcomes(tmp_path):
    path = tmp_path / "restart.sqlite3"
    store = SQLiteWorkflowStore(path, enable_mission_semantics=True)
    store.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Legacy"))
    requests = [operation(), operation("noop", 1), operation("stale", 0)]
    results = [store.commit_semantics(op) for op in requests]
    before = store.get_semantic_snapshot("mission_test")
    reopened = SQLiteWorkflowStore(path, enable_mission_semantics=True)
    assert reopened.get_semantic_snapshot("mission_test") == before
    assert [reopened.commit_semantics(op) for op in requests] == results
    assert counts(reopened) == (1, 1)


def test_additive_migration_legacy_compatibility_and_unknown_version(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = SQLiteWorkflowStore(path, enable_mission_semantics=True)
    store.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Legacy"))
    before = store.list_outbox()
    with sqlite3.connect(path) as conn:
        for table in ["mission_semantic_state", "mission_semantic_commits", "mission_semantic_receipts",
                      "mission_semantic_outbox", "mission_semantic_schema"]:
            conn.execute(f"DROP TABLE {table}")
    reopened = SQLiteWorkflowStore(path, enable_mission_semantics=True)
    assert reopened.get_semantic_snapshot("mission_test").status == "UNINITIALIZED"
    assert reopened.list_outbox() == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT version FROM mission_semantic_schema").fetchall() == [(1,)]
        conn.execute("UPDATE mission_semantic_schema SET version=2")
    with pytest.raises(RuntimeError, match="unsupported Mission semantic schema"):
        SQLiteWorkflowStore(path, enable_mission_semantics=True)


def test_sqlite_purge_failure_rolls_back_run_and_semantics(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "purge.sqlite3", enable_mission_semantics=True)
    store.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Legacy"))
    store.commit_semantics(operation())
    terminal_run(store)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("""CREATE TRIGGER fail_purge BEFORE DELETE ON mission_semantic_state
            BEGIN SELECT RAISE(ABORT, 'purge failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="purge failed"):
        store.delete_run("run_test")
    assert store.get_run("run_test").mission_id == "mission_test"
    assert counts(store) == (1, 1)
    assert store.get_semantic_receipt("mission_test", "op1")
    assert store.get_semantic_snapshot("mission_test").mission_revision == 1


def test_fingerprint_v1_golden_vector():
    assert request_fingerprint(operation()) == "f177705194103f9ffe5b174e5dbe2d7b1562a629afa68d6cd143e4e48beb529c"


def test_operation_id_is_scoped_to_mission(store):
    first = store.commit_semantics(operation())
    store.save_mission(RuntimeMissionRecord(missionId="mission_other", title="Other"))
    other = operation().model_copy(update={"mission_id": "mission_other"})
    second = store.commit_semantics(other)
    assert first.status == second.status == "COMMITTED"
    assert first.commit_id != second.commit_id


def test_same_operation_concurrent_replay(store):
    other = SQLiteWorkflowStore(store.db_path, enable_mission_semantics=True) if isinstance(store, SQLiteWorkflowStore) else store
    barrier = Barrier(2)
    def submit(adapter):
        barrier.wait(timeout=10)
        return adapter.commit_semantics(operation())
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(submit, adapter) for adapter in [store, other]]
        results = [job.result(timeout=15) for job in jobs]
    assert results[0] == results[1]
    assert counts(store) == (1, 1)


def test_state_commit_receipt_outbox_references_match(store):
    result = store.commit_semantics(operation(sourceRefs=["source"]))
    state = store.get_semantic_snapshot("mission_test").state
    commit = store.list_semantic_commits("mission_test")[0]
    receipt = store.get_semantic_receipt("mission_test", "op1")
    event = store.list_semantic_outbox("mission_test")[0]
    assert state == commit.state
    assert state.last_commit_id == commit.commit_id == result.commit_id == event["commitId"]
    assert state.mission_revision == commit.mission_revision == result.mission_revision == event["missionRevision"] == 1
    assert receipt.request_fingerprint == commit.request_fingerprint == request_fingerprint(operation(sourceRefs=["source"]))
    assert receipt.result == result


def test_invalid_requests_and_missing_mission_do_not_leave_receipts(store):
    from pydantic import ValidationError
    for changes in [{"objective": " "}, {"expected_mission_revision": -1},
                    {"expected_mission_revision": True}, {"unexpected": "raw input"},
                    {"constraints": [{"constraintId": "c", "text": " "}]},
                    {"constraints": [{"constraintId": "c", "text": "a"}, {"constraintId": "c", "text": "b"}]}]:
        with pytest.raises(ValidationError):
            MissionSemanticOperation.model_validate({**operation().model_dump(), **changes})
    invalid = operation().model_copy(update={"objective": " "})
    with pytest.raises(ValidationError):
        store.commit_semantics(invalid)
    missing = operation().model_copy(update={"mission_id": "missing"})
    with pytest.raises(KeyError):
        store.commit_semantics(missing)
    assert store.get_semantic_receipt("missing", "op1") is None
    assert counts(store) == (0, 0)


def test_sqlite_first_commit_last_write_failure_preserves_revision_zero(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "first.sqlite3", enable_mission_semantics=True)
    store.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Legacy"))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("""CREATE TRIGGER fail_first BEFORE INSERT ON mission_semantic_receipts
            BEGIN SELECT RAISE(ABORT, 'first failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="first failed"):
        store.commit_semantics(operation())
    assert store.get_semantic_snapshot("mission_test").status == "UNINITIALIZED"
    assert counts(store) == (0, 0)
    assert store.get_semantic_receipt("mission_test", "op1") is None
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER fail_first")
    assert store.commit_semantics(operation()).mission_revision == 1


def test_sqlite_migration_ddl_failure_rolls_back_version_and_tables(tmp_path):
    path = tmp_path / "migration_failure.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE mission_semantic_commits(existing INTEGER)")
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        SQLiteWorkflowStore(path, enable_mission_semantics=True)
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "mission_semantic_state" not in tables
    assert "mission_semantic_schema" not in tables
    assert "mission_semantic_commits" in tables


def test_legacy_mission_and_run_writes_cannot_overwrite_semantics(store):
    store.commit_semantics(operation())
    before = store.get_semantic_snapshot("mission_test")
    mission = store.get_mission("mission_test")
    mission.title = "Changed legacy title"
    mission.input = {"objective": "Untrusted replacement"}
    store.save_mission(mission)
    terminal_run(store)
    assert store.get_semantic_snapshot("mission_test") == before
    assert counts(store) == (1, 1)


def test_memory_purge_preparation_failure_leaves_all_records(monkeypatch):
    store = MemoryWorkflowStore()
    store.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Legacy"))
    store.commit_semantics(operation())
    terminal_run(store)
    def fail(**_):
        raise RuntimeError("injected purge preparation failure")
    monkeypatch.setattr("support.stores.memory_workflow_store.RuntimeRunRecordDeleteResult", fail)
    with pytest.raises(RuntimeError, match="injected purge"):
        store.delete_run("run_test")
    assert store.get_run("run_test").mission_id == "mission_test"
    assert counts(store) == (1, 1)
    assert store.get_semantic_receipt("mission_test", "op1")
    assert store.get_semantic_snapshot("mission_test").mission_revision == 1


def test_sqlite_schema_upgrade_requires_explicit_opt_in(tmp_path):
    path = tmp_path / "no_implicit_upgrade.sqlite3"
    legacy = SQLiteWorkflowStore(path)
    legacy.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Legacy"))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'mission_semantic_%'").fetchall() == []
    with pytest.raises(RuntimeError, match="opt-in"):
        legacy.commit_semantics(operation())
    enabled = SQLiteWorkflowStore(path, enable_mission_semantics=True)
    enabled.commit_semantics(operation())
    terminal_run(legacy)
    assert legacy.delete_run("run_test").mission_deleted
    assert counts(enabled) == (0, 0)
    assert enabled.get_semantic_receipt("mission_test", "op1") is None
    never_upgraded = SQLiteWorkflowStore(tmp_path / "legacy_delete.sqlite3")
    never_upgraded.save_mission(RuntimeMissionRecord(missionId="mission_test", title="Legacy"))
    terminal_run(never_upgraded)
    assert never_upgraded.delete_run("run_test").mission_deleted
