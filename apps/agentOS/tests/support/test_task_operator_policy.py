"""Real Store CAS, restart, migration and Mission scope authorization evidence."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from contracts.task_operator_policy import (
    TaskOperatorPolicyConflict, public_approval_decision, task_operator_policy_projection,
)
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowStatus
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


SCOPE = {"workspaceId": "workspace", "grantId": "grant", "resourceId": "runtime"}
ACTOR = {"userId": "user", "tenantId": "tenant"}


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    result = (MemoryWorkflowStore() if request.param == "memory"
        else SQLiteWorkflowStore(tmp_path / "workflow.db"))
    result.save_mission(RuntimeMissionRecord(missionId="mission", title="Task"))
    return result


def enable(store, **overrides):
    return store.set_task_operator_policy("mission", **{
        "permission": "task_collaboration", "approval_mode": "full",
        "workspace_scope": SCOPE, "actor": ACTOR,
        "operation_id": "enable", "expected_policy_revision": 0, **overrides})


def test_default_and_legacy_permission_share_one_policy(store):
    assert store.get_task_operator_policy("mission").policy_revision == 0
    assert store.get_task_copilot_permission("mission") == "task_collaboration"
    assert store.get_task_operator_policy("mission").approval_mode == "ask"
    enabled = enable(store)
    assert enabled.policy_revision == 1
    store.set_task_copilot_permission("mission", "read_only")
    changed = store.get_task_operator_policy("mission")
    assert (changed.permission, changed.approval_mode, changed.policy_revision) == ("read_only", "ask", 2)
    store.set_task_copilot_permission("mission", "read_only")
    assert store.get_task_operator_policy("mission") == changed
    with pytest.raises(KeyError):
        store.get_task_operator_policy("unknown")


def test_cas_and_replay_do_not_restore_withdrawn_authorization(store):
    first = enable(store)
    assert enable(store) == first
    store.set_task_operator_policy("mission", permission="task_collaboration", approval_mode="ask",
        operation_id="withdraw", expected_policy_revision=1, actor=ACTOR)
    assert enable(store) == first  # Immutable operation receipt, not current policy.
    assert store.get_task_operator_policy("mission").approval_mode == "ask"
    with pytest.raises(TaskOperatorPolicyConflict, match="different content"):
        enable(store, workspace_scope={**SCOPE, "grantId": "other"})
    with pytest.raises(TaskOperatorPolicyConflict, match="revision changed"):
        enable(store, operation_id="stale")
    current = store.get_task_operator_policy("mission")
    assert current.policy_revision == 2


@pytest.mark.parametrize("change", [
    {"workspace_scope": None}, {"actor": None}, {"operation_id": None},
    {"expected_policy_revision": None}, {"permission": "read_only"},
    {"approval_mode": "auto"},
])
def test_full_requires_explicit_authorization_identity(store, change):
    with pytest.raises(ValueError):
        enable(store, **change)
    assert store.get_task_operator_policy("mission").policy_revision == 0


def test_effective_approval_never_expands_workspace_or_resource(store):
    policy = enable(store)
    assert task_operator_policy_projection(policy, SCOPE)["approvalMode"] == "full"
    for binding in (None, {}, {**SCOPE, "revoked": True},
            {**SCOPE, "workspaceId": "other"}, {**SCOPE, "grantId": "other"},
            {**SCOPE, "resourceId": "other"}, {**SCOPE, "resourceId": None}):
        view = task_operator_policy_projection(policy, binding)
        assert view["approvalMode"] == "ask"
        assert view["approvalPolicy"]["approvalMode"] == "full"
        assert not view["approvalPolicy"]["effectiveScopeMatch"]
    store.save_mission(RuntimeMissionRecord(missionId="other", title="Other task"))
    assert store.get_task_operator_policy("other").approval_mode == "ask"


def test_policy_cas_has_one_winner_across_competing_adapters(store):
    other = SQLiteWorkflowStore(store.db_path) if isinstance(store, SQLiteWorkflowStore) else store
    barrier = threading.Barrier(2)

    def compete(adapter, operation_id):
        barrier.wait(timeout=10)
        try:
            return enable(adapter, operation_id=operation_id)
        except TaskOperatorPolicyConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=15) for future in (
            pool.submit(compete, store, "first"), pool.submit(compete, other, "second"))]
    assert sum(result is not None for result in results) == 1
    assert store.get_task_operator_policy("mission").policy_revision == 1


def test_sqlite_restart_keeps_policy_and_operation_receipt(tmp_path):
    path = tmp_path / "workflow.db"
    store = SQLiteWorkflowStore(path)
    store.save_mission(RuntimeMissionRecord(missionId="mission", title="Task"))
    policy = enable(store)
    reopened = SQLiteWorkflowStore(path)
    assert reopened.get_task_operator_policy("mission") == policy
    assert enable(reopened) == policy
    assert reopened.get_task_copilot_permission("mission") == "task_collaboration"
    # Separate Run revisions and graph versions do not mutate Mission policy.
    reopened.save_run(RuntimeRunRecord(runId="run", missionId="mission", workflowId="workflow",
        domain="general", runtimeEngine="acg", executionState={"planningDeferred": True}))
    assert reopened.get_task_operator_policy("mission") == policy


def test_sqlite_legacy_permission_migrates_to_ask_without_automatic_upgrade(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE task_copilot_permissions (mission_id TEXT PRIMARY KEY,
            permission TEXT NOT NULL CHECK(permission IN ('read_only', 'task_collaboration')))""")
        conn.execute("INSERT INTO task_copilot_permissions VALUES('mission','read_only')")
    store = SQLiteWorkflowStore(path)
    store.save_mission(RuntimeMissionRecord(missionId="mission", title="Task"))
    policy = store.get_task_operator_policy("mission")
    assert (policy.permission, policy.approval_mode, policy.policy_revision) == ("read_only", "ask", 0)


def test_sqlite_policy_lock_is_shared_across_instances_and_threads(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "workflow.db")
    other = SQLiteWorkflowStore(store.db_path)
    lock = store.task_operator_policy_lock("mission")
    assert lock is other.task_operator_policy_lock("mission")
    assert lock is not other.task_operator_policy_lock("other")
    attempted = threading.Event()
    admitted = threading.Event()

    def enter():
        attempted.set()
        with other.task_operator_policy_lock("mission"):
            admitted.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with lock:
            future = pool.submit(enter)
            assert attempted.wait(timeout=5)
            assert not admitted.is_set()
        future.result(timeout=5)
    assert admitted.is_set()


def test_purge_removes_policy_and_operation_identity(store):
    enable(store)
    store.save_run(RuntimeRunRecord(runId="run", missionId="mission", workflowId="workflow",
        domain="general", runtimeEngine="acg", status=WorkflowStatus.COMPLETED))
    assert store.delete_run("run").mission_deleted
    store.save_mission(RuntimeMissionRecord(missionId="mission", title="New task"))
    assert store.get_task_operator_policy("mission").policy_revision == 0
    assert enable(store).policy_revision == 1


def test_public_approval_decision_excludes_wal_payload_and_authority_fields():
    decision = {"source": "policy", "decidedAt": "2026-11-17T12:00:00+00:00",
        "policyRevision": 3, "actor": {**ACTOR, "token": "private"},
        "workspaceScope": SCOPE, "command": "private", "request": {"private": True}}
    assert public_approval_decision(decision) == {
        "source": "policy", "decidedAt": decision["decidedAt"], "policyRevision": 3, "actor": ACTOR}
    assert public_approval_decision({**decision, "source": "model"}) is None
    assert public_approval_decision({**decision, "decidedAt": "invalid"}) is None
    assert public_approval_decision(None) is None
    sanitized = public_approval_decision({**decision, "policyRevision": True, "actor": {"userId": 123}})
    assert "policyRevision" not in sanitized and "actor" not in sanitized
