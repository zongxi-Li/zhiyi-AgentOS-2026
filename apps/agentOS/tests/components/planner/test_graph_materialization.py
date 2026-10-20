"""S03-01: real Runtime and SQLite, inactive-only transaction evidence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest
from contracts import stable_checksum
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from contracts.workflow import WorkflowStatus
from components.executor.compiler import ACGGraphCompiler
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from test_graph_revision_commit import accepted_source
from test_horizon import ready_boundary, runtime_boundary
from test_planning_commit_runtime import dump_databases


def setup(ready_boundary):
    runtime, workflow, ledger, run_id, source, agent = accepted_source(ready_boundary)
    accepted = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert accepted.status == "ACCEPTED", accepted.model_dump()
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    journal = SQLiteGraphMaterializationStore(workflow.db_path)
    runtime.enable_graph_materialization(journal)
    return runtime, workflow, journal, run_id, accepted.commit_id, agent


def unchanged_except_journal(workflow):
    result = dump_databases(workflow, include_ledger=True)
    return {path: tuple(line for line in lines if 'INSERT INTO "graph_materializations"' not in line)
            for path, lines in result.items()}


def test_inactive_package_is_complete_read_only_and_restartable(ready_boundary, monkeypatch):
    runtime, workflow, journal, run_id, commit, agent = setup(ready_boundary)
    before = unchanged_except_journal(workflow)
    monkeypatch.setattr(runtime.semantic_revision_service, "prepare", lambda **kw: pytest.fail("replacement"))
    monkeypatch.setattr(runtime.runtime_binding_service, "prepare", lambda **kw: pytest.fail("binding"))
    receipt = runtime.materialize_graph_revision(commit, idempotency_key="materialize")
    assert receipt.status == "MATERIALIZED_INACTIVE", receipt.model_dump()
    record = journal.get_materialization(receipt.materialization_id)
    proposal = journal.get(commit).proposal_payload
    assert record.package == ACGGraphCompiler().compile_package(proposal.candidate_graph, run_id=run_id)
    assert record.package.blueprint_hash == stable_checksum(proposal.candidate_graph.model_dump(mode="json", by_alias=True))
    assert unchanged_except_journal(workflow) == before and not agent.calls
    assert workflow.get_run(run_id).acg_blueprint["version"] == 1
    runtime.enable_graph_materialization(SQLiteGraphMaterializationStore(workflow.db_path))
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", lambda *a, **kw: pytest.fail("recompiled on replay"))
    replay = runtime.materialize_graph_revision(commit, idempotency_key="materialize")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.materialization_id == receipt.materialization_id
    assert runtime.materialize_graph_revision(commit, idempotency_key="other").status == "REJECTED"


@pytest.mark.parametrize("change", ["cancel", "permission", "receipt", "input", "checkpoint", "graph", "plan", "identity", "catalog", "workflow", "authority"])
def test_compile_window_changes_cannot_publish(ready_boundary, monkeypatch, change):
    runtime, workflow, journal, run_id, commit, _ = setup(ready_boundary)
    original = ACGGraphCompiler.compile_package
    def compile_then_change(compiler, *args, **kw):
        assert getattr(journal._local, "connection", None) is None
        package = original(compiler, *args, **kw)
        run = workflow.get_run(run_id)
        if change == "cancel": runtime._cancellation_event(run_id).set()
        elif change == "permission": runtime.mission_semantic_service.authorize = lambda *a: False
        elif change == "receipt": runtime.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=f"commit:{run_id}:A:1")
        elif change == "input": run.input["newOperator"] = "preserve"
        elif change == "checkpoint":
            from runtime.state_persistence import acg_execution_state_from_run
            state = acg_execution_state_from_run(run)
            state.graph_id = run.acg_blueprint["graphId"]
            state.review_payload = {"subjectType": "node", "subjectId": "A"}
            runtime.acg_state_persistence.save_checkpoint(run, state)
        elif change == "graph": run.acg_blueprint["version"] += 1
        elif change == "plan": run.execution_state["taskPlan"]["planVersion"] += 1
        elif change == "identity": runtime.semantic_principal_provider = lambda: None
        elif change == "catalog": runtime.capability_catalog.get("task_understanding").output_contract["changed"] = True
        elif change == "workflow":
            wf = runtime._workflow_for_run(run)
            runtime.workflow_registry.register(wf.model_copy(update={"domain": "changed"}))
        else: runtime.graph_materialization_authority = None
        if change in {"input", "graph", "plan"}: workflow.save_run(run)
        return package
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", compile_then_change)
    result = runtime.materialize_graph_revision(commit, idempotency_key="materialize")
    assert result.status == "REJECTED", result.model_dump()
    assert journal.materialization_for(commit) is None


@pytest.mark.parametrize("same_key", [True, False])
def test_cross_connection_competitors_have_one_durable_result(ready_boundary, same_key):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    # Explicit single active authority; its store opens a new connection per transaction.
    authority = runtime.graph_materialization_authority
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: authority.materialize(commit,
            idempotency_key="same" if same_key else f"different:{i}"), range(2)))
    assert sum(r.status == "MATERIALIZED_INACTIVE" for r in results) == 1, [r.model_dump() for r in results]
    assert {r.status for r in results} == ({"MATERIALIZED_INACTIVE", "IDEMPOTENT_REPLAY"} if same_key else
                                        {"MATERIALIZED_INACTIVE", "REJECTED"})
    reopened = SQLiteGraphMaterializationStore(workflow.db_path)
    assert reopened.materialization_for(commit) is not None


@pytest.mark.parametrize("stage", ["before_insert", "insert", "commit_ack"])
def test_atomic_faults_reconcile_original_key(ready_boundary, monkeypatch, stage):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    original = journal._connect
    if stage == "commit_ack":
        class Connection:
            def __init__(self): self.inner = original()
            def __getattr__(self, key): return getattr(self.inner, key)
            def commit(self):
                self.inner.commit()
                raise sqlite3.OperationalError("lost ack")
        monkeypatch.setattr(journal, "_connect", Connection)
    elif stage == "before_insert":
        original_append = journal._append_materialization
        monkeypatch.setattr(journal, "_append_materialization", lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("write fault")))
    else:
        with journal.connection() as conn, conn:
            conn.execute("CREATE TRIGGER mat_fault AFTER INSERT ON graph_materializations BEGIN SELECT RAISE(ABORT,'fault'); END")
    result = runtime.materialize_graph_revision(commit, idempotency_key="materialize")
    assert result.status == "REJECTED"
    monkeypatch.setattr(journal, "_connect", original)
    if stage == "before_insert": monkeypatch.setattr(journal, "_append_materialization", original_append)
    if stage == "insert":
        with journal.connection() as conn, conn: conn.execute("DROP TRIGGER mat_fault")
    assert (journal.materialization_for(commit) is not None) == (stage == "commit_ack")
    runtime.enable_graph_materialization(SQLiteGraphMaterializationStore(workflow.db_path))
    replay = runtime.materialize_graph_revision(commit, idempotency_key="materialize")
    assert replay.status == ("IDEMPOTENT_REPLAY" if stage == "commit_ack" else "MATERIALIZED_INACTIVE"), replay.model_dump()


@pytest.mark.parametrize("damage", ["checksum", "package", "candidate", "bindings", "provenance"])
def test_corrupted_content_is_rejected(ready_boundary, damage):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    if damage in {"checksum", "package"}:
        receipt = runtime.materialize_graph_revision(commit, idempotency_key="materialize")
        assert receipt.status == "MATERIALIZED_INACTIVE"
        with journal.connection() as conn, conn:
            if damage == "checksum": conn.execute("UPDATE graph_materializations SET checksum=?", ("0"*64,))
            else:
                row = conn.execute("SELECT payload FROM graph_materializations").fetchone()
                raw = json.loads(row[0]); raw["package"]["checksum"] = "0"*64
                conn.execute("UPDATE graph_materializations SET payload=?", (json.dumps(raw),))
    else:
        with journal.connection() as conn, conn:
            raw = json.loads(conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (commit,)).fetchone()[0])
            if damage == "candidate": raw["proposalPayload"]["candidateGraph"]["metadata"]["changed"] = True
            elif damage == "bindings": raw["proposalPayload"]["nextBindings"] = []
            else: raw["proposalPayload"]["sourceProvenance"]["staticFingerprint"] = "0"*64
            conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?", (json.dumps(raw), commit))
    assert runtime.materialize_graph_revision(commit, idempotency_key="materialize").status == "REJECTED"


@pytest.mark.parametrize("damage", ["missing", "wrong_index", "version"])
def test_schema_is_explicit_and_actual_definitions_are_checked(ready_boundary, damage):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    with journal.connection() as conn, conn:
        if damage == "version": conn.execute("UPDATE graph_materialization_schema SET version=99")
        else:
            conn.execute("DROP INDEX graph_materialization_source_unique")
            if damage == "wrong_index": conn.execute("CREATE INDEX graph_materialization_source_unique ON graph_materializations(source_commit_id)")
    with pytest.raises(RuntimeError): SQLiteGraphMaterializationStore(workflow.db_path)
    assert runtime.materialize_graph_revision(commit, idempotency_key="materialize").status == "REJECTED"


def test_absent_authority_and_schema_do_not_fall_back(ready_boundary):
    runtime, workflow, ledger, run_id, source, _ = accepted_source(ready_boundary)
    graph = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert runtime.materialize_graph_revision(graph.commit_id, idempotency_key="key").code == Code.AUTHORITY_DENIED
    with pytest.raises(sqlite3.OperationalError): SQLiteGraphMaterializationStore(workflow.db_path)
    runtime.planning_commit_authority = None
    before = dump_databases(workflow, include_ledger=True)
    asyncio.run(runtime.execute_prepared_run(run_id))
    assert dump_databases(workflow, include_ledger=True) == before


def test_completed_prefix_is_preserved_in_full_inactive_package(ready_boundary):
    from contracts.workflow import StepStatus
    from contracts.runtime_planning import RuntimePlanningState
    from test_planning_commit_runtime import attach, patch
    runtime, workflow, _, run_id, _ = ready_boundary
    run = workflow.get_run(run_id)
    run.steps[0].status = StepStatus.COMPLETED
    run.steps[0].attempt = 1
    loop = RuntimePlanningState.model_validate(run.execution_state["planningLoop"])
    observed = loop.current.observation.model_copy(update={"steps": (
        loop.current.observation.steps[0].model_copy(update={"status": "completed"}),)})
    run.execution_state["planningLoop"] = loop.model_copy(update={"current": loop.current.model_copy(
        update={"observation": observed, "observation_id": observed.fingerprint()})}).model_dump(by_alias=True, mode="json")
    workflow.save_run(run)
    ledger = attach(runtime, workflow)
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, patch(run).model_copy(update={"relations": ()}),
            proposal_id="tail", idempotency_key="tail")
    assert source.status == "ACCEPTED"
    graph = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert graph.status == "ACCEPTED"
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    journal = SQLiteGraphMaterializationStore(workflow.db_path)
    runtime.enable_graph_materialization(journal)
    before = unchanged_except_journal(workflow)
    result = runtime.materialize_graph_revision(graph.commit_id, idempotency_key="mat")
    assert result.status == "MATERIALIZED_INACTIVE", result.model_dump()
    record = journal.get_materialization(result.materialization_id)
    assert "A" in {n.node_id for n in record.package.nodes}
    assert workflow.get_run(run_id).steps[0].status == StepStatus.COMPLETED
    assert unchanged_except_journal(workflow) == before


@pytest.mark.parametrize("barrier", ["control_frames", "loop_paths", "consensus_results", "review", "terminal"])
def test_current_control_review_and_terminal_boundaries_fail_closed(ready_boundary, barrier):
    runtime, workflow, journal, run_id, commit, _ = setup(ready_boundary)
    run = workflow.get_run(run_id)
    if barrier == "review":
        run.execution_state["reviewPayload"] = {"subjectType": "node", "subjectId": "A"}
    elif barrier == "terminal": run.status = WorkflowStatus.CANCELLED
    elif barrier == "control_frames": run.execution_state["controlFrames"] = [{"controlId": "loop", "controlType": "loop"}]
    elif barrier == "loop_paths": run.execution_state["loopPaths"] = {"loop": ["A"]}
    else: run.execution_state["consensusResults"] = {"join": {"status": "accepted"}}
    workflow.save_run(run)
    result = runtime.materialize_graph_revision(commit, idempotency_key="mat")
    assert result.status == "REJECTED" and journal.materialization_for(commit) is None


def test_stale_acceptance_head_and_key_content_conflict(ready_boundary):
    from test_planning_commit_runtime import patch
    runtime, workflow, journal, run_id, commit, _ = setup(ready_boundary)
    assert runtime.materialize_graph_revision(commit, idempotency_key="mat").status == "MATERIALIZED_INACTIVE"
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, patch(workflow.get_run(run_id)),
            proposal_id="next-source", idempotency_key="next-source")
    assert source.status == "ACCEPTED"
    graph = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="next-graph")
    assert graph.status == "ACCEPTED"
    assert runtime.materialize_graph_revision(commit, idempotency_key="mat").code == Code.STALE_COMMITMENT
    assert runtime.materialize_graph_revision(graph.commit_id, idempotency_key="mat").code == Code.DUPLICATE_CONFLICT
    assert journal.materialization_for(graph.commit_id) is None


def test_compiler_checksum_failure_never_publishes(ready_boundary, monkeypatch):
    runtime, _, journal, _, commit, _ = setup(ready_boundary)
    original = ACGGraphCompiler.compile_package
    def corrupted(compiler, *args, **kwargs):
        return original(compiler, *args, **kwargs).model_copy(update={"checksum": "0"*64})
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", corrupted)
    assert runtime.materialize_graph_revision(commit, idempotency_key="mat").status == "REJECTED"
    assert journal.materialization_for(commit) is None


def test_review_and_recovery_continue_only_the_original_graph(ready_boundary, monkeypatch):
    from contracts.runtime_planning import RuntimePlanningDecision
    from contracts.workflow import ReviewDecision
    from test_planning_commit_runtime import attach, patch
    runtime, workflow, agent, run_id, state = ready_boundary
    ledger = attach(runtime, workflow)
    run = workflow.get_run(run_id)
    runtime.mission_manager.mark_running(runtime.mission_manager.get_mission(run.mission_id))
    class Planner:
        def decide_runtime(self, **kwargs):
            return RuntimePlanningDecision(observationId=kwargs["observation"].fingerprint(), action="revise",
                                           reason="candidate", taskPlanPatch=patch(run))
    monkeypatch.setattr(runtime.runtime_planning_coordinator, "planner_for_run", lambda _: Planner())
    assert asyncio.run(runtime.runtime_planning_coordinator.boundary(run, state, "resume")) == "stop"
    graph = runtime.accept_graph_revision(run_id, ledger.latest(run.mission_id).commit_id, idempotency_key="graph")
    assert graph.status == "ACCEPTED"
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    journal = SQLiteGraphMaterializationStore(workflow.db_path)
    runtime.enable_graph_materialization(journal)
    receipt = runtime.materialize_graph_revision(graph.commit_id, idempotency_key="mat")
    assert receipt.status == "MATERIALIZED_INACTIVE", receipt.model_dump()
    before = dump_databases(workflow, include_ledger=True)
    asyncio.run(runtime._recover_pending_planning_transitions(limit=10))
    assert dump_databases(workflow, include_ledger=True) == before and not agent.calls
    class ContinueOriginal:
        def decide_runtime(self, **kwargs):
            obs = kwargs["observation"]
            return RuntimePlanningDecision(observationId=obs.fingerprint(),
                action="continue" if obs.remaining_step_ids else "complete", reason="original")
    monkeypatch.setattr(runtime.runtime_planning_coordinator, "planner_for_run", lambda _: ContinueOriginal())
    held = workflow.get_run(run_id)
    result = asyncio.run(runtime.apply_review(ReviewDecision(runId=run_id, stepId=held.current_step_id,
        decision="approved", operationId="original-approval")))
    assert result.status == WorkflowStatus.COMPLETED
    assert result.acg_blueprint["version"] == 1 and agent.calls == ["A"] and len(result.steps) == 1
    assert journal.get_materialization(receipt.materialization_id).status == "MATERIALIZED_INACTIVE"


@pytest.mark.parametrize("damage", ["parent", "ancestor", "source_body"])
def test_acceptance_chain_cannot_be_bypassed(ready_boundary, damage):
    runtime, _, journal, _, commit, _ = setup(ready_boundary)
    graph = journal.get(commit)
    with journal.connection() as conn, conn:
        if damage == "ancestor":
            conn.execute("DELETE FROM planning_commit_records WHERE commit_id=?", (graph.parent_commit_id,))
        else:
            target = commit if damage == "parent" else graph.parent_commit_id
            raw = json.loads(conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (target,)).fetchone()[0])
            if damage == "parent": raw["parentCommitId"] = "foreign"
            else: raw["proposalPayload"]["addNodes"][0]["objective"] = "unaccepted"
            conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?", (json.dumps(raw), target))
    assert runtime.materialize_graph_revision(commit, idempotency_key="mat").status == "REJECTED"
    assert journal.materialization_for(commit) is None


def test_schema_management_is_idempotent_and_atomic(ready_boundary):
    _, workflow, journal, _, commit, _ = setup(ready_boundary)
    before = dump_databases(workflow, include_ledger=True)
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    assert dump_databases(workflow, include_ledger=True) == before
    with journal.connection() as conn, conn:
        conn.execute("DROP INDEX graph_materialization_source_unique")
        conn.execute("CREATE INDEX graph_materialization_source_unique ON graph_materializations(source_commit_id)")
    malformed = dump_databases(workflow, include_ledger=True)
    with pytest.raises(RuntimeError): SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    assert dump_databases(workflow, include_ledger=True) == malformed


def test_constructor_never_creates_a_database(tmp_path):
    path = tmp_path / "absent.sqlite3"
    with pytest.raises(sqlite3.OperationalError): SQLiteGraphMaterializationStore(path)
    assert not path.exists()


def test_final_source_validation_closes_authority_capture_window(ready_boundary, monkeypatch):
    runtime, _, journal, _, commit, _ = setup(ready_boundary)
    from runtime import graph_materialization
    original = graph_materialization.safe_cut
    calls = []
    def revoke_after_check(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            runtime.mission_semantic_service.authorize = lambda *a: False
        return result
    monkeypatch.setattr(graph_materialization, "safe_cut", revoke_after_check)
    assert runtime.materialize_graph_revision(commit, idempotency_key="mat").code == Code.AUTHORITY_DENIED
    assert journal.materialization_for(commit) is None


def test_final_identity_callback_cannot_cancel_after_authorization(ready_boundary):
    runtime, _, journal, run_id, commit, _ = setup(ready_boundary)
    principal = runtime.semantic_principal_provider()
    calls = []
    def current_identity():
        calls.append(True)
        if len(calls) == 4:
            runtime._cancellation_event(run_id).set()
        return principal
    runtime.semantic_principal_provider = current_identity
    result = runtime.materialize_graph_revision(commit, idempotency_key="mat")
    assert result.code == Code.AUTHORITY_DENIED, result.model_dump()
    assert journal.materialization_for(commit) is None
