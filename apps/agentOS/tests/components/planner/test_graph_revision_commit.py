"""S02-03 actual Runtime/SQLite commitment and deterministic safe-cut evidence."""
import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from contracts.graph_revision import GraphRevisionProposal
from contracts.planning import TaskPlanPatch, PlannedTask, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.workflow import StepStatus, WorkflowStatus
from support.stores.planning_commit_store import SQLitePlanningCommitStore, content_fingerprint
from test_planning_commit_runtime import attach, patch, dump_databases
from test_horizon import ready_boundary, runtime_boundary


def accepted_source(ready_boundary):
    runtime, store, agent, run_id, state = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(
            run_id, patch(run), proposal_id="semantic", idempotency_key="semantic")
    assert source.status == "ACCEPTED", source.model_dump()
    return runtime, store, ledger, run_id, source.commit_id, agent


def test_graph_acceptance_is_read_only_deterministic_and_restartable(ready_boundary, monkeypatch):
    runtime, store, ledger, run_id, source, agent = accepted_source(ready_boundary)
    before = dump_databases(store)
    monkeypatch.setattr(runtime.semantic_revision_service, "prepare", lambda **kwargs: pytest.fail("replacement Run"))
    monkeypatch.setattr(runtime.runtime_binding_service, "prepare", lambda **kwargs: pytest.fail("resource binding"))
    receipt = runtime.planning_commit_authority.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert receipt.status == "ACCEPTED", receipt.model_dump()
    assert dump_databases(store) == before and not agent.calls
    record = ledger.get(receipt.commit_id)
    proposal = GraphRevisionProposal.model_validate_json(record.proposal_payload.model_dump_json(by_alias=True))
    assert proposal.safe_cut.result == "PROVEN" and proposal.source_commit_id == source
    assert proposal.graph_patch.graph_version == 2 and store.get_run(run_id).acg_blueprint["version"] == 1
    assert record.parent_commit_id == source and record.commitment_revision == 2
    assert record.materialization_status == "COMMITTED_NOT_MATERIALIZED"
    restored = SQLitePlanningCommitStore(store.db_path)
    runtime.enable_planning_commit(restored)
    from runtime import graph_revision
    monkeypatch.setattr(graph_revision.SemanticGraphPatchService, "apply", lambda *a, **kw: pytest.fail("replay lowered again"))
    replay = runtime.planning_commit_authority.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.commit_id == receipt.commit_id
    assert len(restored.pending_events()) == 2 and dump_databases(store) == before
    conflicting = runtime.planning_commit_authority.accept_graph_revision(run_id, source, idempotency_key="different")
    assert conflicting.status == "REJECTED"


@pytest.mark.parametrize("mutation,code", [("mission", Code.STALE_MISSION), ("plan", Code.STALE_STRATEGY),
    ("graph", Code.STALE_STRATEGY), ("input", Code.STALE_STRATEGY), ("scope", Code.STALE_STRATEGY),
    ("receipt", Code.STALE_STRATEGY), ("control", Code.STALE_STRATEGY), ("review", Code.STALE_STRATEGY),
    ("cancel", Code.AUTHORITY_DENIED), ("revoke", Code.AUTHORITY_DENIED), ("legacy", Code.INVALID_PROPOSAL)])
def test_stale_or_unproved_graph_sources_fail_closed(ready_boundary, mutation, code):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    run = store.get_run(run_id)
    if mutation == "revoke": runtime.mission_semantic_service.authorize = lambda *args: False
    elif mutation == "cancel": runtime._cancellation_event(run_id).set()
    elif mutation == "receipt": runtime.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=f"commit:{run_id}:A:0")
    elif mutation == "legacy":
        with ledger.connection() as conn, conn:
            raw = json.loads(conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source,)).fetchone()[0])
            raw.pop("sourceProvenance")
            conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?", (json.dumps(raw), source))
    elif mutation == "mission":
        from contracts.mission_semantic import MissionSemanticRequest
        runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
            missionId=run.mission_id, operationId="change", expectedMissionRevision=1, objective="changed", constraints=[]))
    else:
        if mutation == "plan": run.execution_state["taskPlan"]["planVersion"] += 1
        if mutation == "graph": run.acg_blueprint["version"] += 1
        if mutation == "input": run.input["operator"] = "changed"
        if mutation == "scope": run.execution_scope = run.execution_scope.model_copy(update={"capability_ids": ()})
        if mutation == "control": run.execution_state["controlFrames"] = [{"controlId": "branch", "controlType": "loop"}]
        if mutation == "review": run.steps[0].status = StepStatus.WAITING_REVIEW
        store.save_run(run)
    result = runtime.planning_commit_authority.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert result.code == code, result.model_dump()
    assert len(ledger.pending_events()) == 1


def test_source_run_identity_and_head_are_fenced(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    run = store.get_run(run_id)
    _, other = runtime.prepare_run(run.mission_id)
    wrong = runtime.planning_commit_authority.accept_graph_revision(other.run_id, source, idempotency_key="foreign")
    assert wrong.status == "REJECTED"
    with runtime.run_lock_manager.lock_for(run_id):
        next_source = runtime.planning_commit_authority.accept_patch_locked(
            run_id, patch(run), proposal_id="second", idempotency_key="second")
    assert next_source.status == "ACCEPTED"
    result = runtime.planning_commit_authority.accept_graph_revision(run_id, source, idempotency_key="stale")
    assert result.code == Code.STALE_COMMITMENT and ledger.graph_revision_for(source) is None


@pytest.mark.parametrize("stage", ["record", "outbox", "commit_ack"])
def test_graph_atomic_fault_and_reconstruction(ready_boundary, monkeypatch, stage):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    original = ledger._connect
    if stage == "commit_ack":
        class Connection:
            def __init__(self): self.inner = original()
            def __getattr__(self, name): return getattr(self.inner, name)
            def commit(self):
                self.inner.commit()
                raise sqlite3.OperationalError("lost acknowledgement")
        monkeypatch.setattr(ledger, "_connect", Connection)
    else:
        table = "planning_commit_records" if stage == "record" else "planning_commit_outbox"
        with ledger.connection() as conn, conn:
            conn.execute(f"CREATE TRIGGER graph_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
    failed = runtime.planning_commit_authority.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert failed.status == "REJECTED"
    monkeypatch.setattr(ledger, "_connect", original)
    if stage != "commit_ack":
        with ledger.connection() as conn, conn: conn.execute("DROP TRIGGER graph_fault")
    retried = runtime.planning_commit_authority.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert retried.status == ("IDEMPOTENT_REPLAY" if stage == "commit_ack" else "ACCEPTED"), retried.model_dump()
    assert len(ledger.pending_events()) == 2 and retried.commitment_revision == 2


def test_runtime_wait_transition_preserves_source_origin(ready_boundary, monkeypatch):
    runtime, store, agent, run_id, state = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    runtime.mission_manager.mark_running(runtime.mission_manager.get_mission(run.mission_id))
    class Planner:
        def decide_runtime(self, **kwargs):
            return RuntimePlanningDecision(observationId=kwargs["observation"].fingerprint(), action="revise",
                reason="semantic candidate", taskPlanPatch=patch(run))
    monkeypatch.setattr(runtime.runtime_planning_coordinator, "planner_for_run", lambda _: Planner())
    assert asyncio.run(runtime.runtime_planning_coordinator.boundary(run, state, "resume")) == "stop"
    source = ledger.latest(run.mission_id)
    with ledger.connection() as conn:
        source_bytes = conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source.commit_id,)).fetchone()[0]
    result = runtime.planning_commit_authority.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert result.status == "ACCEPTED", result.model_dump()
    assert store.get_run(run_id).status == WorkflowStatus.WAITING_REVIEW and not agent.calls
    before = dump_databases(store)
    asyncio.run(runtime._recover_pending_planning_transitions(limit=10))
    assert dump_databases(store) == before and not agent.calls
    with ledger.connection() as conn:
        assert conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source.commit_id,)).fetchone()[0] == source_bytes
    class ContinueOriginal:
        def decide_runtime(self, **kwargs):
            observed = kwargs["observation"]
            return RuntimePlanningDecision(observationId=observed.fingerprint(),
                action="continue" if observed.remaining_step_ids else "complete", reason="original graph only")
    monkeypatch.setattr(runtime.runtime_planning_coordinator, "planner_for_run", lambda _: ContinueOriginal())
    from contracts.workflow import ReviewDecision
    held = store.get_run(run_id)
    completed = asyncio.run(runtime.apply_review(ReviewDecision(runId=run_id, stepId=held.current_step_id,
        decision="approved", operationId="original-approval")))
    assert completed.status == WorkflowStatus.COMPLETED and completed.acg_blueprint["version"] == 1
    assert agent.calls == ["A"] and len(completed.steps) == 1


@pytest.mark.parametrize("same_key", [True, False])
def test_cross_connection_graph_acceptance_is_unique(ready_boundary, same_key, monkeypatch):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    from runtime.planning_commit import RuntimePlanningCommitAuthority
    from components.planner.planning_commit import PlanningCommitService
    captured = []
    original = PlanningCommitService.accept
    def capture(service, request):
        captured.append((request.model_dump(mode="json"), service.provider.payload.model_dump(mode="json")))
        return original(service, request)
    monkeypatch.setattr(PlanningCommitService, "accept", capture)
    authorities = [RuntimePlanningCommitAuthority(runtime=runtime, store=SQLitePlanningCommitStore(store.db_path)) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: authorities[i].accept_graph_revision(run_id, source,
            idempotency_key="shared" if same_key else f"graph:{i}"), range(2)))
    assert sum(r.status == "ACCEPTED" for r in results) == 1
    if same_key:
        if len(captured) == 2:
            assert captured[0][1] == captured[1][1]
        assert {r.status for r in results} == {"ACCEPTED", "IDEMPOTENT_REPLAY"}, [r.model_dump() for r in results]
    else:
        assert sum(r.status == "REJECTED" for r in results) == 1
    assert len(ledger.pending_events()) == 2


@pytest.mark.parametrize("change,code", [("cancel", Code.AUTHORITY_DENIED), ("revoke", Code.AUTHORITY_DENIED),
    ("authority", Code.AUTHORITY_DENIED), ("input", Code.STALE_STRATEGY)])
def test_changes_during_unlocked_lowering_cannot_publish(ready_boundary, monkeypatch, change, code):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    from runtime import graph_revision
    original = graph_revision.SemanticGraphPatchService.apply
    def derive_then_change(service, **kwargs):
        assert getattr(ledger._local, "connection", None) is None
        result = original(service, **kwargs)
        if change == "cancel": runtime._cancellation_event(run_id).set()
        elif change == "revoke": runtime.mission_semantic_service.authorize = lambda *args: False
        elif change == "authority": runtime.planning_commit_authority = None
        else:
            with runtime.run_lock_manager.lock_for(run_id):
                run = store.get_run(run_id)
                run.input["latestOperatorInput"] = "preserve"
                run.runtime_revision += 1
                store.save_run(run)
        return result
    monkeypatch.setattr(graph_revision.SemanticGraphPatchService, "apply", derive_then_change)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "REJECTED" and result.code == code, result.model_dump()
    assert len(ledger.pending_events()) == 1
    if change == "input": assert store.get_run(run_id).input["latestOperatorInput"] == "preserve"


def test_multi_node_closed_suffix_has_structural_proof(ready_boundary):
    runtime, store, _, run_id, _ = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    candidate = patch(run).model_copy(update={"add_nodes": (
        PlannedTask(key="new:first", title="first", objective="first", capabilityRequirements=("task_understanding",)),
        PlannedTask(key="new:verify", title="verify", objective="verify", capabilityRequirements=("verification",))),
        "relations": (TaskPlanRelation(sourceKey="step:A", targetKey="new:first", relationType="depends_on"),
                      TaskPlanRelation(sourceKey="new:first", targetKey="new:verify", relationType="depends_on"))})
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, candidate, proposal_id="many", idempotency_key="many")
    assert source.status == "ACCEPTED", source.model_dump()
    before = dump_databases(store)
    receipt = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert receipt.status == "ACCEPTED", receipt.model_dump()
    graph = ledger.get(receipt.commit_id).proposal_payload
    assert len(graph.next_plan.nodes) == 3 and len(graph.graph_patch.added_nodes) == 2
    assert dump_databases(store) == before


def test_completed_prefix_pending_suffix_replacement(ready_boundary):
    runtime, store, _, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    run.steps[0].status = StepStatus.COMPLETED
    run.steps[0].attempt = 1
    from contracts.runtime_planning import RuntimePlanningState
    loop = RuntimePlanningState.model_validate(run.execution_state["planningLoop"])
    observed = loop.current.observation.model_copy(update={"steps": (
        loop.current.observation.steps[0].model_copy(update={"status": "completed"}),)})
    run.execution_state["planningLoop"] = loop.model_copy(update={"current": loop.current.model_copy(
        update={"observation": observed, "observation_id": observed.fingerprint()})}).model_dump(by_alias=True, mode="json")
    store.save_run(run)
    ledger = attach(runtime, store)
    # An independent pending node has no dependency on the completed prefix;
    # this is the smallest provable suffix extension preserving its contracts.
    candidate = patch(run).model_copy(update={"relations": ()})
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, candidate, proposal_id="tail", idempotency_key="tail")
    assert source.status == "ACCEPTED", source.model_dump()
    receipt = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert receipt.status == "ACCEPTED", receipt.model_dump()
    assert ledger.get(receipt.commit_id).proposal_payload.safe_cut.protected_node_ids == ("A",)


def test_missing_authority_is_not_a_materialization_fallback(ready_boundary):
    runtime, store, ledger, run_id, source, agent = accepted_source(ready_boundary)
    receipt = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert receipt.status == "ACCEPTED"
    runtime.planning_commit_authority = None
    assert runtime.accept_graph_revision(run_id, source, idempotency_key="graph").code == Code.AUTHORITY_DENIED
    before = dump_databases(store)
    asyncio.run(runtime.execute_prepared_run(run_id))
    assert dump_databases(store) == before and not agent.calls


def test_existing_indexless_ledger_is_readable_but_not_auto_upgraded(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    with ledger.connection() as conn, conn:
        before = conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source,)).fetchone()[0]
        conn.execute("DROP INDEX planning_graph_source_unique")
    reopened = SQLitePlanningCommitStore(store.db_path)
    assert reopened.get(source).proposal_type == "plan_revision"
    runtime.enable_planning_commit(reopened)
    assert runtime.accept_graph_revision(run_id, source, idempotency_key="graph").code == Code.STORAGE_UNAVAILABLE
    with reopened.connection() as conn:
        assert conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source,)).fetchone()[0] == before
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='planning_graph_source_unique'").fetchone() is None
    SQLitePlanningCommitStore.upgrade_schema(store.db_path)  # temporary test DB only
    runtime.enable_planning_commit(SQLitePlanningCommitStore(store.db_path))
    assert runtime.accept_graph_revision(run_id, source, idempotency_key="graph").status == "ACCEPTED"


def test_no_client_constructed_graph_provider_can_accept_without_derivation_certificate(ready_boundary):
    runtime, store, ledger, run_id, source_id, _ = accepted_source(ready_boundary)
    original = runtime.accept_graph_revision(run_id, source_id, idempotency_key="graph")
    candidate = ledger.get(original.commit_id).proposal_payload
    with ledger.connection() as conn, conn:
        conn.execute("DELETE FROM planning_commit_outbox WHERE commit_id=?", (original.commit_id,))
        conn.execute("DELETE FROM planning_commit_records WHERE commit_id=?", (original.commit_id,))
    from runtime.graph_revision import GraphProvider
    from contracts.planning_commit import PlanningCommitRequest
    from components.planner.planning_commit import PlanningCommitService
    provider = GraphProvider(runtime.planning_commit_authority, run_id, candidate, ledger.get(source_id), runtime.semantic_principal_provider())
    request = PlanningCommitRequest(proposalId="fake", proposalType="graph_revision", sources=provider.get_current_sources(candidate.mission_id),
        proposalFingerprint=content_fingerprint(candidate), requestedScope=tuple(n.key for n in candidate.next_plan.nodes),
        idempotencyKey="client", expectedCommitmentRevision=1)
    result = PlanningCommitService(current_state_provider=provider, store=ledger).accept(request)
    assert result.code == Code.INVALID_PROPOSAL and len(ledger.pending_events()) == 1


@pytest.mark.parametrize("damage", ["version", "control_frame"])
def test_checkpoint_identity_and_control_evidence_are_required(ready_boundary, damage):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    run = store.get_run(run_id)
    from runtime.state_persistence import acg_execution_state_from_run
    state = acg_execution_state_from_run(run)
    if damage == "version": state.graph_version += 1
    else: state.control_frames = [{"controlId": "unproved", "controlType": "loop"}]
    ref = runtime.checkpoint_store.save(run_id=run_id, state=state.model_dump(by_alias=True, mode="json"))
    run.execution_state["checkpointId"] = ref
    store.save_run(run)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.code == (Code.STALE_GRAPH if damage == "version" else Code.CONTROL_BARRIER_BLOCKED)
    assert len(ledger.pending_events()) == 1
