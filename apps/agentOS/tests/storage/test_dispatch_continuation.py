"""Continuation admission is append-only, fenced to the next formal graph."""
import sqlite3

import pytest

from contracts.workflow import RuntimeRunRecord
from support.stores import c2_schema_upgrade as ops
from support.stores.execution_dispatch_store import DispatchCommand, DispatchConflict, SQLiteExecutionDispatchStore


@pytest.fixture
def dispatch(tmp_path):
    path = tmp_path / "workflow.sqlite3"
    ops._initialize("workflow", path)
    for factory in ops.UPGRADERS:
        factory.upgrade_schema(path)
    SQLiteExecutionDispatchStore.upgrade_schema(path)
    store = SQLiteExecutionDispatchStore(path)
    run = RuntimeRunRecord(runId="run:review", missionId="mission:review", workflowId="review", domain="general", runtimeEngine="acg",
        executionState={"graphId": "graph:review", "graphVersion": 1, "executionPermitId": "permit:1"})
    command = DispatchCommand(dispatch_id="dispatch:1", operation_key="initial", request_fingerprint="initial",
        mission_id=run.mission_id, run_id=run.run_id, permit_id="permit:1", graph_id="graph:review", graph_version=1,
        runtime_revision=run.runtime_revision, actor_id="owner", tenant_id="tenant")
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO runs(run_id,mission_id,payload,updated_at) VALUES(?,?,?,?)", (
            run.run_id, run.mission_id, run.model_dump_json(by_alias=True), run.updated_at.isoformat()))
    store.accept(command, lambda current: None)
    return store, run, command


def next_graph(store, run, parent):
    run.execution_state.update(graphVersion=parent.graph_version + 1, executionPermitId=f"permit:{parent.graph_version + 1}")
    run.runtime_revision += 1
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run.run_id))
    return parent.model_copy(update={"dispatch_id": f"dispatch:{parent.graph_version + 1}",
        "operation_key": f"continuation:{parent.graph_version + 1}", "request_fingerprint": f"graph:{parent.graph_version + 1}",
        "permit_id": run.execution_state["executionPermitId"], "graph_version": parent.graph_version + 1,
        "runtime_revision": run.runtime_revision})


def test_continuations_preserve_initial_admission_and_replay_without_duplicate(dispatch):
    store, run, initial = dispatch
    parent = initial
    for _ in range(40):
        candidate = next_graph(store, run, parent)
        admitted, replay = store.accept_continuation(candidate, parent, lambda current: None)
        assert admitted == candidate and replay is False
        assert store.accept_continuation(candidate, parent, lambda current: None) == (admitted, True)
        parent = admitted
    assert SQLiteExecutionDispatchStore(store.db_path).get(run.run_id) == parent
    assert store.commands() == [parent]
    with sqlite3.connect(store.db_path) as conn:
        raw = conn.execute("SELECT payload FROM execution_dispatch_commands").fetchone()[0]
        assert DispatchCommand.model_validate_json(raw) == initial
        assert conn.execute("SELECT count(*) FROM execution_dispatch_continuations").fetchone()[0] == 40


@pytest.mark.parametrize("change", ["actor_id", "tenant_id", "mission_id", "graph_id", "permit_id", "graph_version"])
def test_continuation_cannot_change_authorization_or_skip_a_graph(dispatch, change):
    store, run, parent = dispatch
    command = next_graph(store, run, parent)
    value = command.graph_version + 1 if change == "graph_version" else parent.permit_id if change == "permit_id" else "different"
    with pytest.raises(DispatchConflict):
        store.accept_continuation(command.model_copy(update={change: value}), parent, lambda current: None)
    assert store.get(run.run_id) == parent


def test_replay_cannot_change_principal_or_permit_under_the_same_fingerprint(dispatch):
    store, run, parent = dispatch
    command = next_graph(store, run, parent)
    store.accept_continuation(command, parent, lambda current: None)
    with pytest.raises(DispatchConflict):
        store.accept_continuation(command.model_copy(update={"actor_id": "different"}), command, lambda current: None)


def test_permission_denial_never_leaves_an_admission(dispatch):
    store, run, parent = dispatch
    command = next_graph(store, run, parent)
    def denied(current):
        raise PermissionError("revoked")
    with pytest.raises(PermissionError):
        store.accept_continuation(command, parent, denied)
    assert store.get(run.run_id) == parent


def test_continuation_schema_requires_explicit_upgrade_and_detects_mismatch(dispatch):
    store, run, parent = dispatch
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DROP TABLE execution_dispatch_continuations")
    old = SQLiteExecutionDispatchStore(store.db_path)
    command = next_graph(old, run, parent)
    with pytest.raises(DispatchConflict, match="upgrade"):
        old.accept_continuation(command, parent, lambda current: None)
    SQLiteExecutionDispatchStore.upgrade_schema(store.db_path)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("ALTER TABLE execution_dispatch_continuations ADD COLUMN unknown TEXT")
    with pytest.raises(RuntimeError, match="schema definition"):
        SQLiteExecutionDispatchStore(store.db_path)
