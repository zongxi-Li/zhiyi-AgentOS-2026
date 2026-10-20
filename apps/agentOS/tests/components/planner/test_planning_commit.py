"""S02-01 isolated acceptance, trusted fences and absence of execution effects."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, RLock
import sqlite3

import pytest
from pydantic import ValidationError

from contracts.planning_commit import (
    FrozenPlanningSources, PlanningCommitReceipt, PlanningCommitRequest,
    PlanningCommitRejection, PlanningCommitRejectionCode as Code,
)
from components.planner.planning_commit import InMemoryPlanningCommitStore, PlanningCommitService


def sources(**changes):
    return FrozenPlanningSources.model_validate({
        "missionId": "mission_0123456789ab", "missionRevision": 1,
        "observationId": "observation:1", "observationFingerprint": "a" * 64,
        "planVersion": 1, "graphVersion": 1, "strategyFingerprint": "b" * 64,
        **changes,
    })


def request(**changes):
    return PlanningCommitRequest.model_validate({
        "proposalId": "proposal:1", "proposalType": "horizon",
        "proposalFingerprint": "c" * 64, "sources": sources(),
        "requestedScope": ("A", "B"), "idempotencyKey": "operation:1", **changes,
    })


class TrustedProvider:
    """Test-only server registry. No production provider is implicitly installed."""
    def __init__(self, original=None):
        original = original or request()
        self.current = original.sources
        self.allowed = True
        self.lock = RLock()
        self.proposals = {original.proposal_id: original}
        self.problem = None
        self.on_validate = None
        self.fail_exit = False

    @contextmanager
    def planning_guard(self, mission_id):
        with self.lock:
            yield
            if self.fail_exit:
                raise RuntimeError("private provider failure")

    def get_current_sources(self, mission_id):
        return self.current

    def authorize(self, req):
        return self.allowed

    def validate_proposal(self, req):
        if self.on_validate:
            self.on_validate()
        if self.problem:
            return PlanningCommitRejection(code=self.problem, reason="trusted proposal rejected")
        trusted = self.proposals.get(req.proposal_id)
        if (trusted is None or trusted.proposal_type != req.proposal_type
                or trusted.proposal_fingerprint != req.proposal_fingerprint
                or trusted.sources != req.sources):
            return PlanningCommitRejection(code=Code.INVALID_PROPOSAL, reason="unknown or mismatched candidate")
        if not set(req.requested_scope) <= set(trusted.requested_scope):
            return PlanningCommitRejection(code=Code.INVALID_PROPOSAL, reason="scope exceeds trusted candidate")
        # This test registry's B has unfinished prerequisite A. Production
        # providers must use shared compiled dependencies, not this fixture rule.
        if "B" in req.requested_scope and "A" not in req.requested_scope:
            return PlanningCommitRejection(code=Code.DEPENDENCY_NOT_CLOSED, reason="unfinished prerequisite A")
        return None


@pytest.fixture
def authority():
    provider = TrustedProvider()
    service = PlanningCommitService(current_state_provider=provider)
    return service, provider


def test_accept_queries_and_recorded_sources(authority):
    service, _ = authority
    receipt = service.accept(request())
    assert receipt.status == "ACCEPTED"
    assert receipt.commitment_revision == 1
    record = service.store.get(receipt.commit_id)
    assert record == service.store.get_by_idempotency_key("operation:1")
    assert record.sources == sources()
    assert record.source_revision == 1
    assert record.requested_scope == ("A", "B")
    assert record.parent_commit_id is None
    assert service.store.get("unknown") is None
    assert service.store.get_by_idempotency_key("unknown") is None
    with pytest.raises(ValidationError):
        record.status = "REJECTED"


def test_replay_canonical_scope_and_historical_receipt(authority):
    service, provider = authority
    original = service.accept(request())
    provider.current = sources(graphVersion=2)
    # Historical replay does not claim current eligibility or create a new fact.
    replay = service.accept(request(requestedScope=("B", "A")))
    assert replay.status == "IDEMPOTENT_REPLAY"
    assert replay.commit_id == original.commit_id
    assert replay.commitment_revision == 1
    assert service.store.latest(sources().mission_id).commitment_revision == 1


@pytest.mark.parametrize("changes", [
    {"proposalFingerprint": "d" * 64}, {"requestedScope": ("A",)},
    {"proposalId": "another"}, {"proposalType": "method"},
    {"sources": sources(graphVersion=2)},
])
def test_same_key_different_accepted_content_conflicts(authority, changes):
    service, _ = authority
    first = service.accept(request())
    result = service.accept(request(**changes))
    assert result.code == Code.DUPLICATE_CONFLICT
    assert result.status == "REJECTED" and result.commit_id is None
    assert service.store.latest(sources().mission_id).commit_id == first.commit_id


@pytest.mark.parametrize("changes,code", [
    ({"missionRevision": 2}, Code.STALE_MISSION),
    ({"missionId": "mission_fedcba987654"}, Code.STALE_MISSION),
    ({"planVersion": 2}, Code.STALE_PLAN),
    ({"graphVersion": 2}, Code.STALE_GRAPH),
    ({"observationId": "observation:2"}, Code.STALE_OBSERVATION),
    ({"observationFingerprint": "d" * 64}, Code.STALE_OBSERVATION),
    ({"strategyFingerprint": "d" * 64}, Code.STALE_STRATEGY),
])
def test_stale_sources_do_not_consume_key_or_revision(authority, changes, code):
    service, provider = authority
    provider.current = sources(**changes)
    assert service.validate_sources(sources()).code == code
    assert service.accept(request()).code == code
    assert service.store.get_by_idempotency_key("operation:1") is None
    provider.current = sources()
    assert service.accept(request()).commitment_revision == 1


@pytest.mark.parametrize("field", [
    "run_id", "runId", "executor", "resource", "resource_binding",
    "resourceBinding", "scheduler_state", "permission",
])
def test_forbidden_fields_schema_and_service_reject(authority, field):
    service, _ = authority
    raw = request().model_dump(by_alias=True, mode="json")
    raw[field] = "forged"
    with pytest.raises(ValidationError):
        PlanningCommitRequest.model_validate(raw)
    assert service.accept(raw).code == Code.INVALID_PROPOSAL
    assert service.store.latest(sources().mission_id) is None


@pytest.mark.parametrize("changes", [
    {"requestedScope": ()}, {"requestedScope": ("A", "A")},
    {"proposalFingerprint": "unverified"}, {"idempotencyKey": " "},
    {"sources": {**sources().model_dump(by_alias=True), "graphVersion": True}},
    {"sources": {**sources().model_dump(by_alias=True), "permission": "admin"}},
])
def test_invalid_contracts(authority, changes):
    service, _ = authority
    raw = request().model_dump(by_alias=True)
    raw.update(changes)
    assert service.accept(raw).code == Code.INVALID_PROPOSAL


def test_model_copy_cannot_bypass_service_validation(authority):
    service, _ = authority
    invalid = request().model_copy(update={"requested_scope": ("A", "A")})
    assert service.accept(invalid).code == Code.INVALID_PROPOSAL


@pytest.mark.parametrize("changes,code", [
    ({"proposalId": "invented"}, Code.INVALID_PROPOSAL),
    ({"proposalFingerprint": "d" * 64}, Code.INVALID_PROPOSAL),
    ({"proposalType": "initial_plan"}, Code.INVALID_PROPOSAL),
    ({"requestedScope": ("C",)}, Code.INVALID_PROPOSAL),
    ({"requestedScope": ("B",)}, Code.DEPENDENCY_NOT_CLOSED),
])
def test_trusted_candidate_validation(authority, changes, code):
    service, _ = authority
    assert service.accept(request(**changes)).code == code
    assert service.store.latest(sources().mission_id) is None


def test_control_barrier_and_revoked_authority(authority):
    service, provider = authority
    provider.problem = Code.CONTROL_BARRIER_BLOCKED
    assert service.accept(request()).code == Code.CONTROL_BARRIER_BLOCKED
    provider.problem = None
    first = service.accept(request())
    provider.allowed = False
    assert service.accept(request()).code == Code.AUTHORITY_DENIED
    assert service.store.get(first.commit_id) is not None
    assert service.accept(request(idempotencyKey="other")).code == Code.AUTHORITY_DENIED


@pytest.mark.parametrize("mutation,code", [
    ("sources", Code.STALE_GRAPH), ("authorization", Code.AUTHORITY_DENIED),
    ("exception", Code.AUTHORITY_DENIED), ("guard_exit", Code.AUTHORITY_DENIED),
])
def test_validation_races_and_failure_leave_no_record(authority, mutation, code):
    service, provider = authority
    def mutate():
        if mutation == "sources":
            provider.current = sources(graphVersion=2)
        elif mutation == "authorization":
            provider.allowed = False
        elif mutation == "guard_exit":
            provider.fail_exit = True
        else:
            raise RuntimeError("sensitive contents")
    provider.on_validate = mutate
    result = service.accept(request())
    assert result.code == code
    assert "sensitive" not in result.reason
    assert service.store.get_by_idempotency_key("operation:1") is None
    assert service.store.latest(sources().mission_id) is None


def test_parent_lineage_per_mission_and_failed_acceptance(authority):
    service, provider = authority
    first = service.accept(request())
    second = service.accept(request(idempotencyKey="other", requestedScope=("A",)))
    assert second.commitment_revision == 2
    assert service.store.get(second.commit_id).parent_commit_id == first.commit_id
    provider.fail_exit = True
    assert service.accept(request(idempotencyKey="failed")).status == "REJECTED"
    assert service.store.latest(sources().mission_id).commit_id == second.commit_id
    provider.fail_exit = False
    other = request(proposalId="proposal:other", idempotencyKey="mission:other",
                    sources=sources(missionId="mission_fedcba987654"))
    provider.current = other.sources
    provider.proposals[other.proposal_id] = other
    assert service.accept(other).commitment_revision == 1


def test_concurrent_duplicate_and_distinct_requests_share_store(authority):
    service, provider = authority
    other_service = PlanningCommitService(current_state_provider=provider, store=service.store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: (service if i % 2 else other_service).accept(request()), range(24)))
        assert sum(r.status == "ACCEPTED" for r in results) == 1
        assert len({r.commit_id for r in results}) == 1
        results = list(pool.map(lambda i: other_service.accept(request(idempotencyKey=f"operation:{i+2}")), range(16)))
    assert sorted(r.commitment_revision for r in results) == list(range(2, 18))
    assert len({r.commit_id for r in results}) == 16


@pytest.mark.parametrize("inner_scope,status", [(("A", "B"), "IDEMPOTENT_REPLAY"), (("A",), "REJECTED")])
def test_reentrant_provider_cannot_overwrite_idempotency_binding(authority, inner_scope, status):
    service, provider = authority
    nested = []
    def validate():
        provider.on_validate = None
        nested.append(service.accept(request(requestedScope=inner_scope)))
    provider.on_validate = validate
    result = service.accept(request())
    assert nested[0].status == "ACCEPTED"
    assert result.status == status
    if status == "REJECTED":
        assert result.code == Code.DUPLICATE_CONFLICT
    else:
        assert result.commit_id == nested[0].commit_id
    assert service.store.get_by_idempotency_key("operation:1").commit_id == nested[0].commit_id
    assert service.store.latest(sources().mission_id).commitment_revision == 1


def test_external_state_change_waits_for_acceptance_guard(authority):
    service, provider = authority
    entered, attempted = Event(), Event()
    def change():
        entered.wait(5)
        attempted.set()
        with provider.lock:
            provider.current = sources(graphVersion=2)
    def validate():
        entered.set()
        assert attempted.wait(5)
        assert provider.current.graph_version == 1
    provider.on_validate = validate
    with ThreadPoolExecutor(max_workers=2) as pool:
        change_future = pool.submit(change)
        result = service.accept(request())
        change_future.result(timeout=5)
    assert result.status == "ACCEPTED"
    assert service.store.get(result.commit_id).sources.graph_version == 1
    assert provider.current.graph_version == 2


def test_restart_is_explicitly_process_local(authority):
    service, provider = authority
    first = service.accept(request())
    same_store = PlanningCommitService(current_state_provider=provider, store=service.store)
    assert same_store.accept(request()).status == "IDEMPOTENT_REPLAY"
    fresh = PlanningCommitService(current_state_provider=provider)
    assert fresh.store.get(first.commit_id) is None
    assert fresh.store.get_by_idempotency_key("operation:1") is None
    assert fresh.accept(request()).commitment_revision == 1


def test_receipt_cannot_claim_execution_or_incomplete_acceptance():
    with pytest.raises(ValidationError):
        PlanningCommitReceipt(status="ACCEPTED")
    with pytest.raises(ValidationError):
        PlanningCommitReceipt(status="REJECTED", commitId="invented")
    with pytest.raises(ValidationError):
        PlanningCommitReceipt(status="ACCEPTED", commitId="c", commitmentRevision=1, execution="active")


def test_interrupted_guard_exit_does_not_publish_acceptance(authority):
    service, provider = authority
    @contextmanager
    def interrupted(_mission_id):
        yield
        raise KeyboardInterrupt()
    provider.planning_guard = interrupted
    with pytest.raises(KeyboardInterrupt):
        service.accept(request())
    assert service.store.get_by_idempotency_key("operation:1") is None
    assert service.store.latest(sources().mission_id) is None


# Real Runtime fixture: temporary SQLite, actual persisted TaskPlan/ACG/Run.
from test_horizon import ready_boundary, runtime_boundary


def test_accept_does_not_modify_real_runtime_tables_or_execution(ready_boundary):
    runtime, store, agent, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    before = run.model_dump(mode="json", by_alias=True)
    observation = run.execution_state["planningLoop"]["current"]
    basis = run.execution_state["missionIntentBasis"]
    src = sources(missionId=run.mission_id,
        missionRevision=basis.get("sourceRevision") or 1,
        planVersion=run.execution_state["taskPlanVersion"],
        graphVersion=run.acg_blueprint["version"],
        observationId=observation["observationId"],
        observationFingerprint=observation["observationId"])
    req = request(sources=src, requestedScope=tuple(n["key"] for n in run.execution_state["taskPlan"]["nodes"]))
    provider = TrustedProvider(req)
    service = PlanningCommitService(current_state_provider=provider)
    def databases():
        snapshots = {}
        for path in store.db_path.parent.glob("*.sqlite3"):
            with sqlite3.connect(path) as conn:
                snapshots[path.name] = tuple(conn.iterdump())
        return snapshots
    database_before = databases()
    calls_before = tuple(agent.calls)
    assert service.accept(req).status == "ACCEPTED"
    assert service.accept(req).status == "IDEMPOTENT_REPLAY"
    assert store.get_run(run_id).model_dump(mode="json", by_alias=True) == before
    assert databases() == database_before
    assert tuple(agent.calls) == calls_before
    assert service.store.latest(run.mission_id).requested_scope == req.requested_scope
