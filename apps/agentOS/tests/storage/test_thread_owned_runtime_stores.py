"""Worker continuations preserve SQLite ownership, transactions and CAS."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Barrier, Event

import pytest

from components.auditor.decision_store import SQLiteDecisionStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor.value_store import SQLiteExecutionValueStore
from components.recovery.checkpoint import ACGCheckpointStore, CheckpointConflictError
from contracts.governance import PolicyDecision
from support.sqlite_connections import ThreadLocalSQLiteConnections


def _store_operation(kind, path):
    if kind == "checkpoint":
        store = ACGCheckpointStore(db_path=path)

        def write_read(run, value):
            checkpoint = store.save(run_id=run, state={"value": value})
            assert store.version(run_id=run, checkpoint_id=checkpoint) == 1
            return store.load(run_id=run, checkpoint_id=checkpoint)["value"]
    elif kind == "value":
        store = SQLiteExecutionValueStore(db_path=path)

        def write_read(run, value):
            commit = f"commit:{run}"
            store.prepare_node_commit(run_id=run, commit_id=commit)
            reference = store.put_output(run_id=run, step_id="read", payload={"value": value}, operation_id=commit)
            store.complete_node_commit(run_id=run, commit_id=commit, payload={"outputRef": reference})
            return store.get_output(run_id=run, output_ref=reference)["value"]
    elif kind == "provenance":
        store = SQLiteProvenanceStore(db_path=path)

        def write_read(run, value):
            ledger = store.load_ledger(run_id=run, mission_id="mission")
            ledger.record_production("read", {value: True}, 1)
            restored = store.load_ledger(run_id=run, mission_id="mission")
            assert restored.verify_integrity()
            return restored.productions[0].field_names[0]
    else:
        store = SQLiteDecisionStore(db_path=path)

        def write_read(run, value):
            decision = PolicyDecision(decisionId=f"decision:{run}", subjectRef=f"pending:{run}",
                                      outcome="allow", policyRefs=["execution.v1"], rationale=value)
            store.save(run_id=run, step_id="read", decision=decision)
            return store.assert_decision(run_id=run, step_id="read", decision_ref=decision.decision_id,
                                         outcomes={"allow"}).rationale
    return store, write_read


@pytest.mark.parametrize("kind", ["checkpoint", "value", "provenance", "decision"])
def test_store_created_on_main_thread_can_write_from_parallel_workers_and_close_all(tmp_path, kind):
    store, write_read = _store_operation(kind, tmp_path / f"{kind}.sqlite3")
    main_connection = store._connection
    barrier = Barrier(2)

    def worker(index):
        connection = store._connection
        barrier.wait(timeout=5)
        assert write_read(f"run-{index}", f"worker-{index}") == f"worker-{index}"
        assert store._connection is connection
        return connection

    try:
        assert write_read("run-main", "main") == "main"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, index) for index in range(2)]
            connections = [future.result(timeout=10) for future in futures]
        assert len({id(main_connection), *(id(connection) for connection in connections)}) == 3
        # Reads on the constructing thread remain usable after worker commits.
        assert store._connection is main_connection
        table = {"checkpoint": "acg_execution_checkpoints", "value": "acg_node_commits",
                 "provenance": "acg_provenance_events", "decision": "acg_audit_decisions"}[kind]
        assert main_connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (3,)
    finally:
        store.close()
    for connection in [main_connection, *connections]:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    assert store._connection is main_connection
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        store._connection.execute("SELECT 1")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: store._connection)
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            future.result(timeout=5)
    store.close()


def test_parallel_thread_transactions_cannot_observe_or_commit_each_others_changes(tmp_path):
    connections = ThreadLocalSQLiteConnections(tmp_path / "transactions.sqlite3")
    main = connections.connection()
    main.execute("CREATE TABLE events (run_id TEXT PRIMARY KEY)")
    main.commit()
    inserted, observed = Event(), Event()

    def rollback_writer():
        connection = connections.connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("INSERT INTO events VALUES ('rolled-back-run')")
            inserted.set()
            assert observed.wait(timeout=5)
        finally:
            connection.rollback()

    def commit_writer():
        assert inserted.wait(timeout=5)
        connection = connections.connection()
        try:
            # This read must not enter or see the other thread's transaction.
            assert not connection.in_transaction
            assert connection.execute("SELECT * FROM events").fetchall() == []
        finally:
            observed.set()
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO events VALUES ('committed-run')")
        connection.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(rollback_writer), pool.submit(commit_writer)]
            for future in futures:
                future.result(timeout=10)
        assert main.execute("SELECT * FROM events").fetchall() == [("committed-run",)]
    finally:
        connections.close()


@pytest.mark.parametrize("promoted", [False, True])
def test_parallel_checkpoint_head_cas_allows_exactly_one_worker(tmp_path, promoted):
    store = ACGCheckpointStore(db_path=tmp_path / "cas.sqlite3")
    store.save(run_id="run", checkpoint_id="source", state={"source": True})
    barrier = Barrier(2)

    def compete(index):
        _ = store._connection
        barrier.wait(timeout=5)
        try:
            if promoted:
                store.save_promoted(run_id="run", checkpoint_id=f"candidate-{index}", state={"winner": index},
                                    expected_source_version=1)
            else:
                store.save(run_id="run", checkpoint_id=f"candidate-{index}", state={"winner": index}, expected_version=1)
        except CheckpointConflictError:
            return False
        return True

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(compete, index) for index in range(2)]
            results = [future.result(timeout=10) for future in futures]
        assert sorted(results) == [False, True]
        assert store.latest_version(run_id="run") == 2
        assert store.load_latest(run_id="run")[1] == {"winner": results.index(True)}
        assert store.load(run_id="run", checkpoint_id="source") == {"source": True}
    finally:
        store.close()


def test_new_worker_connection_cannot_recreate_a_missing_database(tmp_path):
    path = Path(tmp_path / "removed.sqlite3")
    connections = ThreadLocalSQLiteConnections(path)
    connections.connection().close()
    path.unlink()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(connections.connection)
            with pytest.raises(sqlite3.OperationalError, match="unable to open"):
                future.result(timeout=5)
        assert not path.exists()
    finally:
        connections.close()
