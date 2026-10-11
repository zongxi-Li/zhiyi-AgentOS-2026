"""Atomic decisions share the semantic Revision and WorkflowStore transaction."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from components.mission_manager.semantic_resolver import MissionSemanticResolver
from contracts.mission_revision import MissionRevisionDecision, MissionRevisionConflict, revision_observation
from contracts.mission_semantic import SemanticPrincipal
from contracts.workflow import RuntimeRunRecord, WorkflowStatus
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from test_mission_semantic_store import store, operation

PRINCIPAL = SemanticPrincipal(actorId='owner', tenantId='tenant')


def setup_run(store, legacy=False):
    store.commit_semantics(operation())
    basis = MissionSemanticResolver.freeze(MissionSemanticResolver.resolve(store.get_semantic_snapshot('mission_test')))
    run = RuntimeRunRecord(runId='source', missionId='mission_test', workflowId='w', domain='general', runtimeEngine='acg',
        executionState={} if legacy else {'missionIntentBasis':basis.model_dump(by_alias=True, mode='json')})
    store.save_run(run)
    store.commit_semantics(operation('edit', 1, 'r2'))
    return run


def decision(**changes):
    return MissionRevisionDecision(operationId='d', sourceRevision=1, targetRevision=2,
        decision='CONTINUE', **changes)


def test_legacy_unbound_decision_and_no_implicit_basis(store):
    run = setup_run(store, True)
    observed = revision_observation(run, store.get_semantic_snapshot(run.mission_id), [])
    assert observed['status'] == 'LEGACY_UNBOUND' and observed['sourceRevision'] == 0
    request = MissionRevisionDecision(operationId='d', sourceRevision=0, targetRevision=2, decision='REQUEST_REPLAN')
    receipt = store.decide_run_revision(PRINCIPAL, run.mission_id, run.run_id, request)
    assert receipt.source_revision == 0
    assert store.get_run(run.run_id).execution_state == {}


def test_replay_after_new_commit_is_historical_not_current_acknowledgement(store):
    run = setup_run(store)
    receipt = store.decide_run_revision(PRINCIPAL, run.mission_id, run.run_id, decision())
    store.commit_semantics(operation('r3', 2, 'r3'))
    assert store.decide_run_revision(PRINCIPAL, run.mission_id, run.run_id, decision()) == receipt
    observed = revision_observation(run, store.get_semantic_snapshot(run.mission_id), [receipt])
    assert observed['decisionStatus'] == 'DECISION_STALE'


def test_concurrent_duplicate_decisions_are_one_receipt(store):
    run = setup_run(store)
    other = SQLiteWorkflowStore(store.db_path) if isinstance(store, SQLiteWorkflowStore) else store
    if isinstance(other, SQLiteWorkflowStore):
        other.enable_existing_mission_semantics()
    gate = Barrier(2)
    def write(adapter):
        gate.wait()
        return adapter.decide_run_revision(PRINCIPAL, run.mission_id, run.run_id, decision())
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(write, [store, other]))
    assert results[0] == results[1]
    assert len(store.list_run_revision_decisions(run.mission_id, run.run_id)) == 1


def test_terminal_race_rejects_new_decision(store):
    run = setup_run(store)
    run.status = WorkflowStatus.CANCELLED
    store.save_run(run)
    with pytest.raises(MissionRevisionConflict, match='RUN_TERMINAL'):
        store.decide_run_revision(PRINCIPAL, run.mission_id, run.run_id, decision())
    assert store.list_run_revision_decisions(run.mission_id, run.run_id) == []


def test_activation_never_adds_decision_schema_to_existing_v1(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / 'v1.sqlite3', enable_mission_semantics=True)
    with store._connect() as conn:
        conn.execute('DROP TABLE mission_revision_decisions')
    reopened = SQLiteWorkflowStore(store.db_path)
    reopened.enable_existing_mission_semantics()
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        reopened.list_run_revision_decisions('m', 'r')
    assert reopened.get_semantic_snapshot('missing').status == 'MISSION_NOT_FOUND'
    upgraded = SQLiteWorkflowStore(store.db_path, enable_mission_semantics=True)
    assert upgraded.list_run_revision_decisions('m', 'r') == []


def test_explicit_purge_removes_only_source_decisions(store):
    run = setup_run(store)
    store.decide_run_revision(PRINCIPAL, run.mission_id, run.run_id, decision())
    run.status = WorkflowStatus.CANCELLED
    store.save_run(run)
    store.delete_run(run.run_id, delete_orphan_mission=False)
    assert store.list_run_revision_decisions(run.mission_id, run.run_id) == []
    assert store.get_semantic_snapshot(run.mission_id).mission_revision == 2
