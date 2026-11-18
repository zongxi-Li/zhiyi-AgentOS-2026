"""Actual SQLite faults, retries and competing reviewers at the publication boundary."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from components.evolution.service import EvolutionService
from components.evolution.store import InMemoryEvolutionStore, SQLiteEvolutionStore
from contracts.evolution import PolicyMutation, Trajectory, TrajectoryStep


def trajectory(index=1):
    return Trajectory(trajectoryId=f"evidence-{index}",
        steps=[TrajectoryStep(stepId="analyse", actionType="agent")],
        outcome={"status": "completed"})


def propose(service, index=1):
    return service.propose([trajectory(index)], PolicyMutation(
        mutationType="budget_adjustment", target="memory_token_budget", value=768))


@pytest.fixture(params=["memory", "sqlite"])
def service(request, tmp_path):
    store = (InMemoryEvolutionStore() if request.param == "memory" else
             SQLiteEvolutionStore(tmp_path / "evolution.db"))
    yield EvolutionService(store=store, proposal_threshold=1)
    if hasattr(store, "close"):
        store.close()


def test_same_publication_replays_receipt_and_rejects_another_reviewer(service):
    proposal = propose(service)
    version = service.approve(proposal, approved_by=" reviewer ")
    assert service.approve(proposal, approved_by="reviewer") == version
    receipt = service.store.get_receipt(proposal.proposal_id)
    assert receipt.policy_version == version.version
    assert receipt.approved_by == "reviewer"
    assert service.store.get_proposal(proposal.proposal_id).status.value == "approved"
    with pytest.raises(ValueError, match="reviewer|publication"):
        service.approve(proposal, approved_by="another")
    assert len(service.store.list_versions()) == 2


def test_duplicate_trajectory_cannot_satisfy_evidence_threshold(service):
    service.proposal_threshold = 2
    mutation = PolicyMutation(mutationType="budget_adjustment", target="analysis", value=100)
    assert service.propose([trajectory(), trajectory()], mutation) is None


def test_conflicting_duplicate_evidence_is_rejected(service):
    item = trajectory()
    altered = item.model_copy(update={"outcome": {"status": "failed"}})
    with pytest.raises(ValueError, match="evidence|trajectory"):
        service.propose([item, altered], PolicyMutation(
            mutationType="budget_adjustment", target="analysis", value=100))


@pytest.mark.parametrize("reviewer", ["", "  "])
def test_blank_reviewer_never_activates_policy(service, reviewer):
    proposal = propose(service)
    with pytest.raises(ValueError, match="reviewer"):
        service.approve(proposal, approved_by=reviewer)
    with pytest.raises(ValueError, match="reviewer"):
        service.rollback(0, approved_by=reviewer)
    assert service.store.active().version == 0


def test_proposal_status_write_failure_rolls_back_entire_publication(tmp_path):
    path = tmp_path / "evolution.db"
    store = SQLiteEvolutionStore(path)
    service = EvolutionService(store=store, proposal_threshold=1)
    proposal = propose(service)
    try:
        with sqlite3.connect(path) as connection:
            connection.execute("""CREATE TRIGGER fail_review BEFORE UPDATE ON evolution_proposals
                BEGIN SELECT RAISE(ABORT, 'injected review failure'); END""")
            connection.execute("""CREATE TRIGGER fail_review_replace BEFORE DELETE ON evolution_proposals
                BEGIN SELECT RAISE(ABORT, 'injected review failure'); END""")
            # Reject the existing INSERT OR REPLACE path too.
            connection.execute("""CREATE TRIGGER fail_review_insert BEFORE INSERT ON evolution_proposals
                BEGIN SELECT RAISE(ABORT, 'injected review failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            service.approve(proposal, approved_by="reviewer")
        assert store.active().version == 0
        assert len(store.list_versions()) == 1
        assert store.get_proposal(proposal.proposal_id) == proposal
        with pytest.raises(KeyError):
            store.get_receipt(proposal.proposal_id)
        with sqlite3.connect(path) as connection:
            for name in ("fail_review", "fail_review_replace", "fail_review_insert"):
                connection.execute(f"DROP TRIGGER {name}")
        assert service.approve(proposal, approved_by="reviewer").version == 1
    finally:
        store.close()


def test_lost_reply_can_be_recovered_after_restart_and_rollback(tmp_path):
    path = tmp_path / "evolution.db"
    first = SQLiteEvolutionStore(path)
    service = EvolutionService(store=first, proposal_threshold=1)
    proposal = propose(service)
    service.approve(proposal, approved_by="reviewer")
    first.close()
    store = SQLiteEvolutionStore(path)
    try:
        service = EvolutionService(store=store, proposal_threshold=1)
        receipt = store.get_receipt(proposal.proposal_id)
        service.rollback(0, approved_by="reviewer")
        result = service.approve(proposal, approved_by="reviewer")
        assert result.version == 1
        assert store.get_receipt(proposal.proposal_id) == receipt
        assert store.active().version == 2
    finally:
        store.close()


def test_independent_connections_publish_one_cas_winner(tmp_path):
    path = tmp_path / "race.db"
    stores = [SQLiteEvolutionStore(path), SQLiteEvolutionStore(path)]
    services = [EvolutionService(store=s, proposal_threshold=1) for s in stores]
    proposals = [propose(s, i + 1) for i, s in enumerate(services)]
    def approve(index):
        try:
            return services[index].approve(proposals[index], approved_by="reviewer").version
        except ValueError:
            return "conflict"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, range(2)))
        assert sorted(results, key=str) == [1, "conflict"]
        assert stores[0].active().version == 1
        statuses = [stores[0].get_proposal(p.proposal_id).status.value for p in proposals]
        assert sorted(statuses) == ["approved", "pending_review"]
    finally:
        for store in stores:
            store.close()


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), -1, 0])
def test_invalid_budget_rejected_before_publication(value, service):
    with pytest.raises(ValueError):
        service.propose([trajectory()], PolicyMutation(
            mutationType="budget_adjustment", target="analysis", value=value))
    assert service.store.active().version == 0


def test_mutating_caller_owned_nested_proposal_cannot_change_validated_content(service):
    proposal = propose(service)
    proposal.mutations[0] = PolicyMutation(mutationType="budget_adjustment", target="analysis", value=100)
    with pytest.raises(ValueError, match="content"):
        service.approve(proposal, approved_by="reviewer")
    assert service.store.active().version == 0


def test_identical_concurrent_requests_share_one_durable_receipt(tmp_path):
    path = tmp_path / "same.db"
    stores = [SQLiteEvolutionStore(path), SQLiteEvolutionStore(path)]
    services = [EvolutionService(store=s, proposal_threshold=1) for s in stores]
    proposal = propose(services[0])
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda s: s.approve(proposal, approved_by="reviewer"), services))
        assert results[0] == results[1]
        assert len(stores[0].list_versions()) == 2
        assert stores[0].get_receipt(proposal.proposal_id) == stores[1].get_receipt(proposal.proposal_id)
    finally:
        for store in stores:
            store.close()


def test_receipt_write_failure_rolls_back_version_and_approved_status(tmp_path):
    path = tmp_path / "receipt.db"
    store = SQLiteEvolutionStore(path)
    service = EvolutionService(store=store, proposal_threshold=1)
    proposal = propose(service)
    try:
        with sqlite3.connect(path) as connection:
            connection.execute("""CREATE TRIGGER fail_receipt BEFORE INSERT ON evolution_publication_receipts
                BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            service.approve(proposal, approved_by="reviewer")
        assert store.active().version == 0
        assert store.get_proposal(proposal.proposal_id) == proposal
        assert len(store.list_versions()) == 1
        with pytest.raises(KeyError):
            store.get_receipt(proposal.proposal_id)
    finally:
        store.close()


def test_equivalent_evidence_with_reordered_object_keys_can_be_replayed(service):
    original = trajectory().model_copy(update={"task": {"runId": "r1", "graphId": "g"}})
    reordered = trajectory().model_copy(update={"task": {"graphId": "g", "runId": "r1"}})
    first = service.evaluate(original)
    assert service.evaluate(reordered) == first
