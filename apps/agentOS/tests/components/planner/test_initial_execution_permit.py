"""Real Initial acceptance -> paused v1 -> unique Permit -> native execution."""
import asyncio
import sqlite3
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
import pytest

from test_initial_graph_materialization import setup_initial, materialize, activate, reopen
from test_initial_planning_sources import initial_run as base_initial_run
from test_horizon import ready_boundary, runtime_boundary
from test_graph_handoff import attach as attach_handoff
from support.stores.execution_permit_store import SQLiteExecutionPermitStore
from contracts.workflow import WorkflowStatus
from components.executor.graph import ACGSuperstepError
from test_execution_permit import ready_handoff

_PREPARED_SEED = None


@pytest.fixture
def initial_run(request, tmp_path):
    # A fresh Mission must start with an empty journal, even when pytest orders
    # this case after tests that populated the reusable prepared seed.
    fresh_mission = getattr(request.node, "callspec", None)
    fresh_mission = fresh_mission is not None and fresh_mission.params.get("fresh") is True
    if _PREPARED_SEED is None or fresh_mission:
        return request.getfixturevalue("base_initial_run")
    from test_permit_recovery import _copy_databases
    from test_horizon import ready_resource
    folder, commit_id, run_id, _ = _PREPARED_SEED
    target = tmp_path / "initial-case"
    target.mkdir()
    _copy_databases(folder, target)
    rt, workflow, agent = open_existing(target, commit_id)
    run = workflow.get_run(run_id)
    ready_resource(rt, run)
    return rt, workflow, agent, run, rt.planning_commit_authority.store


def prepared_initial(initial_run, *, fresh=False):
    global _PREPARED_SEED
    if not fresh and initial_run[3].execution_state.get("graphActivation"):
        rt, workflow, agent, run, ledger = initial_run
        handoff = rt.graph_handoff_authority.store.handoff_for(run.execution_state["graphActivation"]["activationId"])
        commit = ledger.get(run.execution_state["graphActivation"]["sourceCommitId"])
        return rt, workflow, agent, run, commit, handoff.handoff_id
    if fresh:
        from contracts.mission_semantic import MissionSemanticRequest
        rt, workflow, agent, old, ledger = initial_run
        mission = rt.create_mission("First Initial execution", workflow_id=old.workflow_id)
        rt.mission_semantic_service.commit(rt.semantic_principal_provider(), MissionSemanticRequest(
            missionId=mission.mission_id, operationId="first-initial", expectedMissionRevision=0,
            objective="Analyze input", constraints=[], sourceRefs=["input:brief"]))
        _, run = rt.prepare_run(mission.mission_id, workflow_id=old.workflow_id)
        initial_run = rt, workflow, agent, run, ledger
    context = setup_initial(initial_run)
    runtime, workflow, agent, run, commit, _, _ = context
    mat = materialize(context)
    act = activate(context, mat)
    attach_handoff(runtime, workflow)
    SQLiteExecutionPermitStore.upgrade_schema(workflow.db_path)
    runtime.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
    receipt = runtime.prepare_graph_handoff(act.activation_id, idempotency_key="initial-handoff")
    assert receipt.status == "STATE_PREPARED", receipt
    if not fresh:
        from test_permit_recovery import _copy_databases
        folder = workflow.db_path.parent.parent / ("initial-seed-" + workflow.db_path.parent.name)
        folder.mkdir()
        _copy_databases(workflow.db_path.parent, folder)
        _PREPARED_SEED = folder, commit.commit_id, run.run_id, receipt.handoff_id
    return runtime, workflow, agent, run, commit, receipt.handoff_id


@pytest.mark.parametrize("fresh", [True, False])
def test_initial_permit_and_native_first_node(initial_run, fresh):
    runtime, workflow, agent, run, commit, handoff_id = prepared_initial(initial_run, fresh=fresh)
    handoff = runtime.graph_handoff_authority.store.get_handoff(handoff_id)
    assert handoff.source_kind == "initial_plan"
    assert handoff.source_checkpoint_id is None and handoff.source_checkpoint_version is None
    assert handoff.identity_link.source_graph is None and not handoff.candidate.state["completedStepIds"]
    assert runtime.checkpoint_store.latest_version(run_id=run.run_id) == 0
    assert runtime.identity_lifecycle.repositories.runs.get(run.run_id) is None
    with pytest.raises(ValueError):
        runtime._claim_acg_execution(workflow.get_run(run.run_id))
    receipt = runtime.issue_execution_permit(handoff_id, idempotency_key="initial-permit")
    assert receipt.status == "ISSUED", receipt
    permit = runtime.execution_permit_authority.store.get_permit(receipt.permit_id)
    assert permit.graph_version == 1 and permit.source_checkpoint_id is None
    assert permit.promoted_checkpoint_version == 1
    cp = runtime.checkpoint_store.load(run_id=run.run_id, checkpoint_id=permit.promoted_checkpoint_id)
    assert cp["executionGeneration"] == permit.attempt_generation and not cp["completedStepIds"]
    identity = runtime.identity_lifecycle.repositories.runs.get(run.run_id)
    blueprint = runtime.identity_lifecycle.repositories.blueprints.get(identity.blueprint_id)
    assert blueprint.graph["version"] == 1 and identity.graph_version == blueprint.version
    if fresh:
        assert identity.graph_version == 1
    replay = runtime.issue_execution_permit(handoff_id, idempotency_key="initial-permit")
    assert replay.status == "IDEMPOTENT_REPLAY" and replay.permit_id == receipt.permit_id
    assert runtime.issue_execution_permit(handoff_id, idempotency_key="different").status == "REJECTED"
    completed = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert agent.calls == ["A"]
    assert completed.completed_step_ids == ["A"], completed
    receipts = runtime.execution_value_store.list_node_commits(run_id=run.run_id)
    assert len(receipts) == 1 and receipts[0]["stage"] == "committed"
    node = receipts[0]["nodeExecution"]
    assert node["attemptId"] and node["executionInstanceId"].startswith(permit.attempt_generation + ":")
    binding = completed.execution_state["executionBindings"]["A"]
    identity_binding = runtime.identity_lifecycle.repositories.execution_bindings.get_for_attempt(node["attemptId"])
    assert identity_binding.resource_id == binding["resourceId"] and binding["attemptId"] == node["attemptId"]
    latest_id, latest = runtime.checkpoint_store.load_latest(run_id=run.run_id)
    assert latest["graphVersion"] == 1 and latest["executionPermitId"] == permit.permit_id
    assert runtime.checkpoint_store.version(run_id=run.run_id, checkpoint_id=latest_id) > 1
    assert len(runtime.identity_lifecycle.repositories.attempts.list_for_run(run.run_id)) == 1
    asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert agent.calls == ["A"]


@pytest.mark.parametrize("cut", ["checkpoint_before", "checkpoint", "identity_rollback", "identity", "workflow", "ack"])
def test_initial_saga_recovers_same_key_after_real_store_failures(initial_run, monkeypatch, cut):
    rt, workflow, agent, run, _, handoff_id = prepared_initial(initial_run)
    permits = rt.execution_permit_authority.store
    with monkeypatch.context() as patch:
        if cut in {"checkpoint_before", "checkpoint"}:
            original = rt.checkpoint_store.save_promoted
            def save_then_fail(**kwargs):
                if cut == "checkpoint_before": raise sqlite3.OperationalError("checkpoint write failed")
                original(**kwargs)
                raise sqlite3.OperationalError("checkpoint ACK lost")
            patch.setattr(rt.checkpoint_store, "save_promoted", save_then_fail)
        elif cut == "identity_rollback":
            service = rt.identity_lifecycle.lifecycle_service
            original = service.create_run
            def rollback_identity(**kwargs):
                original(**kwargs)
                raise RuntimeError("Identity transaction failed after Run insert")
            patch.setattr(service, "create_run", rollback_identity)
        elif cut == "identity":
            original = rt.identity_lifecycle.on_run_prepared
            def identity_then_fail(*args):
                original(*args)
                raise RuntimeError("Identity ACK lost")
            patch.setattr(rt.identity_lifecycle, "on_run_prepared", identity_then_fail)
        elif cut == "workflow":
            with sqlite3.connect(workflow.db_path) as conn:
                conn.execute("CREATE TRIGGER deny_issue BEFORE UPDATE ON graph_execution_permits WHEN NEW.status='ISSUED' BEGIN SELECT RAISE(ABORT,'issue fault'); END")
        else:
            original = permits._connect
            class LostACK:
                def __init__(self): self.inner = original()
                def __getattr__(self, key): return getattr(self.inner, key)
                def commit(self):
                    issued = self.inner.execute("SELECT 1 FROM graph_execution_permits WHERE status='ISSUED'").fetchone()
                    self.inner.commit()
                    if issued: raise sqlite3.OperationalError("Workflow ACK lost")
            patch.setattr(permits, "_connect", LostACK)
        receipt = rt.issue_execution_permit(handoff_id, idempotency_key="recover-key")
        assert receipt.status == "REJECTED", receipt
    pending = permits.permit_for_handoff(handoff_id)
    assert pending is not None and pending.status == ("ISSUED" if cut == "ack" else "PREPARING")
    if cut != "ack":
        with pytest.raises(ValueError): rt._claim_acg_execution(workflow.get_run(run.run_id))
    if cut == "identity_rollback":
        assert rt.identity_lifecycle.repositories.runs.get(run.run_id) is None
    if cut == "workflow":
        with sqlite3.connect(workflow.db_path) as conn: conn.execute("DROP TRIGGER deny_issue")
    receipt = rt.issue_execution_permit(handoff_id, idempotency_key="recover-key")
    assert receipt.status == ("IDEMPOTENT_REPLAY" if cut == "ack" else "ISSUED"), receipt
    assert receipt.permit_id == pending.permit_id and not agent.calls
    asyncio.run(rt.execute_prepared_run(run.run_id))
    assert agent.calls == ["A"]


@pytest.mark.parametrize("same_key", [True, False])
def test_initial_concurrent_permits_are_unique(initial_run, same_key):
    rt, workflow, agent, run, commit, handoff_id = prepared_initial(initial_run)
    def issue(i):
        worker, _, _ = open_existing(workflow.db_path.parent, commit.commit_id)
        return worker.issue_execution_permit(handoff_id, idempotency_key="same" if same_key else f"different:{i}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(issue, range(2)))
    assert sum(r.status == "ISSUED" for r in receipts) == 1, receipts
    assert all(r.status in {"ISSUED", "IDEMPOTENT_REPLAY", "REJECTED"} for r in receipts)
    stored = SQLiteExecutionPermitStore(workflow.db_path).permit_for_handoff(handoff_id)
    assert stored.status == "ISSUED" and not agent.calls
    for i in range(2):
        replay = rt.issue_execution_permit(handoff_id, idempotency_key="same" if same_key else f"different:{i}")
        assert replay.status == ("IDEMPOTENT_REPLAY" if same_key or stored.idempotency_key == f"different:{i}" else "REJECTED")


def open_existing(folder, commit_id):
    from support.stores.graph_handoff_store import SQLiteGraphHandoffStore, SQLiteStagedGraphCheckpointStore
    rt, workflow, agent = reopen(folder, commit_id)
    workflow.enable_existing_mission_semantics()
    rt.enable_graph_handoff(SQLiteGraphHandoffStore(workflow.db_path), SQLiteStagedGraphCheckpointStore(rt.checkpoint_store.db_path))
    rt.enable_execution_permit(SQLiteExecutionPermitStore(workflow.db_path))
    return rt, workflow, agent


@pytest.mark.parametrize("change", ["permission", "cancel", "profile", "checkpoint", "identity",
                                   "workflow", "catalog", "mission", "scope", "input"])
def test_initial_issued_permit_does_not_bypass_current_sources(initial_run, monkeypatch, change):
    rt, workflow, agent, run, _, handoff_id = prepared_initial(initial_run)
    assert rt.issue_execution_permit(handoff_id, idempotency_key="guard").status == "ISSUED"
    if change == "permission": monkeypatch.setattr(rt.mission_semantic_service, "authorize", lambda *a: False)
    elif change == "cancel": rt.cancel(run.run_id)
    elif change == "profile": agent.profile.capabilities = []
    elif change == "workflow": rt._workflow_for_run(run).domain = "changed-same-version"
    elif change == "catalog": rt.capability_catalog.available()[0].description += " drift"
    elif change == "mission":
        from contracts.mission_semantic import MissionSemanticRequest
        rt.mission_semantic_service.commit(rt.semantic_principal_provider(), MissionSemanticRequest(
            missionId=run.mission_id, operationId="changed-after-permit", expectedMissionRevision=1,
            objective="Changed objective", constraints=[], sourceRefs=[]))
    elif change in {"scope", "input"}:
        current = workflow.get_run(run.run_id)
        if change == "scope": current.execution_scope = current.execution_scope.model_copy(update={"agent_ids": ()})
        else: current.input["new-operator-input"] = "changed"
        try: workflow.save_run(current)
        except ValueError:
            assert not agent.calls
            return
    elif change == "checkpoint":
        rt.checkpoint_store.save_promoted(run_id=run.run_id, checkpoint_id="unacknowledged",
            state={"runId": run.run_id}, expected_source_version=1)
    else:
        repos = rt.identity_lifecycle.repositories
        other = next(b for b in repos.blueprints.list_for_mission(run.mission_id)
                     if b.blueprint_id != repos.runs.get(run.run_id).blueprint_id)
        repos.runs.update_blueprint(run.run_id, other.blueprint_id, other.version)
    try:
        asyncio.run(rt.execute_prepared_run(run.run_id))
    except ValueError:
        pass
    assert agent.calls == []
    assert not rt.execution_value_store.list_node_commits(run_id=run.run_id)


@pytest.mark.parametrize("change", ["permission", "cancel", "binding", "identity"])
def test_initial_last_invocation_guard_after_attempt_creation(initial_run, monkeypatch, change):
    from runtime.live_events import runtime_event_broker
    rt, workflow, agent, run, _, handoff_id = prepared_initial(initial_run)
    assert rt.issue_execution_permit(handoff_id, idempotency_key="last-guard").status == "ISSUED"
    original = runtime_event_broker.publish
    triggered = []
    async def mutate(run_id, event):
        await original(run_id, event)
        if run_id != run.run_id or event.event_type != "node.started": return
        triggered.append(event.node_id)
        if change == "permission":
            rt.mission_semantic_service.authorize = lambda *args: False
        elif change == "cancel": rt._signal_run_cancellation(run_id)
        elif change == "binding":
            latest = workflow.get_run(run_id)
            latest.execution_state["executionBindings"][event.node_id]["resourceId"] = "stale-resource"
            workflow.save_run(latest)
        else:
            repos = rt.identity_lifecycle.repositories
            other = next(b for b in repos.blueprints.list_for_mission(run.mission_id)
                         if b.blueprint_id != repos.runs.get(run_id).blueprint_id)
            repos.runs.update_blueprint(run_id, other.blueprint_id, other.version)
    monkeypatch.setattr(runtime_event_broker, "publish", mutate)
    try: asyncio.run(rt.execute_prepared_run(run.run_id))
    except (ValueError, ACGSuperstepError): pass
    assert triggered == ["A"] and agent.calls == []
    assert all(item.get("stage") != "committed" for item in rt.execution_value_store.list_node_commits(run_id=run.run_id))


def test_initial_unknown_external_failure_is_not_an_automatic_retry(initial_run, monkeypatch):
    rt, workflow, agent, run, _, handoff_id = prepared_initial(initial_run)
    assert rt.issue_execution_permit(handoff_id, idempotency_key="unknown").status == "ISSUED"
    entered = []
    async def unknown(context):
        entered.append(context.step.step_id)
        raise RuntimeError("Agent entered; external side effect cannot be determined")
    monkeypatch.setattr(agent, "run", unknown)
    try: asyncio.run(rt.execute_prepared_run(run.run_id))
    except (ValueError, ACGSuperstepError): pass
    assert entered == ["A"]
    assert all(item.get("stage") != "committed" for item in rt.execution_value_store.list_node_commits(run_id=run.run_id))
    with pytest.raises(ValueError): rt.reconcile_execution_checkpoint(run.run_id)
    try: asyncio.run(rt.execute_prepared_run(run.run_id))
    except (ValueError, ACGSuperstepError): pass
    assert entered == ["A"]


def _initial_process_cut(folder, commit_id, handoff_id, cut):
    rt, _, _ = open_existing(folder, commit_id)
    if cut == "checkpoint":
        original = rt.checkpoint_store.save_promoted
        def crash(**kwargs):
            original(**kwargs)
            os._exit(81)
        rt.checkpoint_store.save_promoted = crash
    else:
        permits = rt.execution_permit_authority.store
        original = permits._connect
        class ExitOnIssue:
            def __init__(self): self.inner = original()
            def __getattr__(self, key): return getattr(self.inner, key)
            def commit(self):
                issued = self.inner.execute("SELECT 1 FROM graph_execution_permits WHERE status='ISSUED'").fetchone()
                self.inner.commit()
                if issued: os._exit(82)
        permits._connect = ExitOnIssue
    rt.issue_execution_permit(handoff_id, idempotency_key="process-permit")
    os._exit(90)


@pytest.mark.parametrize("cut,exit_code", [("checkpoint", 81), ("issued", 82)])
def test_initial_real_process_death_recovers_unique_permit(initial_run, cut, exit_code):
    rt, workflow, _, run, commit, handoff_id = prepared_initial(initial_run)
    child = multiprocessing.get_context("spawn").Process(target=_initial_process_cut,
        args=(workflow.db_path.parent, commit.commit_id, handoff_id, cut))
    child.start(); child.join(30)
    if child.is_alive():
        child.terminate(); child.join()
        pytest.fail("Initial Permit process fault experiment exceeded limit")
    assert child.exitcode == exit_code
    stored = rt.execution_permit_authority.store.permit_for_handoff(handoff_id)
    assert stored.status == ("PREPARING" if cut == "checkpoint" else "ISSUED")
    restarted, workflow, agent = open_existing(workflow.db_path.parent, commit.commit_id)
    receipt = restarted.issue_execution_permit(handoff_id, idempotency_key="process-permit")
    assert receipt.status == ("ISSUED" if cut == "checkpoint" else "IDEMPOTENT_REPLAY"), receipt
    assert receipt.permit_id == stored.permit_id
    from test_horizon import ready_resource
    ready_resource(restarted, workflow.get_run(run.run_id))
    asyncio.run(restarted.execute_prepared_run(run.run_id))
    assert agent.calls == ["A"]
    latest_id, checkpoint = restarted.checkpoint_store.load_latest(run_id=run.run_id)
    assert checkpoint["completedStepIds"] == ["A"] and checkpoint["executionPermitId"] == stored.permit_id
    assert len(restarted.execution_value_store.list_node_commits(run_id=run.run_id)) == 1


def test_historical_revision_wire_fingerprints_are_unchanged(ready_handoff):
    import hashlib
    import json
    from contracts.graph_handoff import GraphHandoffRecord
    from support.stores.planning_commit_store import content_fingerprint
    rt, workflow, _, run_id, _, ledger, staged, permits, handoff_id = ready_handoff
    record = ledger.get_handoff(handoff_id)
    body = record.model_dump(mode="json", by_alias=True)
    assert set(body) == {"version", "handoffId", "idempotencyKey", "runId", "activationId", "graphVersion",
        "sourceCheckpointId", "sourceCheckpointVersion", "sourceCheckpointFingerprint", "prefixFingerprint",
        "sourcesFingerprint", "identityLink", "candidate", "candidateFingerprint", "status"}
    assert "sourceKind" not in body["identityLink"] and "sourceKind" not in body["candidate"]
    expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert content_fingerprint(GraphHandoffRecord.model_validate(body)) == expected
    invalid = dict(body, sourceCheckpointId=None, sourceCheckpointVersion=None)
    with pytest.raises(ValueError): GraphHandoffRecord.model_validate(invalid)
    receipt = rt.issue_execution_permit(handoff_id, idempotency_key="legacy-wire")
    assert receipt.status == "ISSUED", receipt
    permit = permits.get_permit(receipt.permit_id)
    assert permit.source_kind == "graph_revision" and "sourceKind" not in permit.model_dump(mode="json", by_alias=True)
    rt.execution_permit_authority.assert_dispatchable(workflow.get_run(run_id))


@pytest.mark.parametrize("change", ["permission", "profile", "authority", "receipt"])
def test_initial_saga_change_after_checkpoint_cannot_issue(initial_run, monkeypatch, change):
    rt, workflow, agent, run, _, handoff_id = prepared_initial(initial_run)
    permits = rt.execution_permit_authority.store
    original = rt.checkpoint_store.save_promoted
    def mutate(**kwargs):
        value = original(**kwargs)
        if change == "permission": monkeypatch.setattr(rt.mission_semantic_service, "authorize", lambda *a: False)
        elif change == "profile": agent.profile.capabilities = []
        elif change == "receipt": rt.execution_value_store.prepare_node_commit(run_id=run.run_id, commit_id="unknown-in-saga")
        else: rt.execution_permit_authority = None
        return value
    monkeypatch.setattr(rt.checkpoint_store, "save_promoted", mutate)
    receipt = rt.issue_execution_permit(handoff_id, idempotency_key="mid-saga")
    assert receipt.status == "REJECTED", receipt
    assert permits.permit_for_handoff(handoff_id).status == "PREPARING"
    assert workflow.get_run(run.run_id).execution_state["graphActivation"]["executionPermit"] is None
    with pytest.raises(ValueError): rt._claim_acg_execution(workflow.get_run(run.run_id))
    assert not agent.calls


def _initial_execution_checkpoint_cut(folder, commit_id, run_id):
    rt, workflow, agent = open_existing(folder, commit_id)
    from test_horizon import ready_resource
    ready_resource(rt, workflow.get_run(run_id))
    original = agent.run
    async def record(context):
        with (folder / "invocations.txt").open("a", encoding="utf-8") as stream:
            stream.write(context.step.step_id + "\n")
            stream.flush()
        return await original(context)
    agent.run = record
    def checkpoint_written():
        _, checkpoint = rt.checkpoint_store.load_latest(run_id=run_id)
        if checkpoint["completedStepIds"] == ["A"]: os._exit(83)
    rt.acg_state_persistence.after_checkpoint_hook = checkpoint_written
    asyncio.run(rt.execute_prepared_run(run_id))
    os._exit(90)


def test_initial_node_checkpoint_reconciles_after_real_process_death(initial_run):
    rt, workflow, _, run, commit, handoff_id = prepared_initial(initial_run)
    receipt = rt.issue_execution_permit(handoff_id, idempotency_key="execute-cut")
    assert receipt.status == "ISSUED"
    folder = workflow.db_path.parent
    child = multiprocessing.get_context("spawn").Process(target=_initial_execution_checkpoint_cut,
        args=(folder, commit.commit_id, run.run_id))
    child.start(); child.join(30)
    if child.is_alive():
        child.terminate(); child.join()
        pytest.fail("Initial node checkpoint process fault experiment exceeded limit")
    assert child.exitcode == 83
    reopened, workflow, agent = open_existing(folder, commit.commit_id)
    current = workflow.get_run(run.run_id)
    head, _ = reopened.checkpoint_store.load_latest(run_id=run.run_id)
    assert head != current.execution_state["checkpointId"] and current.completed_step_ids == ["A"]
    with pytest.raises(ValueError): reopened._claim_acg_execution(current)
    reconciled = reopened.reconcile_execution_checkpoint(run.run_id)
    assert reconciled.execution_state["checkpointId"] == head
    asyncio.run(reopened.execute_prepared_run(run.run_id))
    assert agent.calls == [] and (folder / "invocations.txt").read_text(encoding="utf-8").splitlines() == ["A"]
    assert len(reopened.execution_value_store.list_node_commits(run_id=run.run_id)) == 1
    assert reopened.execution_permit_authority.store.permit_for_handoff(handoff_id).permit_id == receipt.permit_id
