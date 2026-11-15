"""Immutable semantic projection and Run-persistence contracts on both stores."""

from copy import deepcopy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError

from components.mission_manager.semantic_resolver import MissionSemanticResolver
from contracts.mission_semantic import MissionIntentBasis, MissionSemanticOperation, run_intent_basis
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
from runtime.planner_input_adapter import planner_input, material_input
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    store = MemoryWorkflowStore() if request.param == "memory" else SQLiteWorkflowStore(
        tmp_path / "workflow.sqlite3", enable_mission_semantics=True)
    store.save_mission(RuntimeMissionRecord(missionId="m", title="legacy title",
        input={"objective": "raw objective", "userIntent": "legacy", "constraints": ["old constraint"]}))
    return store


def commit(store, *, op="one", revision=0, objective="formal objective"):
    return store.commit_semantics(MissionSemanticOperation(missionId="m", operationId=op,
        expectedMissionRevision=revision, objective=objective, constraints=[
            {"constraintId": "c", "text": "confirmed constraint", "sourceRefs": ["reference"]}],
        sourceRefs=["reference"], actorId="owner", tenantId="tenant"))


def freeze(store):
    return MissionSemanticResolver.freeze(MissionSemanticResolver.resolve(store.get_semantic_snapshot("m")))


def test_resolver_never_promotes_or_writes(store):
    view = MissionSemanticResolver.resolve(store.get_semantic_snapshot("m"))
    assert view.objective is None and view.mission_revision == 0
    with pytest.raises(ValueError, match="compatibility"):
        MissionSemanticResolver.freeze(view, legacy_title="legacy")
    legacy = MissionSemanticResolver.freeze(view, legacy_title="legacy", allow_legacy=True)
    assert legacy.source_type == "LEGACY_TITLE" and legacy.source_revision == 0
    input_basis = MissionSemanticResolver.freeze(view, legacy_input=store.get_mission("m").input,
        legacy_title="legacy", allow_legacy=True)
    assert input_basis.source_type == "LEGACY_INPUT" and input_basis.objective == "raw objective"
    assert input_basis.source_revision == 0 and input_basis.commit_id is None
    assert store.get_semantic_snapshot("m").state is None
    with pytest.raises(KeyError):
        MissionSemanticResolver.resolve(store.get_semantic_snapshot("missing"))
    result = commit(store)
    before = store.get_semantic_snapshot("m")
    basis = freeze(store)
    assert basis.objective == "formal objective" and basis.commit_id == result.commit_id
    assert basis.source_status == "UNVERIFIED"
    assert store.get_semantic_snapshot("m") == before
    assert len(store.list_semantic_commits("m")) == len(store.list_semantic_outbox("m")) == 1


def test_nested_immutability_fingerprint_and_input_projection(store):
    commit(store)
    basis = freeze(store)
    with pytest.raises(ValidationError):
        basis.objective = "changed"
    with pytest.raises(ValidationError):
        basis.constraints[0].text = "changed"
    payload = basis.model_dump(by_alias=True, mode="json")
    payload["objective"] = "forged"
    with pytest.raises(ValidationError, match="fingerprint"):
        MissionIntentBasis.model_validate(payload)
    raw = {"objective": "wrong", "userIntent": "wrong", "taskGoal": "wrong", "intent": "wrong",
           "title": "wrong", "goal": "wrong", "constraints": ["wrong"], "materialText": "document",
           "materialRefs": ["sealed"], "thinkingMode": "disabled"}
    saved = deepcopy(raw)
    projected = planner_input(basis, raw)
    assert projected["objective"] == projected["userIntent"] == projected["taskGoal"] == basis.objective
    assert projected["constraints"][0]["value"] == "confirmed constraint"
    assert projected["materialRefs"] == ["sealed"] and projected["materialText"] == "document"
    projected["materialRefs"].append("another")
    assert raw == saved
    assert not {"objective", "title", "goal", "constraints"} & material_input(raw).keys()


@pytest.mark.parametrize("mutation", ["replace", "remove", "fingerprint", "mission", "plan"])
def test_store_rejects_basis_mutations_atomically(store, mutation):
    commit(store)
    original = RuntimeRunRecord(runId="r", missionId="m", workflowId="w", domain="general", runtimeEngine="acg",
        executionState={"missionIntentBasis": freeze(store).model_dump(by_alias=True, mode="json")})
    store.save_run(original)
    before_events = store.list_outbox()
    changed = original.model_copy(deep=True)
    if mutation == "remove":
        changed.execution_state.pop("missionIntentBasis")
    elif mutation == "replace":
        commit(store, op="two", revision=1, objective="later formal objective")
        changed.execution_state["missionIntentBasis"] = freeze(store).model_dump(by_alias=True, mode="json")
    elif mutation == "fingerprint":
        changed.execution_state["missionIntentBasis"]["fingerprint"] = "f" * 64
    elif mutation == "mission":
        changed.mission_id = "other"
    else:
        changed.execution_state["taskPlan"] = {"metadata": {}}
    with pytest.raises(ValueError):
        store.save_run(changed)
    assert store.get_run("r") == original
    assert store.list_outbox() == before_events


def test_existing_unbound_run_cannot_be_backfilled(store):
    run = RuntimeRunRecord(runId="r", missionId="m", workflowId="w", domain="general", runtimeEngine="acg")
    store.save_run(run)
    commit(store)
    run.execution_state["missionIntentBasis"] = freeze(store).model_dump(by_alias=True, mode="json")
    with pytest.raises(ValueError, match="cannot be added"):
        store.save_run(run)
    assert run_intent_basis(store.get_run("r")) is None


def test_concurrent_run_saves_preserve_frozen_basis(store):
    commit(store)
    basis = freeze(store)
    run = RuntimeRunRecord(runId="r", missionId="m", workflowId="w", domain="general", runtimeEngine="acg",
        executionState={"missionIntentBasis": basis.model_dump(by_alias=True, mode="json")})
    store.save_run(run)
    def save(index):
        snapshot = store.get_run("r")
        snapshot.execution_state["ordinaryRuntimeValue"] = index
        store.save_run(snapshot)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(12)))
    assert run_intent_basis(store.get_run("r")) == basis
    loaded = store.get_run("r")
    loaded.execution_state["missionIntentBasis"]["objective"] = "modified outside store"
    assert run_intent_basis(store.get_run("r")) == basis


def test_attach_existing_schema_does_not_migrate(tmp_path):
    path = tmp_path / "workflow.sqlite3"
    store = SQLiteWorkflowStore(path)
    with pytest.raises(RuntimeError, match="upgraded explicitly"):
        store.enable_existing_mission_semantics()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'mission_semantic_%'").fetchall() == []
    SQLiteWorkflowStore(path, enable_mission_semantics=True)
    with sqlite3.connect(path) as conn:
        before = conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    restarted = SQLiteWorkflowStore(path)
    restarted.enable_existing_mission_semantics()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == before
    assert restarted.get_semantic_snapshot("missing").status == "MISSION_NOT_FOUND"


def test_two_connections_cannot_bind_or_unbind_same_run_concurrently(tmp_path):
    path = tmp_path / "workflow.sqlite3"
    store = SQLiteWorkflowStore(path, enable_mission_semantics=True)
    store.save_mission(RuntimeMissionRecord(missionId="m", title="legacy"))
    commit(store)
    basis = freeze(store)
    bound = RuntimeRunRecord(runId="r", missionId="m", workflowId="w", domain="general", runtimeEngine="acg",
        executionState={"missionIntentBasis": basis.model_dump(by_alias=True, mode="json")})
    unbound = bound.model_copy(deep=True, update={"execution_state": {}})
    connections = [SQLiteWorkflowStore(path), SQLiteWorkflowStore(path)]
    barrier = Barrier(2)
    def save(index):
        barrier.wait()
        try:
            connections[index].save_run([bound, unbound][index])
            return "saved"
        except ValueError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, range(2)))
    assert sorted(outcomes) == ["conflict", "saved"]
    persisted = store.get_run("r")
    assert persisted == (bound if outcomes[0] == "saved" else unbound)
