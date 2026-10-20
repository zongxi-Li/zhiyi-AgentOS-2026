"""Initial acceptance with real Runtime capture, SQLite and source drift fences."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from pydantic import ValidationError

from test_horizon import ready_boundary, runtime_boundary
from test_planning_commit_runtime import attach, dump_databases
from components.planner.planning_commit import PlanningCommitService
from contracts.initial_planning import InitialPlanningSourceProvenance
from contracts.planning_commit import PlanningCommitRecord, PlanningCommitRejectionCode as Code
from runtime.planning_commit import RuntimePlanningCommitAuthority
from support.stores.planning_commit_store import SQLitePlanningCommitStore


@pytest.fixture
def initial_run(ready_boundary):
    runtime, store, agent, source_id, _ = ready_boundary
    ledger = attach(runtime, store)
    source = store.get_run(source_id)
    _, run = runtime.prepare_run(source.mission_id, workflow_id=source.workflow_id)
    return runtime, store, agent, run, ledger


def accept(initial_run):
    runtime, store, agent, run, ledger = initial_run
    receipt = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert receipt.status == "ACCEPTED", receipt
    record = ledger.get(receipt.commit_id)
    assert isinstance(record.source_provenance, InitialPlanningSourceProvenance)
    assert runtime.planning_commit_authority.validate_initial_sources(record.commit_id) is None
    return record


def test_initial_profile_capability_drift_is_detected(initial_run, monkeypatch):
    record = accept(initial_run)
    runtime, _, agent, _, _ = initial_run
    original = agent.profile.model_dump(mode="json", by_alias=True)
    monkeypatch.setattr(agent, "profile", agent.profile.model_copy(deep=True, update={"capabilities": []}))
    assert runtime.planning_commit_authority.validate_initial_sources(record.commit_id).code == Code.STALE_STRATEGY
    assert record.source_provenance.agent_profiles[0] == original


def test_initial_workflow_same_version_domain_drift_is_detected(initial_run, monkeypatch):
    record = accept(initial_run)
    runtime, _, _, run, _ = initial_run
    workflow = runtime._workflow_for_run(run)
    changed = workflow.model_copy(deep=True, update={"domain": "other-domain"})
    assert changed.version == workflow.version
    monkeypatch.setattr(runtime, "_workflow_for_run", lambda _: changed)
    assert runtime.planning_commit_authority.validate_initial_sources(record.commit_id).code == Code.STALE_STRATEGY
    assert record.source_provenance.workflow.domain == workflow.domain


@pytest.mark.parametrize("change", ["catalog", "policy", "identity", "scope", "input", "permission", "principal", "mission", "basis", "authority"])
def test_initial_current_source_fences(initial_run, monkeypatch, change):
    record = accept(initial_run)
    runtime, store, _, run, _ = initial_run
    if change == "catalog":
        descriptor = runtime.capability_catalog.available()[0]
        monkeypatch.setattr(descriptor, "description", descriptor.description + " drift")
    elif change == "policy":
        import runtime.initial_planning_sources as sources
        original = sources.compilation_policy
        def drift():
            value = original()
            return value.model_copy(update={"versions": {**value.versions, "lowerer": "changed-policy"}})
        monkeypatch.setattr(sources, "compilation_policy", drift)
    elif change == "identity":
        repo = runtime.identity_lifecycle.repositories.task_plans
        previous = repo.latest(run.mission_id)
        assert previous is not None
        monkeypatch.setattr(repo, "latest", lambda _: None)
    elif change in {"scope", "input"}:
        latest = store.get_run(run.run_id)
        if change == "scope":
            latest.execution_scope = latest.execution_scope.model_copy(update={"agent_ids": ()})
        else:
            latest.input["operatorInput"] = "changed"
        store.save_run(latest)
    elif change == "permission":
        monkeypatch.setattr(runtime.mission_semantic_service, "authorize", lambda *args: False)
    elif change == "principal":
        monkeypatch.setattr(runtime, "semantic_principal_provider", lambda: None)
    elif change == "mission":
        from contracts.mission_semantic import MissionSemanticRequest
        runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
            missionId=run.mission_id, operationId="updated-mission", expectedMissionRevision=1,
            objective="Updated objective", constraints=[], sourceRefs=[]))
    elif change == "basis":
        # Normal Store must refuse to mutate the Run's frozen basis itself.
        latest = store.get_run(run.run_id)
        latest.execution_state["missionIntentBasis"]["objective"] = "forged"
        with pytest.raises(ValueError):
            store.save_run(latest)
        return
    else:
        authority = runtime.planning_commit_authority
        runtime.planning_commit_authority = None
        assert authority.validate_initial_sources(record.commit_id).code == Code.AUTHORITY_DENIED
        return
    result = runtime.planning_commit_authority.validate_initial_sources(record.commit_id)
    assert result is not None and result.status == "REJECTED"


def test_complete_sources_are_embedded_and_acceptance_has_no_other_writes(initial_run):
    runtime, store, agent, run, ledger = initial_run
    before = dump_databases(store)
    record = accept(initial_run)
    origin = record.source_provenance
    assert dump_databases(store) == before
    assert origin.workflow.workflow_id == run.workflow_id
    assert origin.basis.reference() == record.proposal_payload.metadata["missionIntentBasisRef"]
    assert origin.identity_snapshot and origin.identity_fingerprint
    assert origin.catalog and origin.validation_catalog and len(origin.policy.implementations) == 6
    loaded = SQLitePlanningCommitStore(ledger.db_path).get(record.commit_id)
    assert loaded == record
    replay = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.commit_id == record.commit_id
    assert len(ledger.pending_events()) == 1
    held = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert not held.acg_blueprint and not held.steps and held.execution_state["planningDeferred"]
    assert not agent.calls and not runtime.execution_value_store.list_node_commits(run_id=run.run_id)


@pytest.mark.parametrize("fault", ["unknown", "missing", "checksum", "rebound"])
def test_corrupt_or_unbound_origin_is_rejected(initial_run, fault):
    record = accept(initial_run)
    body = record.model_dump(mode="json", by_alias=True)
    origin = body["sourceProvenance"]
    if fault == "unknown":
        origin["version"] = "initial-static-v999"
    elif fault == "missing":
        origin.pop("workflow")
    elif fault == "checksum":
        origin["staticFingerprint"] = "0" * 64
    else:
        changed = record.source_provenance.model_copy(deep=True)
        changed.workflow.domain = "rebound"
        origin = changed.model_dump(mode="json", by_alias=True)
        origin["staticFingerprint"] = changed.content_fingerprint()
        body["sourceProvenance"] = origin
    with pytest.raises(ValidationError):
        PlanningCommitRecord.model_validate(body)


def test_legacy_initial_stays_readable_and_is_never_upgraded(initial_run, monkeypatch):
    # Deliberately retain a historical-format record in the temporary ledger.
    record = accept(initial_run)
    runtime, _, _, run, ledger = initial_run
    provider = runtime.planning_commit_authority._provider(run.run_id, record.proposal_payload, True)
    provider.legacy_initial_sources = True
    sources = provider.get_current_sources(run.mission_id)
    request = runtime.planning_commit_authority.replay_request(record, "initial-planning:" + run.run_id)
    request = request.model_copy(update={"sources": sources})
    body = request.model_dump(mode="json", by_alias=True, exclude={"idempotency_key"})
    from runtime.planning_commit import fingerprint
    historical = record.model_copy(update={"source_provenance": None, "sources": sources,
        "request_fingerprint": fingerprint(body)})
    with ledger.connection() as conn, conn:
        conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?",
                     (historical.model_dump_json(by_alias=True), record.commit_id))
    before = ledger.get(record.commit_id).model_dump_json()
    def forbidden(*args, **kwargs):
        raise AssertionError("historical replay invoked Planner")
    monkeypatch.setattr(runtime, "_planning_engine_for_run", forbidden)
    replay = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.commit_id == record.commit_id
    assert runtime.planning_commit_authority.validate_initial_sources(record.commit_id).code == Code.INVALID_PROPOSAL
    assert ledger.get(record.commit_id).model_dump_json() == before


def test_source_changes_at_final_capture_reject_without_record(initial_run, monkeypatch):
    runtime, _, agent, run, ledger = initial_run
    from runtime.planning_commit import RuntimePlanningCommitProvider
    original = RuntimePlanningCommitProvider.get_source_provenance
    def drift(provider, request):
        value = original(provider, request)
        agent.profile.capabilities = []
        return value
    monkeypatch.setattr(RuntimePlanningCommitProvider, "get_source_provenance", drift)
    result = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert result.status == "REJECTED" and not ledger.pending_events()
    assert not ledger.latest(run.mission_id) and not agent.calls


def test_missing_provenance_from_runtime_provider_cannot_be_accepted(initial_run, monkeypatch):
    runtime, _, _, run, ledger = initial_run
    from runtime.planning_commit import RuntimePlanningCommitProvider
    monkeypatch.setattr(RuntimePlanningCommitProvider, "get_source_provenance", lambda *_: None)
    result = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert result.code == Code.INVALID_PROPOSAL and not ledger.pending_events()


def test_workflow_credentials_reject_without_persisting_them(initial_run, monkeypatch):
    runtime, _, _, run, ledger = initial_run
    workflow = runtime._workflow_for_run(run).model_copy(deep=True)
    workflow.steps[0].input["api_key"] = "never-persist-this-secret"
    monkeypatch.setattr(runtime, "_workflow_for_run", lambda _: workflow)
    assert runtime.planning_commit_authority.accept_initial(run.run_id).status == "REJECTED"
    assert not ledger.latest(run.mission_id) and not ledger.pending_events()


def test_dynamic_resource_health_is_not_a_compilation_fact(initial_run, monkeypatch):
    record = accept(initial_run)
    runtime, _, _, _, _ = initial_run
    def forbidden(*args, **kwargs):
        raise AssertionError("source capture queried runtime resource readiness")
    monkeypatch.setattr(runtime.resource_binder, "assess", forbidden)
    assert runtime.planning_commit_authority.validate_initial_sources(record.commit_id) is None
    text = record.source_provenance.model_dump_json()
    assert "leaseId" not in text and "heartbeatAt" not in text


def test_unavailable_identity_authority_is_not_trusted_absence(initial_run):
    runtime, _, _, run, ledger = initial_run
    runtime.identity_lifecycle = None
    result = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert result.status == "REJECTED" and not ledger.pending_events()


def test_first_mission_with_no_prior_identity_plan_is_explicit_absence(initial_run):
    runtime, _, _, _, ledger = initial_run
    from contracts.mission_semantic import MissionSemanticRequest
    mission = runtime.create_mission("First plan", workflow_id="htn")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="first-plan", expectedMissionRevision=0,
        objective="Analyze first input", constraints=[], sourceRefs=[]))
    _, run = runtime.prepare_run(mission.mission_id, workflow_id="htn")
    assert runtime.identity_lifecycle.repositories.task_plans.latest(mission.mission_id) is None
    receipt = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert receipt.status == "ACCEPTED", receipt
    assert ledger.get(receipt.commit_id).source_provenance.identity_snapshot is None


def test_non_template_initial_keeps_actual_l1_profile(initial_run):
    runtime, _, _, _, ledger = initial_run
    from contracts.workflow import WorkflowDefinition, WorkflowDefinitionType
    from contracts.mission_semantic import MissionSemanticRequest
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="initial-native", name="native",
        domain="general", runtimeEngine="acg", definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP))
    mission = runtime.create_mission("Analyze input", workflow_id="initial-native")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="native-source", expectedMissionRevision=0,
        objective="Analyze supplied input", constraints=[], sourceRefs=[]))
    _, run = runtime.prepare_run(mission.mission_id, workflow_id="initial-native", input_override={"deterministicIntent": True})
    receipt = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert receipt.status == "ACCEPTED", receipt
    origin = ledger.get(receipt.commit_id).source_provenance
    assert origin.semantic_profile is not None
    assert origin.semantic_profile.primary_goal
    assert runtime.planning_commit_authority.validate_initial_sources(receipt.commit_id) is None


@pytest.mark.parametrize("change", ["profile", "workflow", "policy"])
def test_new_inputs_changing_during_unlocked_planning_reject(initial_run, monkeypatch, change):
    runtime, _, agent, run, ledger = initial_run
    engine = runtime._planning_engine_for_run(run)
    original = engine.semantic_planner.plan_template
    monkeypatch.setattr(runtime, "_planning_engine_for_run", lambda _: engine)
    def mutate(**kwargs):
        result = original(**kwargs)
        if change == "profile":
            agent.profile.capabilities = []
        elif change == "workflow":
            workflow = runtime._workflow_for_run(run).model_copy(deep=True, update={"domain": "changed"})
            monkeypatch.setattr(runtime, "_workflow_for_run", lambda _: workflow)
        else:
            import runtime.initial_planning_sources as sources
            policy = sources.compilation_policy().model_copy(deep=True)
            policy.versions["lowerer"] = "changed"
            monkeypatch.setattr(sources, "compilation_policy", lambda: policy)
        return result
    monkeypatch.setattr(engine.semantic_planner, "plan_template", mutate)
    result = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert result.status == "REJECTED" and not ledger.pending_events()


@pytest.mark.parametrize("same_key", [False, True])
def test_real_sources_cross_connection_cas(initial_run, same_key):
    record = accept(initial_run)
    runtime, _, _, run, ledger = initial_run
    services, requests = [], []
    for index in range(2):
        store = SQLitePlanningCommitStore(ledger.db_path)
        authority = RuntimePlanningCommitAuthority(runtime=runtime, store=store)
        provider = authority._provider(run.run_id, record.proposal_payload, True)
        provider.initial_provenance = record.source_provenance
        requests.append(authority._request(provider, record.proposal_payload, "same-candidate",
            "race" if same_key else f"race:{index}", expected=1))
        services.append(PlanningCommitService(current_state_provider=provider, store=store))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: services[i].accept(requests[i]), range(2)))
    assert sorted(r.status for r in results) == (["ACCEPTED", "IDEMPOTENT_REPLAY"] if same_key else ["ACCEPTED", "REJECTED"])
    if not same_key:
        assert next(r for r in results if r.status == "REJECTED").code == Code.STALE_COMMITMENT
    assert len(ledger.pending_events()) == 2


@pytest.mark.parametrize("stage", ["record", "outbox", "commit", "ack"])
def test_real_initial_sources_atomic_faults(initial_run, monkeypatch, stage):
    runtime, _, _, run, ledger = initial_run
    original = ledger._connect
    if stage in {"record", "outbox"}:
        table = "planning_commit_records" if stage == "record" else "planning_commit_outbox"
        with ledger.connection() as conn, conn:
            conn.execute(f"CREATE TRIGGER initial_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'fault'); END")
    else:
        class Fault:
            def __init__(self): self.inner = original()
            def __getattr__(self, key): return getattr(self.inner, key)
            def commit(self):
                if stage == "ack": self.inner.commit()
                raise sqlite3.OperationalError("lost commit acknowledgement")
        monkeypatch.setattr(ledger, "_connect", Fault)
    failed = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert failed.status == "REJECTED"
    monkeypatch.setattr(ledger, "_connect", original)
    assert len(ledger.pending_events()) == (1 if stage == "ack" else 0)
    if stage in {"record", "outbox"}:
        with ledger.connection() as conn, conn: conn.execute("DROP TRIGGER initial_fault")
    retry = runtime.planning_commit_authority.accept_initial(run.run_id)
    assert retry.status == ("IDEMPOTENT_REPLAY" if stage == "ack" else "ACCEPTED")
    assert len(ledger.pending_events()) == 1
