"""Independent S02-03 adversarial checks against real Runtime and SQLite."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from pydantic import ValidationError

from components.planner.planning_commit import PlanningCommitService
from contracts.planning import PlannedTask, TaskPlan, TaskPlanPatch
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from runtime.state_persistence import acg_execution_state_from_run
from support.stores.planning_commit_store import SQLitePlanningCommitStore, content_fingerprint
from test_graph_revision_commit import accepted_source
from test_horizon import ready_boundary, runtime_boundary
from test_planning_commit_runtime import attach, dump_databases, patch


@pytest.mark.parametrize("evidence", ["output_refs", "context_refs", "memory_refs", "trace_refs", "provenance_refs",
                                    "consensus_results", "communication_usage"])
def test_checkpoint_evidence_cannot_be_discarded_when_run_lags(ready_boundary, evidence):
    runtime, store, _, run_id, _ = ready_boundary
    ledger = attach(runtime, store)
    run = store.get_run(run_id)
    node = TaskPlan.model_validate(run.execution_state["taskPlan"]).nodes[0]
    candidate = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=1, planVersion=2,
        replaceKeys=(node.key,), addNodes=(node.model_copy(update={"objective": "different work"}),))
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, candidate,
            proposal_id="replace-pending", idempotency_key="replace-pending")
    assert source.status == "ACCEPTED", source.model_dump()
    state = acg_execution_state_from_run(run)
    state.graph_id = run.acg_blueprint["graphId"]
    setattr(state, evidence, {"A": ["event:committed"]} if evidence == "provenance_refs" else
            {"join": {"status": "accepted"}} if evidence == "consensus_results" else
            {"used": 1} if evidence == "communication_usage" else {"A": "stored:reference"})
    ref = runtime.checkpoint_store.save(run_id=run_id, state=state.model_dump(mode="json", by_alias=True))
    run = store.get_run(run_id)
    run.execution_state["checkpointId"] = ref
    store.save_run(run)
    before = dump_databases(store)
    result = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert len(ledger.pending_events()) == 1 and dump_databases(store) == before


def test_unpublished_latest_checkpoint_blocks_acceptance(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    run = store.get_run(run_id)
    state = acg_execution_state_from_run(run)
    state.graph_id = run.acg_blueprint["graphId"]
    state.review_payload = {"subjectType": "node", "subjectId": "A"}
    # Real crash window: checkpoint commits before Workflow Run projection.
    runtime.acg_state_persistence.save_checkpoint(run, state)
    assert store.get_run(run_id).execution_state.get("checkpointId") != state.checkpoint_id
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert len(ledger.pending_events()) == 1


@pytest.mark.parametrize("field,value", [("runId", "foreign-run"), ("graphId", "foreign-graph"), ("graphVersion", 99)])
def test_execution_state_identity_cannot_be_silently_normalized(ready_boundary, field, value):
    runtime, store, _, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    run.execution_state[field] = value
    store.save_run(run)
    ledger = attach(runtime, store)
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, patch(run),
            proposal_id="identity", idempotency_key="identity")
    if source.status == "REJECTED":
        assert not ledger.pending_events()
        return
    result = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert len(ledger.pending_events()) == 1


@pytest.mark.parametrize("channel,value", [("outputSummaries", "stored summary"),
    ("blackboardSnapshots", {"snapshotRef": "stored:snapshot"}), ("debateSessions", {"sessionId": "stored:debate"})])
def test_existing_execution_channels_protect_pending_identity(ready_boundary, channel, value):
    runtime, store, _, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    run.execution_state[channel] = {"A": value}
    store.save_run(run)
    ledger = attach(runtime, store)
    node = TaskPlan.model_validate(run.execution_state["taskPlan"]).nodes[0]
    candidate = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=1, planVersion=2,
        replaceKeys=(node.key,), addNodes=(node.model_copy(update={"objective": "different work"}),))
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, candidate,
            proposal_id="channel", idempotency_key="channel")
    assert source.status == "ACCEPTED", source.model_dump()
    result = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert len(ledger.pending_events()) == 1


@pytest.mark.parametrize("channel", ["outputRefs", "blackboardSnapshots"])
def test_unknown_execution_channel_identity_cannot_be_dropped(ready_boundary, channel):
    runtime, store, _, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    run.execution_state[channel] = {"foreign-node": "stored:output" if channel == "outputRefs" else {"snapshotRef": "stored:snapshot"}}
    store.save_run(run)
    ledger = attach(runtime, store)
    with runtime.run_lock_manager.lock_for(run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run_id, patch(run),
            proposal_id="unknown", idempotency_key="unknown")
    assert source.status == "ACCEPTED", source.model_dump()
    result = runtime.accept_graph_revision(run_id, source.commit_id, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert len(ledger.pending_events()) == 1


def ancestor_boundary(ready_boundary):
    runtime, store, _, _, _ = ready_boundary
    from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus, StepStatus
    from contracts.planning import TaskPlanRelation
    from contracts.mission_semantic import MissionSemanticRequest
    from contracts.runtime_planning import RuntimePlanningState, RuntimePlanningRound
    from components.executor import ACGExecutionState
    tasks = tuple(PlannedTask(key="step:" + key, title=key, objective=key,
        parentKey="step:P1" if key == "A" else None,
        capabilityRequirements=("task_understanding",), sourceRefs=("input:brief",)) for key in ("A", "P1", "P2"))
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="ancestor-audit", name="ancestor-audit", domain="general",
        runtimeEngine="acg", planningNodes=tasks,
        planningRelations=(TaskPlanRelation(sourceKey="step:P2", targetKey="step:A", relationType="parent"),),
        steps=tuple(WorkflowStepDefinition(stepId=key, name=key, agentName="runner") for key in ("A", "P1", "P2"))))
    mission = runtime.create_mission("ancestor-audit", workflow_id="ancestor-audit")
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
        missionId=mission.mission_id, operationId="first", expectedMissionRevision=0,
        objective="Preserve completed child semantics", constraints=[], sourceRefs=["input:brief"]))
    _, run = runtime.prepare_run(mission.mission_id)
    run.status = runtime.state_machine.transition(run.status, WorkflowStatus.RUNNING)
    assert run.get_step("A").status == StepStatus.PENDING
    run.get_step("A").attempt = 1
    runtime.execution_value_store.prepare_node_commit(run_id=run.run_id, commit_id=f"commit:{run.run_id}:A:1")
    state = ACGExecutionState(runId=run.run_id, graphId=run.acg_blueprint["graphId"], graphVersion=1)
    run.execution_state.update(state.model_dump(mode="json", by_alias=True))
    observation = runtime.runtime_planning_coordinator.observe(run, state, "resume")
    run.execution_state["planningLoop"] = RuntimePlanningState(current=RuntimePlanningRound(
        observationId=observation.fingerprint(), observation=observation)).model_dump(mode="json", by_alias=True)
    store.save_run(run)
    ledger = attach(runtime, store)
    plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
    parent = next(node for node in plan.nodes if node.key == "step:P1")
    candidate = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=1, planVersion=2,
        replaceKeys=(parent.key,), addNodes=(parent.model_copy(update={"objective": "different parent obligation"}),))
    return runtime, store, ledger, run, candidate


def test_semantic_acceptance_protects_all_declared_ancestors(ready_boundary):
    runtime, store, ledger, run, candidate = ancestor_boundary(ready_boundary)
    with runtime.run_lock_manager.lock_for(run.run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run.run_id, candidate,
            proposal_id="ancestor", idempotency_key="ancestor")
    assert source.status == "REJECTED", source.model_dump()
    assert not ledger.pending_events()


def test_all_declared_semantic_ancestors_of_started_work_are_protected(ready_boundary, monkeypatch):
    runtime, store, ledger, run, candidate = ancestor_boundary(ready_boundary)
    from runtime import planning_commit, graph_revision
    # Emulate the demonstrated old single-parent source guard to preserve the
    # historical accepted-source scenario. The real graph validator stays active.
    with monkeypatch.context() as legacy:
        legacy.setattr(planning_commit, "with_semantic_ancestors", lambda plan, keys: set(keys) | {"step:P2"}, raising=False)
        with runtime.run_lock_manager.lock_for(run.run_id):
            source = runtime.planning_commit_authority.accept_patch_locked(run.run_id, candidate,
                proposal_id="ancestor", idempotency_key="ancestor")
        assert source.status == "ACCEPTED", source.model_dump()
        result = runtime.accept_graph_revision(run.run_id, source.commit_id, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert result.reason == "semantic execution prefix changed"
    assert len(ledger.pending_events()) == 1


@pytest.mark.parametrize("field", ["graph", "plan", "bindings", "patch", "proof"])
def test_single_field_tampering_is_not_authenticated_by_rehash(ready_boundary, monkeypatch, field):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    original = PlanningCommitService.accept
    def tamper(service, request):
        if request.proposal_type == "graph_revision":
            payload = service.provider.payload.model_copy(deep=True)
            if field == "graph": payload.candidate_graph.metadata["untrusted"] = True
            elif field == "plan": payload.next_plan.metadata["untrusted"] = True
            elif field == "bindings":
                payload = payload.model_copy(update={"next_bindings": payload.next_bindings[1:]})
            elif field == "patch": payload = payload.model_copy(update={"graph_patch": payload.graph_patch.model_copy(update={"reason": "untrusted"})})
            else: payload = payload.model_copy(update={"safe_cut": payload.safe_cut.model_copy(update={"protected_task_keys": ("unknown",)})})
            service.provider.payload = payload
            request = request.model_copy(update={"proposal_fingerprint": content_fingerprint(payload)})
        return original(service, request)
    monkeypatch.setattr(PlanningCommitService, "accept", tamper)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "REJECTED" and len(ledger.pending_events()) == 1


def test_unique_expression_index_enforces_source_and_upgrade_is_idempotent(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "ACCEPTED"
    with ledger.connection() as conn:
        rows = conn.execute("SELECT * FROM planning_commit_records ORDER BY revision").fetchall()
        before = [tuple(row) for row in rows]
        raw = json.loads(rows[-1]["payload"])
    raw.update(commitId="duplicate", commitmentRevision=3)
    with ledger.connection() as conn, conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO planning_commit_records VALUES(?,?,?,?,?)",
                ("duplicate", raw["missionId"], 3, "new-key", json.dumps(raw)))
    SQLitePlanningCommitStore.upgrade_schema(store.db_path)
    SQLitePlanningCommitStore.upgrade_schema(store.db_path)
    with ledger.connection() as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM planning_commit_records ORDER BY revision")] == before


def test_conflicting_history_causes_atomic_schema_preparation_failure(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "ACCEPTED"
    with ledger.connection() as conn, conn:
        raw = json.loads(conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (result.commit_id,)).fetchone()[0])
        conn.execute("DROP INDEX planning_graph_source_unique")
        raw.update(commitId="conflict", commitmentRevision=3)
        conn.execute("INSERT INTO planning_commit_records VALUES(?,?,?,?,?)", ("conflict", raw["missionId"], 3, "bad-history", json.dumps(raw)))
    before = dump_databases(store, include_ledger=True)
    with pytest.raises(sqlite3.IntegrityError): SQLitePlanningCommitStore.upgrade_schema(store.db_path)
    assert dump_databases(store, include_ledger=True) == before
    assert not SQLitePlanningCommitStore(store.db_path).supports_graph_revisions


@pytest.mark.parametrize("change", ["attempt", "receipt", "scope", "plan", "graph", "observation", "checkpoint", "agent", "workflow_version", "workflow_domain"])
def test_trusted_changes_after_derivation_are_fenced(ready_boundary, monkeypatch, change):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    from runtime import graph_revision
    original = graph_revision.SemanticGraphPatchService.apply
    def derive_then_change(service, **kwargs):
        result = original(service, **kwargs)
        run = store.get_run(run_id)
        if change == "receipt":
            runtime.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=f"commit:{run_id}:A:1")
        elif change == "checkpoint":
            state = acg_execution_state_from_run(run)
            state.graph_id = run.acg_blueprint["graphId"]
            state.review_payload = {"subjectType": "node", "subjectId": "A"}
            runtime.acg_state_persistence.save_checkpoint(run, state)
        elif change == "agent":
            next(iter(runtime.agent_registry.all())).profile.binding_priority += 1
        elif change.startswith("workflow_"):
            workflow = runtime._workflow_for_run(run)
            runtime.workflow_registry.register(workflow.model_copy(update={
                "version": "2.0.0"} if change == "workflow_version" else {"domain": "changed"}))
        else:
            if change == "attempt": run.steps[0].attempt += 1
            elif change == "scope": run.execution_scope = run.execution_scope.model_copy(update={"capability_ids": ()})
            elif change == "plan": run.execution_state["taskPlan"]["planVersion"] += 1
            elif change == "graph": run.acg_blueprint["version"] += 1
            else: run.execution_state["planningLoop"]["current"]["observationId"] = "0" * 64
            store.save_run(run)
        return result
    monkeypatch.setattr(graph_revision.SemanticGraphPatchService, "apply", derive_then_change)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "REJECTED" and len(ledger.pending_events()) == 1


def test_receipt_replay_still_checks_current_authority(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "ACCEPTED"
    runtime.mission_semantic_service.authorize = lambda *args: False
    replay = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert replay.code == Code.AUTHORITY_DENIED and len(ledger.pending_events()) == 2


def test_source_body_corruption_cannot_hide_behind_commit_id(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    with ledger.connection() as conn, conn:
        raw = json.loads(conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source,)).fetchone()[0])
        raw["proposalPayload"]["addNodes"][0]["objective"] = "corrupted body"
        conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?", (json.dumps(raw), source))
    with pytest.raises(ValidationError): ledger.get(source)
    assert runtime.accept_graph_revision(run_id, source, idempotency_key="graph").code == Code.INVALID_PROPOSAL
    assert len(ledger.pending_events()) == 1


def test_legacy_projection_is_readable_but_cannot_be_implicitly_recertified(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    with ledger.connection() as conn, conn:
        raw = json.loads(conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source,)).fetchone()[0])
        assert raw["sourceProvenance"]["version"] == "runtime-static-v2"
        raw["sourceProvenance"]["version"] = "runtime-static-v1"
        legacy = json.dumps(raw)
        conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?", (legacy, source))
    assert ledger.get(source).source_provenance.version == "runtime-static-v1"
    assert runtime.accept_graph_revision(run_id, source, idempotency_key="graph").status == "REJECTED"
    with ledger.connection() as conn:
        assert conn.execute("SELECT payload FROM planning_commit_records WHERE commit_id=?", (source,)).fetchone()[0] == legacy
    assert len(ledger.pending_events()) == 1


@pytest.mark.parametrize("invalid", [None, 12, {"id": "nested"}, "missing"])
def test_null_or_malformed_source_cannot_enter_typed_ledger(ready_boundary, invalid):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    receipt = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert receipt.status == "ACCEPTED"
    raw = ledger.get(receipt.commit_id).model_dump(mode="json", by_alias=True)
    if invalid == "missing": raw["proposalPayload"].pop("sourceCommitId")
    else: raw["proposalPayload"]["sourceCommitId"] = invalid
    from contracts.planning_commit import PlanningCommitRecord
    with pytest.raises(ValidationError): PlanningCommitRecord.model_validate(raw)


def test_index_name_collision_does_not_bypass_transactional_source_guard(ready_boundary):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    with ledger.connection() as conn, conn:
        conn.execute("DROP INDEX planning_graph_source_unique")
        conn.execute("CREATE INDEX planning_graph_source_unique ON planning_commit_records(mission_id)")
    # P2: readiness currently checks only the name. Acceptance still has the
    # serialized source-head/graph lookup guard, even with this malformed index.
    reopened = SQLitePlanningCommitStore(store.db_path)
    assert reopened.supports_graph_revisions
    runtime.enable_planning_commit(reopened)
    assert runtime.accept_graph_revision(run_id, source, idempotency_key="first").status == "ACCEPTED"
    assert runtime.accept_graph_revision(run_id, source, idempotency_key="second").status == "REJECTED"
    assert len(reopened.pending_events()) == 2


@pytest.mark.parametrize("excess", ["run_string", "receipts"])
def test_oversized_current_evidence_cannot_accept(ready_boundary, excess):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    if excess == "run_string":
        run = store.get_run(run_id)
        run.input["oversized"] = "x" * 2_000_001
        store.save_run(run)
    else:
        for i in range(1025):
            runtime.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=f"unrelated:{i}")
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.code == Code.INVALID_PROPOSAL and len(ledger.pending_events()) == 1


def test_fresh_processes_reconstruct_identical_candidates(ready_boundary, tmp_path, monkeypatch):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    run = store.get_run(run_id)
    workflow = runtime._workflow_for_run(run).model_dump(mode="json", by_alias=True)
    captured = []
    original = PlanningCommitService.accept
    def capture(service, request):
        if request.proposal_type == "graph_revision":
            captured.append(service.provider.payload.model_dump(mode="json", by_alias=True))
            from contracts.planning_commit import PlanningCommitRejection
            return PlanningCommitRejection(code=Code.INVALID_PROPOSAL, reason="capture before acceptance")
        return original(service, request)
    monkeypatch.setattr(PlanningCommitService, "accept", capture)
    runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert len(captured) == 1 and len(ledger.pending_events()) == 1
    script = '''
import json, sys
from pathlib import Path
from test_react_loop import runtime_at
from contracts.workflow import WorkflowDefinition
from contracts.mission_semantic import SemanticPrincipal
from components.mission_manager.semantic_service import MissionSemanticService
from support.stores.planning_commit_store import SQLitePlanningCommitStore
data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
runtime,store,_=runtime_at(Path(data["directory"]))
runtime.workflow_registry.register(WorkflowDefinition.model_validate(data["workflow"]))
store._init_semantic_schema()
store.enable_existing_mission_semantics()
owner=SemanticPrincipal(actorId="owner",tenantId="tenant")
runtime.mission_semantic_service=MissionSemanticService(store=store,authorize=lambda p,m,a:p==owner)
runtime.semantic_principal_provider=lambda:owner
runtime.allow_legacy_mission_intent=False
runtime.enable_planning_commit(SQLitePlanningCommitStore(store.db_path))
receipt=runtime.accept_graph_revision(data["run"],data["source"],idempotency_key="graph")
assert receipt.status=="ACCEPTED",receipt.model_dump()
print("CANDIDATE:"+runtime.planning_commit_authority.store.get(receipt.commit_id).proposal_payload.model_dump_json(by_alias=True))
'''
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(Path("src").resolve()), str(Path("tests/components/planner").resolve()), env.get("PYTHONPATH", "")])
    for i in range(2):
        directory = tmp_path / f"restart-{i}"
        directory.mkdir()
        for db in store.db_path.parent.glob("*.sqlite3"):
            with sqlite3.connect(db) as source_db, sqlite3.connect(directory / db.name) as destination:
                source_db.backup(destination)
        input_file = directory / "input.json"
        input_file.write_text(json.dumps(dict(directory=str(directory), workflow=workflow, run=run_id, source=source)), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-c", script, str(input_file)], env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert completed.returncode == 0, completed.stderr
        reconstructed = json.loads(next(line.removeprefix("CANDIDATE:") for line in completed.stdout.splitlines() if line.startswith("CANDIDATE:")))
        assert reconstructed == captured[0]


@pytest.mark.parametrize("kind", ["profile", "catalog"])
def test_transient_profile_change_cannot_escape_frozen_derivation_inputs(ready_boundary, monkeypatch, kind):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    from runtime import graph_revision
    baseline = []
    original_accept = PlanningCommitService.accept
    def capture(service, request):
        if request.proposal_type == "graph_revision":
            baseline.append(service.provider.payload.model_dump(mode="json", by_alias=True))
            from contracts.planning_commit import PlanningCommitRejection
            return PlanningCommitRejection(code=Code.INVALID_PROPOSAL, reason="capture frozen candidate")
        return original_accept(service, request)
    with monkeypatch.context() as preview:
        preview.setattr(PlanningCommitService, "accept", capture)
        assert runtime.accept_graph_revision(run_id, source, idempotency_key="graph").status == "REJECTED"
    assert len(baseline) == 1 and len(ledger.pending_events()) == 1
    original_apply = graph_revision.SemanticGraphPatchService.apply
    agent = next(iter(runtime.agent_registry.all()))
    original_priority = agent.profile.binding_priority
    descriptor = runtime.capability_catalog.get("task_understanding")
    original_contract = descriptor.output_contract
    def transient_change(service, **kwargs):
        if kind == "profile": agent.profile.binding_priority = original_priority + 1000
        else: descriptor.output_contract = {**original_contract, "transientUnboundContract": True}
        try:
            return original_apply(service, **kwargs)
        finally:
            agent.profile.binding_priority = original_priority
            descriptor.output_contract = original_contract
    monkeypatch.setattr(graph_revision.SemanticGraphPatchService, "apply", transient_change)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "ACCEPTED", result.model_dump()
    assert agent.profile.binding_priority == original_priority
    assert ledger.get(result.commit_id).proposal_payload.model_dump(mode="json", by_alias=True) == baseline[0]


@pytest.mark.parametrize("change", ["cancel", "revoke"])
def test_provenance_capture_finishes_before_final_authority_fence(ready_boundary, monkeypatch, change):
    runtime, store, ledger, run_id, source, _ = accepted_source(ready_boundary)
    from runtime.graph_revision import GraphProvider
    original = GraphProvider.get_source_provenance
    def capture_then_change(provider, request):
        result = original(provider, request)
        if change == "cancel": runtime._cancellation_event(run_id).set()
        else: runtime.mission_semantic_service.authorize = lambda *args: False
        return result
    monkeypatch.setattr(GraphProvider, "get_source_provenance", capture_then_change)
    result = runtime.accept_graph_revision(run_id, source, idempotency_key="graph")
    assert result.status == "REJECTED", result.model_dump()
    assert len(ledger.pending_events()) == 1
