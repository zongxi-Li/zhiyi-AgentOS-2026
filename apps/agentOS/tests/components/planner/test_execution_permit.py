"""Focused Permit Authority and promotion tests on the real B1 Runtime fixture."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
import sqlite3

import pytest

from components.executor.node_runner import ACGNodeRunner
from contracts import stable_checksum
from contracts.runtime_planning import RuntimePlanningDecision
from support.stores.execution_permit_store import SQLiteExecutionPermitStore
from support.stores.graph_handoff_store import SQLiteGraphHandoffStore, SQLiteStagedGraphCheckpointStore
from support.stores.graph_activation_store import validate_activation_run
from test_graph_handoff import _build_prefix


_PERMIT_SEED = pytest.StashKey()


@pytest.fixture
def ready_handoff(tmp_path, tmp_path_factory, pytestconfig):
    from test_permit_recovery import _copy_databases, _open
    seed = pytestconfig.stash.get(_PERMIT_SEED, None)
    if seed is None:
        folder = tmp_path_factory.mktemp("original-permit-seed")
        with pytest.MonkeyPatch.context() as patch:
            rt, workflow, agent, run_id, activation_id, _, _ = _build_prefix(folder, patch)
            prepared = rt.prepare_graph_handoff(activation_id, idempotency_key="permit-handoff")
            assert prepared.status == "STATE_PREPARED", prepared.model_dump()
            SQLiteExecutionPermitStore.upgrade_schema(workflow.db_path)
            definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
            # Preserve the actual seed Agent invocation history alongside its
            # real committed databases. No execution facts are synthesized.
            seed = (folder, definition, run_id, activation_id, prepared.handoff_id, tuple(agent.calls), rt)
            pytestconfig.stash[_PERMIT_SEED] = seed
    folder, definition, run_id, activation_id, handoff_id, history, _ = seed
    _copy_databases(folder, tmp_path)
    rt, workflow, agent = _open(tmp_path, definition)
    agent.calls.extend(history)
    permits = rt.execution_permit_authority.store
    return (rt, workflow, agent, run_id, activation_id, rt.graph_handoff_authority.store,
            rt.graph_handoff_authority.staged_store, permits, handoff_id)


@pytest.mark.freeze_gate
def test_permit_issues_only_after_checkpoint_and_identity_promotion(ready_handoff):
    rt, workflow, agent, run_id, activation_id, ledger, staged, permits, handoff_id = ready_handoff
    paused = workflow.get_run(run_id)
    original_checkpoint_version = rt.checkpoint_store.latest_version(run_id=run_id)
    result = rt.issue_execution_permit(handoff_id, idempotency_key="permit-key")

    assert result.status == "ISSUED", result.model_dump()
    permit = permits.get_permit(result.permit_id)
    assert permit.status == "ISSUED"
    assert permit.activation_id == activation_id and permit.run_id == run_id and permit.graph_version == 2
    assert permit.promoted_checkpoint_version == original_checkpoint_version + 1
    run = workflow.get_run(run_id)
    assert run.execution_state["graphActivation"]["executionPermit"]["permitId"] == permit.permit_id
    assert run.execution_state["executionGeneration"] == permit.attempt_generation
    assert run.execution_state["checkpointId"] == permit.promoted_checkpoint_id
    promoted = rt.checkpoint_store.load(run_id=run_id, checkpoint_id=permit.promoted_checkpoint_id)
    assert promoted["executionPermitId"] == permit.permit_id
    assert promoted["executionGeneration"] == permit.attempt_generation
    assert promoted["completedStepIds"] == ["A"]
    assert agent.calls == ["A"]
    identity_run = rt.identity_lifecycle.repositories.runs.get(run_id)
    identity_blueprint = rt.identity_lifecycle.repositories.blueprints.get(identity_run.blueprint_id)
    assert identity_run.graph_version == 2
    assert identity_blueprint.graph == run.acg_blueprint
    assert rt.issue_execution_permit(handoff_id, idempotency_key="permit-key").status == "IDEMPOTENT_REPLAY"
    assert rt.issue_execution_permit(handoff_id, idempotency_key="other-key").code == "DUPLICATE_CONFLICT"
    with permits.connection() as conn:
        row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
        assert validate_activation_run(conn, type(run).model_validate_json(row[0])).active_graph_version == 2
    # Issuance does not itself invoke Scheduler or run a candidate node.
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
def test_issued_permit_is_the_only_path_to_native_scheduler_dispatch(ready_handoff):
    rt, workflow, agent, run_id, _, _, _, permits, handoff_id = ready_handoff
    before = workflow.get_run(run_id)
    assert before.execution_state["graphActivation"]["executionPermit"] is None
    with pytest.raises(ValueError, match="permit|paused"):
        rt._claim_acg_execution(before)
    with pytest.raises(ValueError, match="permit|authority"):
        asyncio.run(rt.execute_prepared_run(run_id))
    assert agent.calls == ["A"]
    permit_result = rt.issue_execution_permit(handoff_id, idempotency_key="dispatch-key")
    assert permit_result.status == "ISSUED", permit_result.model_dump()
    class ContinuePlanner:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="continue",
                                           reason="Resume the activated graph")
    # The prior B1 fixture intentionally persisted a wait at graph v1. The
    # activated v2 graph gets a fresh deterministic decision before scheduling.
    rt.runtime_planning_coordinator.planner_for_run = lambda _: ContinuePlanner()

    resumed = asyncio.run(rt.execute_prepared_run(run_id))
    assert resumed.run_id == run_id
    assert all(name in agent.calls for name in ("A", "B", "C", "D")), (
        agent.calls, resumed.status, resumed.current_step_id, resumed.error,
        [(step.step_id, step.status.value, step.error) for step in resumed.steps],
        resumed.execution_state.get("failureEvents"),
        (resumed.execution_state.get("planningLoop") or {}).get("current"),
    )
    permit = permits.get_permit(permit_result.permit_id)
    assert permit.status == "ISSUED"
    # New graph receipts are isolated by the permit's attempt generation.
    commits = rt.execution_value_store.list_node_commits(run_id=run_id)
    new_receipts = [item["commitId"] for item in commits
                    if any(f":{step_id}:" in item["commitId"] for step_id in ("B", "C", "D"))]
    assert len(new_receipts) == 3
    assert all(f"generation:{permit.attempt_generation}" in commit_id for commit_id in new_receipts)


@pytest.mark.freeze_gate
def test_activation_projects_package_requirements_and_rejects_run_tampering(ready_handoff):
    rt, workflow, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    run = workflow.get_run(run_id)
    assert set(run.execution_state["bindingRequirements"]) == {"A", "B", "C", "D"}
    assert run.execution_state["bindingRequirements"]["D"]["requiredCapabilities"]

    permit = rt.issue_execution_permit(handoff_id, idempotency_key="tamper-key")
    assert permit.status == "ISSUED", permit.model_dump()
    tampered = workflow.get_run(run_id)
    tampered.execution_state["bindingRequirements"] = {}
    workflow.save_run(tampered)
    with pytest.raises(ValueError, match="binding requirements"):
        asyncio.run(rt.execute_prepared_run(run_id))
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
def test_concurrent_duplicate_permit_requests_reconcile_one_authority(ready_handoff):
    rt, workflow, agent, run_id, _, _, _, permits, handoff_id = ready_handoff
    folder = workflow.db_path.parent
    definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)

    def issue_from_reopened_runtime(_):
        from test_graph_handoff import _reopen
        reopened, reopened_workflow, _, _, _ = _reopen(folder, definition)
        store = SQLiteExecutionPermitStore(reopened_workflow.db_path)
        reopened.enable_execution_permit(store)
        return reopened.issue_execution_permit(handoff_id, idempotency_key="concurrent-key")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(issue_from_reopened_runtime, range(2)))
    assert sorted(result.status for result in results) == ["IDEMPOTENT_REPLAY", "ISSUED"], [r.model_dump() for r in results]
    assert len({result.permit_id for result in results}) == 1
    record = permits.get_permit(results[0].permit_id)
    assert record.status == "ISSUED" and record.run_id == run_id
    assert workflow.get_run(run_id).execution_state["executionPermitId"] == record.permit_id
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
def test_issued_permit_does_not_survive_principal_revocation(ready_handoff):
    from contracts.mission_semantic import SemanticPrincipal

    rt, _, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    issued = rt.issue_execution_permit(handoff_id, idempotency_key="revoke-key")
    assert issued.status == "ISSUED", issued.model_dump()
    rt.semantic_principal_provider = lambda: SemanticPrincipal(actorId="revoked", tenantId="tenant")
    with pytest.raises(ValueError, match="permission changed"):
        asyncio.run(rt.execute_prepared_run(run_id))
    assert agent.calls == ["A"]


@pytest.mark.freeze_gate
def test_preparing_permit_reconciles_checkpoint_promotion_after_identity_failure(ready_handoff, monkeypatch):
    rt, workflow, _, run_id, _, _, _, permits, handoff_id = ready_handoff
    original = rt.identity_lifecycle.on_execution_permit_blueprint_promoted
    attempts = {"count": 0}

    def fail_once(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("injected Identity outage")
        return original(*args, **kwargs)

    monkeypatch.setattr(rt.identity_lifecycle, "on_execution_permit_blueprint_promoted", fail_once)
    first = rt.issue_execution_permit(handoff_id, idempotency_key="recover-key")
    assert first.status == "REJECTED"
    preparing = permits.permit_by_key("recover-key")
    assert preparing.status == "PREPARING"
    assert permits.permit_for_run(run_id).status == "PREPARING"
    assert workflow.get_run(run_id).execution_state["graphActivation"]["executionPermit"] is None
    assert rt.checkpoint_store.load(run_id=run_id, checkpoint_id=preparing.promoted_checkpoint_id) is not None

    monkeypatch.setattr(rt.identity_lifecycle, "on_execution_permit_blueprint_promoted", original)
    from test_graph_handoff import _reopen
    definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
    reopened, reopened_workflow, _, _, _ = _reopen(workflow.db_path.parent, definition)
    reopened.enable_execution_permit(SQLiteExecutionPermitStore(reopened_workflow.db_path))
    retried = reopened.issue_execution_permit(handoff_id, idempotency_key="recover-key")
    assert retried.status == "ISSUED", retried.model_dump()
    assert permits.get_permit(retried.permit_id).status == "ISSUED"
    assert attempts["count"] == 1


@pytest.mark.freeze_gate
def test_preparing_permit_refuses_changed_run(ready_handoff, monkeypatch):
    rt, workflow, _, run_id, _, _, _, permits, handoff_id = ready_handoff
    original = rt.identity_lifecycle.on_execution_permit_blueprint_promoted

    def fail_after_checkpoint(*args, **kwargs):
        raise RuntimeError("stop after checkpoint promotion")

    monkeypatch.setattr(rt.identity_lifecycle, "on_execution_permit_blueprint_promoted", fail_after_checkpoint)
    first = rt.issue_execution_permit(handoff_id, idempotency_key="stale-key")
    assert first.status == "REJECTED"
    record = permits.permit_by_key("stale-key")
    assert record.status == "PREPARING"
    monkeypatch.setattr(rt.identity_lifecycle, "on_execution_permit_blueprint_promoted", original)

    run = workflow.get_run(run_id)
    run.input["operatorNote"] = "changed after permit preparation"
    workflow.save_run(run)
    stale = rt.issue_execution_permit(handoff_id, idempotency_key="stale-key")
    assert stale.status == "REJECTED"
    assert workflow.get_run(run_id).execution_state["graphActivation"]["executionPermit"] is None
    assert permits.permit_by_key("stale-key").status == "PREPARING"


@pytest.mark.freeze_gate
def test_checkpoint_advance_between_prepare_and_promotion_rejects_permit(ready_handoff, monkeypatch):
    rt, workflow, agent, run_id, _, _, _, permits, handoff_id = ready_handoff
    original = rt.checkpoint_store.save_promoted
    source_version = rt.checkpoint_store.latest_version(run_id=run_id)

    def advance_source_then_promote(**kwargs):
        _, state = rt.checkpoint_store.load_latest(run_id=run_id)
        rt.checkpoint_store.save(run_id=run_id, checkpoint_id="unacknowledged-concurrent",
                                 state=state, expected_version=source_version)
        return original(**kwargs)

    monkeypatch.setattr(rt.checkpoint_store, "save_promoted", advance_source_then_promote)
    result = rt.issue_execution_permit(handoff_id, idempotency_key="checkpoint-race")
    assert result.status == "REJECTED" and result.code == "STALE_GRAPH", result.model_dump()
    assert permits.permit_by_key("checkpoint-race").status == "PREPARING"
    assert workflow.get_run(run_id).execution_state["graphActivation"]["executionPermit"] is None
    identity_run = rt.identity_lifecycle.repositories.runs.get(run_id)
    assert identity_run.graph_version == 1 and agent.calls == ["A"]


@pytest.mark.freeze_gate
def test_attempt_receipt_identity_is_namespaced_by_graph_generation():
    old = ACGNodeRunner._commit_id("run_123", "D", 1)
    new = ACGNodeRunner._commit_id("run_123", "D", 1, execution_generation="agen_new")
    other = ACGNodeRunner._commit_id("run_123", "D", 1, execution_generation="agen_other")
    assert old == "commit:run_123:D:1"
    assert new != old and other != new
    assert "generation:agen_new" in new
