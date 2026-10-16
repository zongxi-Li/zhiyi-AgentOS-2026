"""S03-02A: durable activation authority, version CAS, and execution fencing."""
import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from contracts.workflow import StepStatus, WorkflowStatus
from support.stores.graph_activation_store import SQLiteGraphActivationStore
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from test_graph_materialization import setup as materialized
from test_graph_revision_commit import accepted_source
from test_horizon import ready_boundary, runtime_boundary


def chain(ready_boundary, *, prepare_key=None):
    """Real Runtime chain up to an inactive materialization, activation enabled."""
    runtime, workflow, journal, run_id, commit, agent = materialized(ready_boundary)
    receipt = runtime.materialize_graph_revision(commit, idempotency_key="mat")
    assert receipt.status == "MATERIALIZED_INACTIVE", receipt.model_dump()
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    activations = SQLiteGraphActivationStore(workflow.db_path)
    runtime.enable_graph_activation(activations)
    materialization_id = receipt.materialization_id
    if prepare_key is None:
        return runtime, workflow, activations, run_id, materialization_id, agent
    prepared = runtime.prepare_graph_activation(materialization_id, idempotency_key=prepare_key)
    assert prepared.status == "ACTIVATION_PREPARED", prepared.model_dump()
    return runtime, workflow, activations, run_id, materialization_id, agent


def activated(ready_boundary):
    runtime, workflow, activations, run_id, materialization_id, agent = chain(ready_boundary, prepare_key="act")
    receipt = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert receipt.status == "ACTIVATED_PAUSED", receipt.model_dump()
    return runtime, workflow, activations, run_id, materialization_id, agent, receipt.activation_id


def test_preparation_is_durable_read_only_and_replayable(ready_boundary):
    runtime, workflow, activations, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    before = workflow.get_run(run_id)
    prepared = activations.activation_for(materialization_id)
    assert prepared.status == "ACTIVATION_PREPARED" and prepared.source_graph_version == 1
    assert prepared.candidate_graph_version == 2 and prepared.idempotency_key == "act"
    run = workflow.get_run(run_id)
    assert run.acg_blueprint["version"] == 1 and "graphActivation" not in run.execution_state
    assert run.model_dump(mode="json") == before.model_dump(mode="json")
    assert activations.head(run_id) is None
    # A restarted process replays the same durable preparation.
    reopened = SQLiteGraphActivationStore(workflow.db_path)
    runtime.enable_graph_activation(reopened)
    replay = runtime.prepare_graph_activation(materialization_id, idempotency_key="act")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.activation_id == prepared.activation_id
    other = runtime.prepare_graph_activation(materialization_id, idempotency_key="other")
    assert other.status == "REJECTED" and other.code == Code.DUPLICATE_CONFLICT


def test_commit_switches_head_and_projection_atomically(ready_boundary):
    runtime, workflow, activations, run_id, materialization_id, agent, activation_id = activated(ready_boundary)
    run = workflow.get_run(run_id)
    head = activations.head(run_id)
    assert head.activation_id == activation_id and head.active_graph_version == 2
    assert run.acg_blueprint["version"] == 2
    assert run.execution_state["graphVersion"] == 2
    assert run.execution_state["compiledPackageChecksum"]
    assert run.execution_state["taskPlanVersion"] == 2
    assert run.execution_state["checkpointId"] is None
    projection = run.execution_state["graphActivation"]
    assert (projection["status"] == "ACTIVATED_PAUSED" and projection["executionPermit"] is None
            and projection["activeGraphVersion"] == 2 and projection["activationId"] == activation_id)
    journal = activations.activation_for(materialization_id)
    assert journal.status == "ACTIVATED_PAUSED"
    assert {s.step_id for s in run.steps} == {"A", "work"}
    # The completed prefix channel references survive untouched on the Run.
    assert not agent.calls


def test_same_key_commit_replay_has_one_durable_fact(ready_boundary):
    runtime, workflow, activations, run_id, materialization_id, _, activation_id = activated(ready_boundary)
    replay = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.activation_id == activation_id
    with activations.connection() as conn, conn:
        rows = conn.execute("SELECT activation_id FROM graph_activations").fetchall()
        heads = conn.execute("SELECT activation_id FROM graph_activation_heads").fetchall()
    assert [r[0] for r in rows] == [activation_id] and [r[0] for r in heads] == [activation_id]


def test_competing_keys_produce_one_preparation(ready_boundary):
    runtime, _, activations, run_id, materialization_id, _ = chain(ready_boundary)
    authority = runtime.graph_activation_authority
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda key: authority.prepare(materialization_id, idempotency_key=key),
                                ("key:1", "key:2")))
    statuses = {r.status for r in results}
    assert statuses == {"ACTIVATION_PREPARED", "REJECTED"}, [r.model_dump() for r in results]
    assert sum(r.code == Code.DUPLICATE_CONFLICT for r in results if r.status == "REJECTED") == 1
    with activations.connection() as conn:
        assert len(conn.execute("SELECT 1 FROM graph_activations").fetchall()) == 1


def test_commit_requires_the_matching_preparation(ready_boundary):
    runtime, _, _, run_id, materialization_id, _ = chain(ready_boundary)
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED" and result.code == Code.INVALID_PROPOSAL
    runtime.prepare_graph_activation(materialization_id, idempotency_key="act")
    wrong = runtime.commit_graph_activation(materialization_id, idempotency_key="other")
    assert wrong.status == "REJECTED" and wrong.code == Code.DUPLICATE_CONFLICT


@pytest.mark.parametrize("mutation,expected", [
    ("plan", Code.STALE_STRATEGY), ("mission", Code.STALE_STRATEGY),
    ("permission", Code.AUTHORITY_DENIED), ("scope", Code.STALE_STRATEGY),
    ("graph_version", Code.STALE_GRAPH), ("input", Code.STALE_STRATEGY),
])
def test_stale_sources_are_rejected_before_and_after_preparation(ready_boundary, mutation, expected):
    runtime, workflow, _, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    run = workflow.get_run(run_id)
    if mutation == "permission":
        runtime.mission_semantic_service.authorize = lambda *a: False
    elif mutation == "mission":
        from contracts.mission_semantic import MissionSemanticRequest
        runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
            missionId=run.mission_id, operationId="change", expectedMissionRevision=1,
            objective="changed", constraints=[], sourceRefs=[]))
    else:
        if mutation == "plan": run.execution_state["taskPlan"]["planVersion"] += 1
        if mutation == "graph_version": run.acg_blueprint["version"] = 3
        if mutation == "input": run.input["operator"] = "changed"
        if mutation == "scope": run.execution_scope = run.execution_scope.model_copy(update={"capability_ids": ()})
        workflow.save_run(run)
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED" and result.code == expected, result.model_dump()
    assert workflow.get_run(run_id).acg_blueprint["version"] != 2
    fresh = runtime.prepare_graph_activation(materialization_id, idempotency_key="fresh")
    assert fresh.status == "REJECTED" and fresh.code == expected, fresh.model_dump()


def test_new_receipt_blocks_activation(ready_boundary):
    runtime, workflow, _, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    runtime.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=f"commit:{run_id}:A:1")
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED" and result.code == Code.STALE_STRATEGY, result.model_dump()
    assert workflow.get_run(run_id).acg_blueprint["version"] == 1


def test_latest_checkpoint_change_blocks_activation(ready_boundary):
    from runtime.state_persistence import acg_execution_state_from_run
    runtime, workflow, _, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    run = workflow.get_run(run_id)
    state = acg_execution_state_from_run(run)
    state.graph_id = run.acg_blueprint["graphId"]
    runtime.acg_state_persistence.save_checkpoint(run, state)
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED" and result.code == Code.CONTROL_BARRIER_BLOCKED, result.model_dump()
    assert workflow.get_run(run_id).acg_blueprint["version"] == 1


@pytest.mark.parametrize("barrier", ["review", "active", "control"])
def test_unresolved_review_and_active_work_block_activation(ready_boundary, barrier):
    runtime, workflow, _, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    run = workflow.get_run(run_id)
    if barrier == "review":
        run.steps[0].status = StepStatus.WAITING_REVIEW
    elif barrier == "active":
        run.active_step_ids = ["A"]
    else:
        run.execution_state["controlFrames"] = [{"controlId": "loop", "controlType": "loop"}]
    workflow.save_run(run)
    # The mutated Run projection no longer matches the frozen materialization
    # sources; the acceptance chain refuses before safe-cut even reruns.
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED" and result.code == Code.STALE_STRATEGY, result.model_dump()
    assert workflow.get_run(run_id).acg_blueprint["version"] == 1


def test_activation_transaction_failure_rolls_back_completely(ready_boundary, monkeypatch):
    runtime, workflow, activations, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    original = activations._connect
    with activations.connection() as conn, conn:
        conn.execute("CREATE TRIGGER head_fault BEFORE INSERT ON graph_activation_heads "
                     "BEGIN SELECT RAISE(ABORT,'fault'); END")
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED", result.model_dump()
    assert activations.head(run_id) is None
    assert activations.activation_for(materialization_id).status == "ACTIVATION_PREPARED"
    assert workflow.get_run(run_id).acg_blueprint["version"] == 1
    with activations.connection() as conn, conn:
        conn.execute("DROP TRIGGER head_fault")
    retry = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert retry.status == "ACTIVATED_PAUSED", retry.model_dump()
    assert workflow.get_run(run_id).acg_blueprint["version"] == 2


def test_commit_ack_loss_reconciles_with_the_original_key(ready_boundary, monkeypatch):
    runtime, workflow, activations, run_id, materialization_id, _, activation_id = activated(ready_boundary)
    replay = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.activation_id == activation_id
    assert workflow.get_run(run_id).acg_blueprint["version"] == 2


def test_commit_ack_fault_still_leaves_a_reconcilable_fact(ready_boundary, monkeypatch):
    runtime, workflow, activations, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    original = activations._connect

    class Connection:
        def __init__(self):
            self.inner = original()

        def __getattr__(self, key):
            return getattr(self.inner, key)

        def commit(self):
            self.inner.commit()
            raise sqlite3.OperationalError("lost ack")

    monkeypatch.setattr(activations, "_connect", Connection)
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED" and result.code == Code.STORAGE_UNAVAILABLE
    monkeypatch.setattr(activations, "_connect", original)
    reopened = SQLiteGraphActivationStore(workflow.db_path)
    runtime.enable_graph_activation(reopened)
    reconciled = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert reconciled.status == "IDEMPOTENT_REPLAY"
    assert reopened.head(run_id).active_graph_version == 2
    assert workflow.get_run(run_id).acg_blueprint["version"] == 2


def test_old_thread_snapshot_cannot_regress_the_graph_version(ready_boundary):
    runtime, workflow, activations, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    old_snapshot = workflow.get_run(run_id)
    started = threading.Event()
    release = threading.Event()
    outcome = {}

    def old_worker():
        started.set()
        release.wait(10)
        try:
            old_snapshot.runtime_revision += 1
            SQLiteWorkflowStore(workflow.db_path).save_run(old_snapshot)
            outcome["saved"] = True
        except ValueError as exc:
            outcome["error"] = str(exc)

    thread = threading.Thread(target=old_worker)
    thread.start()
    assert started.wait(10)
    receipt = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert receipt.status == "ACTIVATED_PAUSED"
    release.set()
    thread.join(10)
    assert "activation head" in outcome.get("error", ""), outcome
    assert workflow.get_run(run_id).acg_blueprint["version"] == 2


def test_cross_connection_regression_is_blocked(ready_boundary):
    runtime, workflow, activations, run_id, materialization_id, _, _ = activated(ready_boundary)
    current = workflow.get_run(run_id)
    regressed = current.model_copy(deep=True)
    regressed.acg_blueprint["version"] = 1
    regressed.execution_state["graphVersion"] = 1
    with pytest.raises(ValueError, match="activation head"):
        SQLiteWorkflowStore(workflow.db_path).save_run(regressed)
    forged = current.model_copy(deep=True)
    forged.acg_blueprint["version"] = 99
    with pytest.raises(ValueError, match="activation head"):
        workflow.save_run(forged)
    assert workflow.get_run(run_id).acg_blueprint["version"] == 2


def test_scheduler_entries_refuse_the_paused_graph(ready_boundary, monkeypatch):
    runtime, workflow, activations, run_id, materialization_id, agent, _ = activated(ready_boundary)
    stale = workflow.get_run(run_id).model_copy(deep=True)
    stale.acg_blueprint["version"] = 1
    stale.execution_state.pop("graphActivation")
    with pytest.raises(ValueError, match="no execution permit"):
        asyncio.run(runtime.execute_prepared_run(run_id))
    with pytest.raises(ValueError, match="graph version changed|no execution permit"):
        asyncio.run(runtime._execute_acg(stale))
    with pytest.raises(ValueError, match="no execution permit|graphVersion|checkpoint"):
        asyncio.run(runtime.resume_from_checkpoint(run_id=run_id, checkpoint_id="acgckpt_missing"))
    from contracts.workflow import ReviewDecision
    with pytest.raises(Exception):
        asyncio.run(runtime.apply_review(ReviewDecision(runId=run_id, stepId="A",
            decision="approved", operationId="op")))
    assert agent.calls == []
    before = workflow.get_run(run_id).model_dump(mode="json")
    assert workflow.get_run(run_id).model_dump(mode="json") == before


def test_preparation_does_not_pause_the_original_graph(ready_boundary, monkeypatch):
    from contracts.runtime_planning import RuntimePlanningDecision
    runtime, workflow, activations, run_id, materialization_id, agent = chain(ready_boundary, prepare_key="act")

    class ContinueOriginal:
        def decide_runtime(self, **kwargs):
            obs = kwargs["observation"]
            return RuntimePlanningDecision(observationId=obs.fingerprint(),
                action="continue" if obs.remaining_step_ids else "complete", reason="original")

    monkeypatch.setattr(runtime.runtime_planning_coordinator, "planner_for_run", lambda _: ContinueOriginal())
    mission = runtime.mission_manager.get_mission(workflow.get_run(run_id).mission_id)
    runtime.mission_manager.mark_running(mission)
    result = asyncio.run(runtime.execute_prepared_run(run_id))
    assert result.status == WorkflowStatus.COMPLETED and result.acg_blueprint["version"] == 1
    assert agent.calls == ["A"]
    assert activations.head(run_id) is None
    assert activations.activation_for(materialization_id).status == "ACTIVATION_PREPARED"
    finished = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert finished.status == "REJECTED" and finished.code == Code.AUTHORITY_DENIED


def test_recovery_cannot_resume_from_the_paused_projection(ready_boundary):
    """A real acknowledged v1 checkpoint survives activation but cannot resume."""
    runtime, workflow, journal, run_id, receipt_id, agent = materialized_chain_with_checkpoint(ready_boundary)
    runtime.enable_graph_activation(SQLiteGraphActivationStore(workflow.db_path))
    assert runtime.prepare_graph_activation(receipt_id, idempotency_key="act").status == "ACTIVATION_PREPARED"
    checkpoint_id = workflow.get_run(run_id).execution_state["checkpointId"]
    assert runtime.commit_graph_activation(receipt_id, idempotency_key="act").status == "ACTIVATED_PAUSED"
    assert workflow.get_run(run_id).execution_state["checkpointId"] is None
    with pytest.raises(ValueError, match="no execution permit"):
        asyncio.run(runtime.resume_from_checkpoint(run_id=run_id, checkpoint_id=checkpoint_id))
    assert agent.calls == []
    assert runtime.checkpoint_store.load(run_id=run_id, checkpoint_id=checkpoint_id) is not None


def materialized_chain_with_checkpoint(ready_boundary):
    """Accepted source with an acknowledged v1 checkpoint head, then graph+materialization."""
    from runtime.state_persistence import acg_execution_state_from_run
    runtime, workflow, ledger, run_id, source, agent = accepted_source(ready_boundary)
    run = workflow.get_run(run_id)
    state = acg_execution_state_from_run(run)
    state.graph_id = run.acg_blueprint["graphId"]
    checkpoint_id = runtime.acg_state_persistence.save_checkpoint(run, state)
    run.execution_state["checkpointId"] = checkpoint_id
    workflow.save_run(run)
    graph = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert graph.status == "ACCEPTED", graph.model_dump()
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    journal = SQLiteGraphActivationStore(workflow.db_path)
    runtime.enable_graph_materialization(SQLiteGraphMaterializationStore(workflow.db_path))
    receipt = runtime.materialize_graph_revision(graph.commit_id, idempotency_key="mat")
    assert receipt.status == "MATERIALIZED_INACTIVE", receipt.model_dump()
    return runtime, workflow, journal, run_id, receipt.materialization_id, agent


def test_missing_authority_never_activates(ready_boundary):
    runtime, workflow, journal, run_id, commit, _ = materialized(ready_boundary)
    receipt = runtime.materialize_graph_revision(commit, idempotency_key="mat")
    assert receipt.status == "MATERIALIZED_INACTIVE", receipt.model_dump()
    runtime.graph_activation_authority = None
    materialization_id = receipt.materialization_id
    result = runtime.prepare_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED" and result.code == Code.AUTHORITY_DENIED
    assert runtime.commit_graph_activation(materialization_id, idempotency_key="act").code == Code.AUTHORITY_DENIED
    # The activation journal schema was never prepared for this database.
    with pytest.raises(sqlite3.OperationalError):
        SQLiteGraphActivationStore(workflow.db_path)
    assert workflow.get_run(run_id).acg_blueprint["version"] == 1


def test_schema_is_explicit_and_actual_definitions_are_checked(ready_boundary):
    from test_planning_commit_runtime import dump_databases
    runtime, workflow, activations, run_id, materialization_id, _ = chain(ready_boundary)
    with activations.connection() as conn, conn:
        conn.execute("DROP INDEX graph_activation_key_unique")
        conn.execute("CREATE INDEX graph_activation_key_unique ON graph_activations(idempotency_key)")
    malformed = dump_databases(workflow, include_ledger=True)
    with pytest.raises(RuntimeError):
        SQLiteGraphActivationStore(workflow.db_path)
    with pytest.raises(RuntimeError):
        SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    assert dump_databases(workflow, include_ledger=True) == malformed
    assert runtime.prepare_graph_activation(materialization_id, idempotency_key="act").status == "REJECTED"
    with activations.connection() as conn, conn:
        conn.execute("DROP INDEX graph_activation_key_unique")
        conn.execute("CREATE UNIQUE INDEX graph_activation_key_unique ON graph_activations(idempotency_key)")
    before = dump_databases(workflow, include_ledger=True)
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    assert dump_databases(workflow, include_ledger=True) == before


def test_constructor_never_creates_a_database(tmp_path):
    absent = tmp_path / "absent.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        SQLiteGraphActivationStore(absent)
    assert not absent.exists()


def test_corrupted_activation_content_is_rejected(ready_boundary):
    runtime, workflow, activations, run_id, materialization_id, _ = chain(ready_boundary, prepare_key="act")
    with activations.connection() as conn, conn:
        conn.execute("UPDATE graph_activations SET checksum=?", ("0" * 64,))
    with pytest.raises(ValueError):
        activations.activation_for(materialization_id)
    result = runtime.commit_graph_activation(materialization_id, idempotency_key="act")
    assert result.status == "REJECTED"
    assert workflow.get_run(run_id).acg_blueprint["version"] == 1


def test_planning_and_review_cannot_bypass_the_paused_state(ready_boundary):
    """Both planning lanes fail closed on a paused Run: activation advanced the
    Run projection, so the stale observation is refused, and no new executable
    graph can exist until S03-02B hand-off re-establishes trusted boundaries."""
    from test_planning_commit_runtime import patch
    runtime, workflow, activations, run_id, materialization_id, agent, activation_id = activated(ready_boundary)
    run = workflow.get_run(run_id)
    with runtime.run_lock_manager.lock_for(run_id):
        accepted = runtime.planning_commit_authority.accept_patch_locked(
            run_id, patch(workflow.get_run(run_id)), proposal_id="paused-plan", idempotency_key="paused-plan")
    assert accepted.status == "REJECTED", accepted.model_dump()
    assert accepted.code == Code.STALE_OBSERVATION, accepted.model_dump()
    latest = runtime.planning_commit_authority.store.latest(run.mission_id)
    assert latest.proposal_type == "graph_revision"
    graph = runtime.accept_graph_revision(run_id, latest.commit_id, idempotency_key="paused-graph")
    assert graph.status == "REJECTED", graph.model_dump()
    # The activation fact itself is untouched by the refused planning lane.
    assert activations.head(run_id).activation_id == activation_id
    assert workflow.get_run(run_id).acg_blueprint["version"] == 2
    assert workflow.get_run(run_id).execution_state["graphActivation"]["executionPermit"] is None
    with pytest.raises(ValueError, match="no execution permit"):
        asyncio.run(runtime.execute_prepared_run(run_id))
    assert agent.calls == []
