"""Independent S02-02 adversarial acceptance and crash-window evidence."""
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest

from contracts.planning_commit import PlanningCommitRejectionCode as Code
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.runtime_planning import RuntimePlanningRound, RuntimePlanningState
from contracts.workflow import WorkflowStatus, StepStatus
from contracts.planning import TaskPlan, TaskPlanPatch, PlannedTask
from components.planner.planning_commit import PlanningCommitService
from support.stores.planning_commit_store import SQLitePlanningCommitStore
from test_planning_commit_runtime import attach, patch, durable, dump_databases
from test_horizon import ready_boundary, runtime_boundary
from test_planning_commit import TrustedProvider


def test_same_mission_distinct_keys_race_on_one_acceptance_head(tmp_path):
    path, store, provider, req = durable(tmp_path)
    requests = [req.model_copy(update={"idempotency_key": f"race:{i}"}) for i in range(2)]
    services = [PlanningCommitService(current_state_provider=provider,
        store=SQLitePlanningCommitStore(path)) for _ in requests]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: services[i].accept(requests[i]), range(2)))
    assert sorted(r.status for r in results) == ["ACCEPTED", "REJECTED"]
    assert next(r for r in results if r.status == "REJECTED").code == Code.STALE_COMMITMENT
    assert len(store.pending_events()) == 1 and store.latest(req.sources.mission_id).commitment_revision == 1


@pytest.mark.parametrize("stage", ["record", "outbox", "commit", "commit_ack"])
def test_sqlite_fault_stages_are_atomic_and_retryable(tmp_path, monkeypatch, stage):
    path, store, provider, req = durable(tmp_path)
    original = store._connect
    if stage in {"record", "outbox"}:
        table = "planning_commit_records" if stage == "record" else "planning_commit_outbox"
        with store.connection() as conn, conn:
            conn.execute(f"CREATE TRIGGER audit_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'fault'); END")
    else:
        class FaultConnection:
            def __init__(self): self.inner = original()
            def __getattr__(self, name): return getattr(self.inner, name)
            def commit(self):
                if stage == "commit_ack": self.inner.commit()
                raise sqlite3.OperationalError("commit acknowledgement unavailable")
        monkeypatch.setattr(store, "_connect", FaultConnection)
    failed = PlanningCommitService(current_state_provider=provider, store=store).accept(req)
    assert failed.status == "REJECTED"
    monkeypatch.setattr(store, "_connect", original)
    record = store.get_by_idempotency_key(req.idempotency_key)
    assert (record is not None) == (stage == "commit_ack")
    assert len(store.pending_events()) == (1 if record else 0)
    if stage in {"record", "outbox"}:
        with store.connection() as conn, conn: conn.execute("DROP TRIGGER audit_fault")
    retry = PlanningCommitService(current_state_provider=provider, store=store).accept(req)
    assert retry.status == ("IDEMPOTENT_REPLAY" if record else "ACCEPTED")
    assert retry.commitment_revision == 1 and len(store.pending_events()) == 1


def test_different_missions_share_write_lock_and_timeout_is_safe(tmp_path):
    path, store, provider, req = durable(tmp_path)
    from contracts.identity import new_mission_id
    other_sources = req.sources.model_copy(update={"mission_id": new_mission_id()})
    other_plan = provider.get_proposal_payload(req).model_copy(update={"mission_id": other_sources.mission_id})
    from support.stores.planning_commit_store import content_fingerprint
    other = req.model_copy(update={"sources": other_sources, "idempotency_key": "other-mission",
                                  "proposal_fingerprint": content_fingerprint(other_plan)})
    second_provider = TrustedProvider(other)
    second_provider.get_proposal_payload = lambda _: other_plan
    entered, release = Event(), Event()
    original_validation = provider.validate_proposal
    def slow_validation(request):
        entered.set()
        assert release.wait(20)
        return original_validation(request)
    provider.validate_proposal = slow_validation
    first = PlanningCommitService(current_state_provider=provider, store=store)
    second = PlanningCommitService(current_state_provider=second_provider, store=SQLitePlanningCommitStore(path))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(first.accept, req)
        assert entered.wait(5)
        try:
            started = monotonic()
            rejected = second.accept(other)
            assert monotonic() - started >= 4
            assert rejected.code == Code.STORAGE_UNAVAILABLE
        finally:
            release.set()
        assert pending.result().status == "ACCEPTED"
    assert second.accept(other).status == "ACCEPTED"
    assert len(store.pending_events()) == 2


@pytest.mark.parametrize("operator_input", [False, True])
def test_acceptance_before_decided_save_recovers_without_another_model_call(ready_boundary, monkeypatch, operator_input):
    runtime, store, agent, run_id, state = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    runtime.mission_manager.mark_running(runtime.mission_manager.get_mission(run.mission_id))
    class Planner:
        def decide_runtime(self, **kwargs):
            return RuntimePlanningDecision(observationId=kwargs["observation"].fingerprint(),
                action="revise", reason="candidate", taskPlanPatch=patch(run))
    coordinator = runtime.runtime_planning_coordinator
    monkeypatch.setattr(coordinator, "planner_for_run", lambda _: Planner())
    original = coordinator._save
    def crash_before_decided(run, loop, stage):
        if stage == "decided":
            raise RuntimeError("decided save crash")
        return original(run, loop, stage)
    monkeypatch.setattr(coordinator, "_save", crash_before_decided)
    with pytest.raises(RuntimeError, match="decided save crash"):
        asyncio.run(coordinator.boundary(run, state, "resume"))
    assert len(ledger.pending_events()) == 1
    held = store.get_run(run_id)
    assert held.execution_state["planningLoop"]["current"]["decision"] is None
    if operator_input:
        from contracts.runtime_planning import RuntimeUserInput
        from contracts.workflow import utc_now
        store.save_planning_input(run_id, "after-acceptance", RuntimeUserInput(sourceRunId=run_id,
            operationId="after-acceptance", content="keep this latest instruction",
            submittedAt=utc_now()).model_dump(by_alias=True, mode="json"))
    monkeypatch.setattr(coordinator, "_save", original)
    monkeypatch.setattr(coordinator, "planner_for_run", lambda _: pytest.fail("accepted round called model again"))
    assert asyncio.run(coordinator.boundary(held, state, "restart")) == "stop"
    assert len(ledger.pending_events()) == 1 and not agent.calls
    assert store.get_run(run_id).status == WorkflowStatus.WAITING_REVIEW
    if operator_input:
        assert store.list_planning_inputs(run_id)[0]["content"] == "keep this latest instruction"


def test_persisted_acceptance_mode_cannot_be_removed(ready_boundary):
    runtime, store, _, run_id, _ = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    with runtime.run_lock_manager.lock_for(run_id):
        assert runtime.planning_commit_authority.accept_patch_locked(
            run_id, patch(run), proposal_id="p", idempotency_key="p").status == "ACCEPTED"
    run.execution_state.pop("planningCommitRequired")
    with pytest.raises(ValueError, match="planning.*mode|Planning Commit"):
        store.save_run(run)
    assert store.get_run(run_id).execution_state["planningCommitRequired"] is True
    assert len(ledger.pending_events()) == 1


def test_compiler_generated_dependency_cannot_target_completed_sink(tmp_path):
    from test_react_loop import runtime_at
    from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal
    from components.mission_manager.semantic_service import MissionSemanticService
    runtime, store, _ = runtime_at(tmp_path)
    owner = SemanticPrincipal(actorId="owner", tenantId="tenant")
    store._init_semantic_schema()
    store.enable_existing_mission_semantics()
    runtime.mission_semantic_service = MissionSemanticService(store=store, authorize=lambda p, m, a: p == owner)
    runtime.semantic_principal_provider = lambda: owner
    mission = runtime.create_mission("compiled sink audit", workflow_id="seq")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="sink-basis", expectedMissionRevision=0,
        objective="Analyze and verify input", constraints=[], sourceRefs=["input:brief"]))
    _, run = runtime.prepare_run(mission.mission_id)
    run.status = WorkflowStatus.RUNNING
    for step in run.steps:
        step.status = StepStatus.COMPLETED
        step.attempt = 1
    from runtime.state_persistence import acg_execution_state_from_run
    state = acg_execution_state_from_run(run)
    observation = runtime.runtime_planning_coordinator.observe(run, state, "exhausted")
    run.execution_state["planningLoop"] = RuntimePlanningState(current=RuntimePlanningRound(
        observationId=observation.fingerprint(), observation=observation)).model_dump(by_alias=True, mode="json")
    store.save_run(run)
    ledger = attach(runtime, store)
    run = store.get_run(run.run_id)
    plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
    candidate = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=plan.plan_version,
        planVersion=plan.plan_version + 1, addNodes=(PlannedTask(key="new:analysis", title="new", objective="new",
            capabilityRequirements=("task_understanding",), sourceRefs=("input:brief",)),))
    from components.planner.service import apply_task_plan_patch
    revised = apply_task_plan_patch(plan, candidate, runtime.capability_catalog)
    assert any(r.source_key == "new:analysis" and r.target_key in {n.key for n in plan.nodes} for r in revised.relations)
    with runtime.run_lock_manager.lock_for(run.run_id):
        result = runtime.planning_commit_authority.accept_patch_locked(
            run.run_id, candidate, proposal_id="sink", idempotency_key="sink")
    assert result.status == "REJECTED" and result.code == Code.INVALID_PROPOSAL
    assert not ledger.pending_events()


def test_receipt_only_crash_prefix_cannot_be_replaced(ready_boundary):
    runtime, store, _, run_id, _ = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    step = run.steps[0]
    assert step.status == StepStatus.PENDING and step.attempt == 0
    commit_id = f"commit:{run_id}:{step.step_id}:{step.attempt}"
    values = runtime.execution_value_store
    values.prepare_node_commit(run_id=run_id, commit_id=commit_id)
    values.complete_node_commit(run_id=run_id, commit_id=commit_id, payload={"stage": "committed"})
    plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
    replacement = plan.nodes[0].model_copy(update={"objective": "changed after side effect"})
    candidate = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=plan.plan_version,
        planVersion=plan.plan_version + 1, replaceKeys=(replacement.key,), addNodes=(replacement,))
    with runtime.run_lock_manager.lock_for(run_id):
        result = runtime.planning_commit_authority.accept_patch_locked(
            run_id, candidate, proposal_id="receipt", idempotency_key="receipt")
    assert result.status == "REJECTED" and result.code == Code.INVALID_PROPOSAL
    assert not ledger.pending_events()


@pytest.mark.parametrize("mutation,code", [("input", Code.STALE_STRATEGY),
    ("cancel", Code.AUTHORITY_DENIED), ("revoke", Code.AUTHORITY_DENIED),
    ("identity", Code.STALE_STRATEGY), ("scope", Code.STALE_STRATEGY),
    ("catalog", Code.STALE_STRATEGY), ("mission", Code.STALE_MISSION)])
def test_initial_worker_source_changes_are_rejected(ready_boundary, monkeypatch, mutation, code):
    runtime, store, _, source_id, _ = ready_boundary
    ledger = attach(runtime, store)
    source = store.get_run(source_id)
    _, run = runtime.prepare_run(source.mission_id)
    # The scoped engine is constructed for each Run: capture this trusted engine
    # so the hook modifies sources during the actual unlocked planning phase.
    engine = runtime._planning_engine_for_run(run)
    monkeypatch.setattr(runtime, "_planning_engine_for_run", lambda _: engine)
    original = engine.semantic_planner.plan_template
    def mutate_after_capture(**kwargs):
        result = original(**kwargs)
        if mutation == "revoke":
            runtime.mission_semantic_service.authorize = lambda *args: False
        elif mutation == "cancel":
            runtime._cancellation_event(run.run_id).set()
        elif mutation == "identity":
            old = runtime.identity_lifecycle.repositories.task_plans.latest(run.mission_id)
            changed = old.model_copy(update={"plan_version": old.plan_version + 1})
            runtime.identity_lifecycle.repositories.persist_task_plan(changed)
        elif mutation == "catalog":
            descriptor = runtime.capability_catalog.get("task_understanding").model_copy(
                update={"capability_id": "audit_new_capability", "aliases": []})
            runtime.capability_catalog.register(descriptor)
        elif mutation == "mission":
            from contracts.mission_semantic import MissionSemanticRequest
            runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
                missionId=run.mission_id, operationId="worker-edit", expectedMissionRevision=1,
                objective="Changed while planning", constraints=[], sourceRefs=["input:brief"]))
        else:
            with runtime.run_lock_manager.lock_for(run.run_id):
                current = store.get_run(run.run_id)
                if mutation == "input": current.input["operator"] = "new trusted input"
                else: current.execution_scope = current.execution_scope.model_copy(update={"capability_ids": ()})
                current.runtime_revision += 1
                store.save_run(current)
        return result
    monkeypatch.setattr(engine.semantic_planner, "plan_template", mutate_after_capture)
    result = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert result.status == "REJECTED" and result.code == code
    assert ledger.get_by_idempotency_key("initial-planning:" + run.run_id) is None
    assert not ledger.pending_events()


def test_node_review_barrier_does_not_accept_new_planning_facts(ready_boundary):
    runtime, store, _, run_id, state = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    run.steps[0].status = StepStatus.WAITING_REVIEW
    run.status = WorkflowStatus.WAITING_REVIEW
    run.current_step_id = run.steps[0].step_id
    state.review_payload = {"subjectType": "step", "subjectId": run.current_step_id}
    run.execution_state["reviewPayload"] = state.review_payload
    run.execution_state["checkpointId"] = runtime.acg_state_persistence.save_checkpoint(run, state)
    old = RuntimePlanningState.model_validate(run.execution_state["planningLoop"])
    observed = old.current.observation.model_copy(update={"steps": (
        old.current.observation.steps[0].model_copy(update={"status": "waiting_review"}),)})
    run.execution_state["planningLoop"] = old.model_copy(update={"current": old.current.model_copy(
        update={"observation": observed, "observation_id": observed.fingerprint()})}).model_dump(by_alias=True, mode="json")
    store.save_run(run)
    with runtime.run_lock_manager.lock_for(run_id):
        result = runtime.planning_commit_authority.accept_patch_locked(
            run_id, patch(run), proposal_id="review", idempotency_key="review")
    assert result.status == "REJECTED" and result.code == Code.CONTROL_BARRIER_BLOCKED
    assert not ledger.pending_events()


@pytest.mark.parametrize("damage", ["graph_body", "binding", "scope_missing"])
def test_incoherent_persisted_sources_are_not_new_acceptance_authority(ready_boundary, damage):
    runtime, store, _, run_id, _ = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    if damage == "graph_body":
        run.acg_blueprint["metadata"]["audit-source-change"] = True
    elif damage == "scope_missing":
        run.execution_scope = None
    else:
        run.execution_state["taskBindings"][0]["planNodeKey"] = "unknown:semantic"
        loop = RuntimePlanningState.model_validate(run.execution_state["planningLoop"])
        observed = loop.current.observation.model_copy(update={"steps": (
            loop.current.observation.steps[0].model_copy(update={"task_key": "unknown:semantic"}),)})
        run.execution_state["planningLoop"] = loop.model_copy(update={"current": loop.current.model_copy(
            update={"observation": observed, "observation_id": observed.fingerprint()})}).model_dump(by_alias=True, mode="json")
    store.save_run(run)
    with runtime.run_lock_manager.lock_for(run_id):
        result = runtime.planning_commit_authority.accept_patch_locked(
            run_id, patch(run), proposal_id="incoherent", idempotency_key="incoherent")
    assert result.status == "REJECTED"
    assert result.code in {Code.INVALID_PROPOSAL, Code.AUTHORITY_DENIED}
    assert not ledger.pending_events()


@pytest.mark.parametrize("stage", ["checkpoint_ack", "applied_run_save"])
def test_barrier_write_failures_preserve_one_acceptance(ready_boundary, monkeypatch, stage):
    runtime, store, agent, run_id, state = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    runtime.mission_manager.mark_running(runtime.mission_manager.get_mission(run.mission_id))
    class Planner:
        def decide_runtime(self, **kwargs):
            return RuntimePlanningDecision(observationId=kwargs["observation"].fingerprint(), action="revise",
                reason="candidate", taskPlanPatch=patch(run))
    coordinator = runtime.runtime_planning_coordinator
    monkeypatch.setattr(coordinator, "planner_for_run", lambda _: Planner())
    if stage == "checkpoint_ack":
        target, method = runtime.acg_state_persistence, "save_checkpoint"
        original = target.save_checkpoint
        def failing(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("barrier write failed")
    else:
        target, method = store, "save_run"
        original = store.save_run
        def failing(run):
            if run.status == WorkflowStatus.WAITING_REVIEW: raise RuntimeError("barrier write failed")
            return original(run)
    monkeypatch.setattr(target, method, failing)
    with pytest.raises(RuntimeError, match="barrier write failed"):
        asyncio.run(coordinator.boundary(run, state, "resume"))
    assert len(ledger.pending_events()) == 1
    monkeypatch.setattr(target, method, original)
    monkeypatch.setattr(coordinator, "planner_for_run", lambda _: pytest.fail("barrier recovery called model"))
    from runtime.state_persistence import acg_execution_state_from_run
    held = store.get_run(run_id)
    assert asyncio.run(coordinator.boundary(held, acg_execution_state_from_run(held), "restart")) == "stop"
    assert store.get_run(run_id).status == WorkflowStatus.WAITING_REVIEW
    assert len(ledger.pending_events()) == 1 and not agent.calls
