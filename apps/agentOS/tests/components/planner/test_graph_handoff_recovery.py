"""Cross-connection/process uniqueness and cross-database failure cuts."""
import asyncio
import json
import multiprocessing
import os
import sqlite3
import pytest
from test_graph_handoff import prefix, _reopen, _build_prefix
from support.stores.graph_handoff_store import SQLiteGraphHandoffStore, SQLiteStagedGraphCheckpointStore


def _compete(folder, definition, act, key, start, results):
    try:
        rt, _, _, _, _ = _reopen(folder, definition)
        assert start.wait(60)
        result = rt.prepare_graph_handoff(act, idempotency_key=key)
        results.put({"pid": os.getpid(), "key":key, "result": result.model_dump(mode="json")})
    except BaseException as exc:
        results.put({"error": repr(exc), "pid": os.getpid()})


@pytest.mark.parametrize("same_key", [True, False])
@pytest.mark.slow_multiprocess
def test_two_real_processes_cannot_confirm_two_handoffs(prefix, same_key):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    before = workflow.get_run(run_id)
    definition = rt._workflow_for_run(before).model_dump(mode="json", by_alias=True)
    ctx = multiprocessing.get_context("spawn")
    start, results = ctx.Event(), ctx.Queue()
    workers = [ctx.Process(target=_compete, args=(str(workflow.db_path.parent), definition,
        act, "same" if same_key else str(i), start, results)) for i in range(2)]
    for w in workers: w.start()
    start.set()
    try:
        outcomes = [results.get(timeout=90) for _ in workers]
    finally:
        for w in workers:
            w.join(10)
            if w.is_alive(): w.terminate(); w.join(10)
    assert all(w.exitcode == 0 for w in workers) and all("error" not in r for r in outcomes), outcomes
    assert sum(o["result"]["status"] == "STATE_PREPARED" for o in outcomes) == 1, outcomes
    winner = ledger.handoff_for(act)
    assert winner.status == "STATE_PREPARED"
    assert rt.prepare_graph_handoff(act, idempotency_key=winner.idempotency_key).status == "IDEMPOTENT_REPLAY"
    with ledger.connection() as conn:
        assert conn.execute("SELECT count(*) FROM graph_handoffs").fetchone()[0] == 1
    with staged.connection() as conn:
        assert conn.execute("SELECT count(*) FROM staged_graph_checkpoints").fetchone()[0] == 1
    assert workflow.get_run(run_id) == before and agent.calls == ["A"]


@pytest.mark.parametrize("cut", ["intent", "stage_ack", "confirmation", "commit_ack"])
@pytest.mark.slow_fault_injection
def test_write_failure_and_lost_ack_reconcile_original_key(prefix, monkeypatch, cut):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    before = workflow.get_run(run_id)
    if cut in {"intent", "confirmation"}:
        method = "_append_handoff" if cut == "intent" else "_confirm_handoff"
        original = getattr(ledger, method)
        def fail(record):
            original(record)
            raise sqlite3.OperationalError("after handoff write, before COMMIT")
        monkeypatch.setattr(ledger, method, fail)
    elif cut == "stage_ack":
        original = staged.stage
        def fail(record):
            original(record)
            raise sqlite3.OperationalError("external stage committed, ACK lost")
        monkeypatch.setattr(staged, "stage", fail)
    else:
        original = ledger._connect
        commits = []
        class Connection:
            def __init__(self): self.inner = original()
            def __getattr__(self, name): return getattr(self.inner, name)
            def commit(self):
                self.inner.commit()
                commits.append(True)
                if len(commits) == 2: raise sqlite3.OperationalError("confirmation durable, ACK lost")
        monkeypatch.setattr(ledger, "_connect", Connection)
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "REJECTED" and result.code == "STORAGE_UNAVAILABLE", result
    fact = ledger.handoff_for(act)
    assert (fact is None) == (cut == "intent")
    if fact:
        assert fact.status == ("STATE_PREPARED" if cut == "commit_ack" else "STAGING")
        assert staged.get(fact.candidate.checkpoint_id) is not None
    monkeypatch.undo()
    replay = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert replay.status == ("IDEMPOTENT_REPLAY" if cut == "commit_ack" else "STATE_PREPARED"), replay
    assert workflow.get_run(run_id) == before and agent.calls == ["A"]


@pytest.mark.parametrize("source", ["permission", "identity", "receipt", "checkpoint", "input", "scope", "basis", "head",
                                    "identity_version", "semantic_identity", "pending_identity"])
@pytest.mark.slow_fault_injection
def test_external_stage_cannot_hide_new_source_facts(prefix, monkeypatch, source):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    original = staged.stage
    def stage(record):
        original(record)
        if source == "permission":
            monkeypatch.setattr(rt.mission_semantic_service, "authorize", lambda *a: False)
        elif source == "identity":
            monkeypatch.setattr(rt.identity_lifecycle.repositories.runs, "get", lambda _: None)
        elif source == "receipt":
            rt.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=f"commit:{run_id}:B:0")
        elif source == "checkpoint":
            rt.checkpoint_store.save(run_id=run_id, checkpoint_id="later-head", state=rt.checkpoint_store.load_latest(run_id=run_id)[1])
        elif source in {"identity_version", "semantic_identity", "pending_identity"}:
            repos = rt.identity_lifecycle.repositories
            with repos.storage.transaction() as conn:
                if source == "identity_version":
                    conn.execute("UPDATE acg_blueprints SET version=99")
                elif source == "semantic_identity":
                    receipt = rt.execution_value_store.list_node_commits(run_id=run_id)[0]
                    attempt = repos.attempts.get(receipt["nodeExecution"]["attemptId"])
                    conn.execute("UPDATE semantic_tasks SET semantic_key='step:foreign' WHERE task_id=?", (attempt.task_id,))
                else:
                    identity = repos.runs.get(run_id)
                    task = repos.task_bindings.find_for_acg_node("B", identity.blueprint_id)[0].task_id
                    conn.execute("UPDATE semantic_tasks SET semantic_key='step:foreign' WHERE task_id=?", (task,))
        elif source in {"basis", "head"}:
            with workflow._connect() as conn:
                conn.execute("UPDATE mission_semantic_state SET revision=revision+1" if source == "basis"
                             else "UPDATE graph_activation_heads SET active_graph_version=3")
        else:
            run = workflow.get_run(run_id)
            if source == "input":
                run.input["newInput"] = "stop"
                workflow.save_run(run)
            else:
                run.execution_scope = run.execution_scope.model_copy(update={"agent_ids": ()})
                with workflow._connect() as conn:
                    conn.execute("UPDATE runs SET payload=? WHERE run_id=?", (run.model_dump_json(by_alias=True), run_id))
    monkeypatch.setattr(staged, "stage", stage)
    assert rt.prepare_graph_handoff(act, idempotency_key="handoff").status == "REJECTED"
    assert ledger.handoff_for(act).status == "STAGING" and agent.calls == ["A"]
    with pytest.raises(ValueError):
        asyncio.run(rt.execute_prepared_run(run_id))
    assert agent.calls == ["A"]


@pytest.mark.parametrize("damage", ["missing", "content"])
def test_confirmed_stage_corruption_is_not_silently_repaired(prefix, damage):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    assert rt.prepare_graph_handoff(act, idempotency_key="handoff").status == "STATE_PREPARED"
    before = workflow.get_run(run_id)
    with staged.connection() as conn, conn:
        conn.execute("DELETE FROM staged_graph_checkpoints" if damage == "missing" else
                     "UPDATE staged_graph_checkpoints SET payload='{}'")
    assert rt.prepare_graph_handoff(act, idempotency_key="handoff").status == "REJECTED"
    assert ledger.handoff_for(act).status == "STATE_PREPARED"
    assert workflow.get_run(run_id) == before and agent.calls == ["A"]


def test_authority_absence_and_schema_upgrade_are_explicit(prefix):
    rt, workflow, agent, run_id, act, ledger, staged = prefix
    before = workflow.get_run(run_id)
    rt.graph_handoff_authority = None
    assert rt.prepare_graph_handoff(act, idempotency_key="handoff").code == "AUTHORITY_DENIED"
    SQLiteGraphHandoffStore.upgrade_schema(workflow.db_path)
    SQLiteStagedGraphCheckpointStore.upgrade_schema(rt.checkpoint_store.db_path)
    assert ledger.handoff_for(act) is None and workflow.get_run(run_id) == before
    with staged.connection() as conn, conn:
        conn.execute("DROP TABLE staged_graph_checkpoints")
        conn.execute("CREATE TABLE staged_graph_checkpoints(checkpoint_id TEXT)")
    with pytest.raises(RuntimeError, match="explicit handoff schema upgrade"):
        SQLiteStagedGraphCheckpointStore(rt.checkpoint_store.db_path)
    with pytest.raises(RuntimeError):
        SQLiteStagedGraphCheckpointStore.upgrade_schema(rt.checkpoint_store.db_path)
    assert agent.calls == ["A"]


def test_persistent_unique_activation_survives_independent_connection(prefix):
    rt, workflow, _, _, act, ledger, _ = prefix
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "STATE_PREPARED", result
    record = ledger.get_handoff(result.handoff_id)
    # Exercise the SQL constraint independently of both Runtime and OS locks.
    other = record.model_copy(update={"handoff_id":"other", "idempotency_key":"other"})
    independent = SQLiteGraphHandoffStore(workflow.db_path)
    with pytest.raises(sqlite3.IntegrityError), independent._transaction():
        independent._append_handoff(other)
    assert ledger.handoff_for(act) == record


def test_blocking_authorizer_cannot_publish_a_cached_operator_snapshot(prefix, monkeypatch):
    rt, workflow, _, run_id, act, ledger, _ = prefix
    authorize = rt.mission_semantic_service.authorize
    changed = []
    def edit(*args):
        if not changed:
            run = workflow.get_run(run_id)
            run.input["afterSourceCapture"] = "new operator instructions"
            workflow.save_run(run)
            changed.append(True)
        return authorize(*args)
    monkeypatch.setattr(rt.mission_semantic_service, "authorize", edit)
    assert rt.prepare_graph_handoff(act, idempotency_key="handoff").status == "REJECTED"
    assert ledger.handoff_for(act) is None and changed


def test_foreign_success_trace_cannot_prove_handoff_via_normal_save(prefix):
    from contracts.workflow import TraceEventType
    rt, workflow, _, run_id, act, ledger, _ = prefix
    run = workflow.get_run(run_id)
    matches = [e for e in run.trace if e.event_type == TraceEventType.STEP_SUCCEEDED and e.step_id == "A"]
    assert matches
    for event in matches:
        event.run_id = "a-different-run"
    workflow.save_run(run)
    assert workflow.get_run(run_id).trace == run.trace
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "REJECTED", result
    assert ledger.handoff_for(act) is None


def test_receipt_decision_ref_must_match_committed_execution_audit_ref(tmp_path, monkeypatch):
    """A valid but different allow decision cannot be substituted in the receipt."""
    def replace_receipt_decision(authority, run_id):
        rt = authority.runtime
        receipt = rt.execution_value_store.list_node_commits(run_id=run_id)[0]
        decision = rt.decision_store.assert_decision(run_id=run_id, step_id="A",
            decision_ref=receipt["auditDecisionRef"], outcomes={"allow"})
        from contracts.governance import PolicyDecision
        alternate = PolicyDecision.model_validate(decision.model_copy(update={
            "decision_id": "other-valid-allow", "rationale": "independent valid allow for the same step"
        }).model_dump(mode="json", by_alias=True))
        rt.decision_store.save(run_id=run_id, step_id="A", decision=alternate)
        receipt["auditDecisionRef"] = alternate.decision_id
        with sqlite3.connect(rt.execution_value_store.db_path) as conn:
            conn.execute("UPDATE acg_node_commits SET payload_json=? WHERE commit_id=?",
                         (json.dumps(receipt), receipt["commitId"]))

    rt, workflow, agent, run_id, act, ledger, _ = _build_prefix(
        tmp_path, monkeypatch, before_accept=replace_receipt_decision)
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "REJECTED", result
    assert ledger.handoff_for(act) is None and agent.calls == ["A"]


def test_identity_execution_binding_must_match_runtime_attempt_binding(tmp_path, monkeypatch):
    """A schema-valid Identity binding cannot rewrite the executed resource."""
    def replace_identity_resource(authority, run_id):
        rt = authority.runtime
        receipt = rt.execution_value_store.list_node_commits(run_id=run_id)[0]
        attempt_id = receipt["nodeExecution"]["attemptId"]
        run = rt.workflow_store.get_run(run_id)
        execution = run.execution_state["executionBindings"]["A"]
        identity = rt.identity_lifecycle.repositories.execution_bindings.get_for_attempt(attempt_id)
        assert identity.resource_id == execution["resourceId"]
        assert run.execution_state["resourceBindings"]["A"] == execution["resourceId"]
        with rt.identity_lifecycle.repositories.storage.transaction() as conn:
            conn.execute("UPDATE execution_bindings SET resource_id=? WHERE attempt_id=?",
                         ("resource:substituted", attempt_id))

    rt, workflow, agent, run_id, act, ledger, _ = _build_prefix(
        tmp_path, monkeypatch, before_accept=replace_identity_resource)
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "REJECTED", result
    assert ledger.handoff_for(act) is None and agent.calls == ["A"]


@pytest.mark.parametrize("field", ["version", "graph_id", "semantic_key", "semantic_mission", "missing_mission", "missing_task",
                                   "pending_key", "snapshot_task_id", "identity_plan_version"])
def test_source_identity_envelope_and_ownership_must_agree(prefix, monkeypatch, field):
    rt, workflow, agent, run_id, act, ledger, _ = prefix
    repos = rt.identity_lifecycle.repositories
    identity = repos.runs.get(run_id)
    receipt = rt.execution_value_store.list_node_commits(run_id=run_id)[0]
    attempt = repos.attempts.get(receipt["nodeExecution"]["attemptId"])
    if field == "missing_mission":
        monkeypatch.setattr(repos.missions, "get", lambda _: None)
    elif field == "missing_task":
        monkeypatch.setattr(repos.semantic_tasks, "get", lambda _: None)
    else:
        if field == "semantic_mission":
            foreign = rt.create_mission("another Mission", workflow_id="abc")
        # These four updates preserve schema and enabled FK constraints. They
        # simulate damaged persisted identity, without forging any execution.
        with repos.storage.transaction() as conn:
            if field == "pending_key":
                task = repos.task_bindings.find_for_acg_node("B", identity.blueprint_id)[0].task_id
                conn.execute("UPDATE semantic_tasks SET semantic_key='step:foreign' WHERE task_id=?", (task,))
            elif field == "snapshot_task_id":
                conn.execute("UPDATE task_plan_nodes SET task_id=? WHERE mission_id=? AND semantic_key='step:B'",
                             (attempt.task_id, identity.mission_id))
            elif field == "identity_plan_version":
                conn.execute("UPDATE workflow_runs_v2 SET metadata_json=json_set(metadata_json,'$.taskPlanVersion',99) WHERE run_id=?", (run_id,))
            elif field in {"semantic_key", "semantic_mission"}:
                column = "semantic_key" if field == "semantic_key" else "mission_id"
                conn.execute(f"UPDATE semantic_tasks SET {column}=? WHERE task_id=?", (
                    "step:foreign" if field == "semantic_key" else foreign.mission_id, attempt.task_id))
            else:
                conn.execute(f"UPDATE acg_blueprints SET {field}=? WHERE blueprint_id=?", (
                    99 if field == "version" else "foreign-graph", identity.blueprint_id))
    before = workflow.get_run(run_id)
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    assert result.status == "REJECTED", result
    assert ledger.handoff_for(act) is None and workflow.get_run(run_id) == before and agent.calls == ["A"]


def _before_intent(folder, definition, act):
    rt, _, _, ledger, _ = _reopen(folder, definition)
    def crash(record): os._exit(36)
    ledger._append_handoff = crash
    result = rt.prepare_graph_handoff(act, idempotency_key="handoff")
    raise AssertionError(result)


@pytest.mark.slow_multiprocess
def test_process_death_before_intent_has_no_external_stage(prefix):
    rt, workflow, _, run_id, act, ledger, staged = prefix
    before = workflow.get_run(run_id)
    definition = rt._workflow_for_run(before).model_dump(mode="json", by_alias=True)
    worker = multiprocessing.get_context("spawn").Process(target=_before_intent,
        args=(str(workflow.db_path.parent), definition, act))
    worker.start()
    worker.join(60)
    if worker.is_alive(): worker.terminate(); worker.join(10)
    assert worker.exitcode == 36
    assert ledger.handoff_for(act) is None
    with staged.connection() as conn:
        assert conn.execute("SELECT count(*) FROM staged_graph_checkpoints").fetchone()[0] == 0
    assert workflow.get_run(run_id) == before
    assert rt.prepare_graph_handoff(act, idempotency_key="handoff").status == "STATE_PREPARED"
