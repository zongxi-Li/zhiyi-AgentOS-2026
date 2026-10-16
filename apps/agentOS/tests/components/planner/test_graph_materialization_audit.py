"""Independent materialization adversaries against actual persisted Runtime facts."""
import json
import asyncio
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from contracts import stable_checksum
from components.executor.compiler import ACGGraphCompiler
from contracts.planning_commit import PlanningCommitRejectionCode as Code
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from test_graph_materialization import setup, unchanged_except_journal
from test_horizon import ready_boundary, runtime_boundary


@pytest.mark.parametrize("change", ["receipt", "checkpoint", "profile", "catalog", "workflow"])
def test_final_identity_read_cannot_hide_trusted_source_changes(ready_boundary, change):
    runtime, workflow, journal, run_id, commit, _ = setup(ready_boundary)
    principal = runtime.semantic_principal_provider()
    calls = []
    def identity_with_concurrent_change():
        calls.append(True)
        if len(calls) == 4:
            if change == "receipt":
                runtime.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=f"commit:{run_id}:A:1")
            elif change == "checkpoint":
                from runtime.state_persistence import acg_execution_state_from_run
                run = workflow.get_run(run_id)
                state = acg_execution_state_from_run(run)
                state.graph_id = run.acg_blueprint["graphId"]
                state.review_payload = {"subjectType": "node", "subjectId": "A"}
                runtime.acg_state_persistence.save_checkpoint(run, state)
            elif change == "profile":
                next(iter(runtime.agent_registry.all())).profile.binding_priority += 1
            elif change == "catalog":
                runtime.capability_catalog.get("task_understanding").output_contract["new"] = True
            else:
                definition = runtime._workflow_for_run(workflow.get_run(run_id))
                runtime.workflow_registry.register(definition.model_copy(update={"domain": "new-domain"}))
        return principal
    runtime.semantic_principal_provider = identity_with_concurrent_change
    result = runtime.materialize_graph_revision(commit, idempotency_key="audit")
    assert result.status == "REJECTED", result.model_dump()
    assert journal.materialization_for(commit) is None


@pytest.mark.parametrize("kind", ["profile", "catalog"])
def test_transient_live_registry_changes_do_not_change_complete_package(ready_boundary, monkeypatch, kind):
    runtime, workflow, journal, run_id, commit, _ = setup(ready_boundary)
    proposal = journal.get(commit).proposal_payload
    expected = ACGGraphCompiler().compile_package(proposal.candidate_graph, run_id=run_id).model_dump(mode="json", by_alias=True)
    before = unchanged_except_journal(workflow)
    original = ACGGraphCompiler.compile_package
    profile = next(iter(runtime.agent_registry.all())).profile
    priority = profile.binding_priority
    descriptor = runtime.capability_catalog.get("task_understanding")
    old_contract = descriptor.output_contract
    def compile_with_transient_registry_change(compiler, *args, **kwargs):
        if kind == "profile": profile.binding_priority += 1000
        else: descriptor.output_contract = {"transient": "different contract"}
        try:
            return original(compiler, *args, **kwargs)
        finally:
            profile.binding_priority = priority
            descriptor.output_contract = old_contract
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", compile_with_transient_registry_change)
    result = runtime.materialize_graph_revision(commit, idempotency_key="audit")
    assert result.status == "MATERIALIZED_INACTIVE", result.model_dump()
    assert journal.get_materialization(result.materialization_id).package.model_dump(mode="json", by_alias=True) == expected
    assert unchanged_except_journal(workflow) == before


@pytest.mark.parametrize("field", ["binding", "communication", "blueprint", "version"])
def test_package_field_or_compiler_version_corruption_is_rejected(ready_boundary, monkeypatch, field):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    original = ACGGraphCompiler.compile_package
    def corrupted(compiler, *args, **kwargs):
        package = original(compiler, *args, **kwargs)
        if field == "binding":
            manifest = package.binding_manifest
            rules = (manifest.rules[0].model_copy(update={"max_concurrency": 99}), *manifest.rules[1:])
            return package.model_copy(update={"binding_manifest": manifest.model_copy(update={"rules": rules})})
        if field == "communication":
            return package.model_copy(update={"communication_manifest": package.communication_manifest.model_copy(update={"run_id": "foreign-run"})})
        return package.model_copy(update={"blueprint_hash": "0"*64} if field == "blueprint" else {"package_version": 3})
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", corrupted)
    before = unchanged_except_journal(workflow)
    assert runtime.materialize_graph_revision(commit, idempotency_key="audit").status == "REJECTED"
    assert journal.materialization_for(commit) is None and unchanged_except_journal(workflow) == before


@pytest.mark.parametrize("field,value", [("status", "ACTIVE"), ("validationPolicy", "materialization-dag-v0"),
                                         ("version", "graph-materialization-v0")])
def test_unknown_or_active_journal_status_cannot_be_replayed(ready_boundary, field, value):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    receipt = runtime.materialize_graph_revision(commit, idempotency_key="audit")
    assert receipt.status == "MATERIALIZED_INACTIVE"
    with journal.connection() as conn, conn:
        raw = json.loads(conn.execute("SELECT payload FROM graph_materializations").fetchone()[0])
        raw[field] = value
        conn.execute("UPDATE graph_materializations SET payload=?", (json.dumps(raw),))
    before = unchanged_except_journal(workflow)
    assert runtime.materialize_graph_revision(commit, idempotency_key="audit").status == "REJECTED"
    assert unchanged_except_journal(workflow) == before


@pytest.mark.parametrize("commit_id", [None, 12, {"candidateGraph": {"version": 2}, "permission": "execute"}])
def test_client_payload_is_not_a_materialization_source(ready_boundary, commit_id):
    runtime, _, journal, _, _, _ = setup(ready_boundary)
    assert runtime.materialize_graph_revision(commit_id, idempotency_key="audit").code == Code.INVALID_PROPOSAL
    with journal.connection() as conn:
        assert conn.execute("SELECT count(*) FROM graph_materializations").fetchone()[0] == 0


def child_environment():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(Path("src").resolve()), str(Path("tests/components/planner").resolve()), env.get("PYTHONPATH", "")])
    return env


CHILD = '''
import json,sys,asyncio
from pathlib import Path
from test_react_loop import runtime_at
from contracts.workflow import WorkflowDefinition
from contracts.mission_semantic import SemanticPrincipal
from components.mission_manager.semantic_service import MissionSemanticService
from support.stores.planning_commit_store import SQLitePlanningCommitStore
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
runtime,store,agent=runtime_at(Path(data["directory"]))
runtime.workflow_registry.register(WorkflowDefinition.model_validate(data["workflow"]))
store.enable_existing_mission_semantics()
principal=SemanticPrincipal(actorId="owner",tenantId="tenant")
runtime.mission_semantic_service=MissionSemanticService(store=store,authorize=lambda p,m,a:p==principal)
runtime.semantic_principal_provider=lambda:principal
runtime.allow_legacy_mission_intent=False
runtime.enable_planning_commit(SQLitePlanningCommitStore(store.db_path))
journal=SQLiteGraphMaterializationStore(store.db_path)
runtime.enable_graph_materialization(journal)
def forbidden(*a,**k): raise AssertionError("restart invoked Planner/lowering/execution")
runtime.runtime_planning_coordinator.planner_for_run=forbidden
runtime.semantic_revision_service.prepare=forbidden
runtime.runtime_binding_service.prepare=forbidden
result=runtime.materialize_graph_revision(data["commit"],idempotency_key=sys.argv[2])
if data.get("recover"):
    asyncio.run(runtime._recover_pending_planning_transitions(limit=10))
record=journal.materialization_for(data["commit"])
assert not agent.calls
print("RESULT:"+json.dumps({"receipt":result.model_dump(mode="json",by_alias=True),
    "record":record.model_dump(mode="json",by_alias=True) if record else None,
    "run":store.get_run(data["run"]).model_dump(mode="json",by_alias=True)},ensure_ascii=False,sort_keys=True))
'''


def child_input(runtime, workflow, run_id, commit, directory, *, recover=False):
    directory.mkdir(exist_ok=True)
    for db in workflow.db_path.parent.glob("*.sqlite3"):
        with sqlite3.connect(db) as source, sqlite3.connect(directory / db.name) as target:
            source.backup(target)
    payload = dict(directory=str(directory), workflow=runtime._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True),
                   run=run_id, commit=commit, recover=recover)
    path = directory / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def parse_child(completed):
    assert completed.returncode == 0, completed.stderr
    return json.loads(next(line.removeprefix("RESULT:") for line in completed.stdout.splitlines() if line.startswith("RESULT:")))


def test_independent_new_processes_compile_identical_complete_packages(ready_boundary, tmp_path):
    runtime, workflow, journal, run_id, commit, _ = setup(ready_boundary)
    expected = ACGGraphCompiler().compile_package(journal.get(commit).proposal_payload.candidate_graph, run_id=run_id)
    records = []
    for index in range(2):
        path = child_input(runtime, workflow, run_id, commit, tmp_path / f"rebuild-{index}")
        result = parse_child(subprocess.run([sys.executable, "-c", CHILD, str(path), "audit"],
                                           env=child_environment(), capture_output=True, text=True, encoding="utf-8", timeout=120))
        assert result["receipt"]["status"] == "MATERIALIZED_INACTIVE"
        records.append(result["record"])
    assert records[0] == records[1]
    assert records[0]["package"] == expected.model_dump(mode="json", by_alias=True)
    assert journal.materialization_for(commit) is None


@pytest.mark.parametrize("same_key", [True, False])
def test_cross_process_sqlite_uniqueness_does_not_depend_on_run_lock(ready_boundary, tmp_path, same_key):
    runtime, workflow, _, run_id, commit, _ = setup(ready_boundary)
    path = child_input(runtime, workflow, run_id, commit, tmp_path / "shared")
    children = [subprocess.Popen([sys.executable, "-c", CHILD, str(path), "shared" if same_key else f"key-{i}"],
                env=child_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for i in range(2)]
    results = []
    for child in children:
        out, err = child.communicate(timeout=120)
        results.append(parse_child(subprocess.CompletedProcess(child.args, child.returncode, out, err)))
    statuses = [r["receipt"]["status"] for r in results]
    assert statuses.count("MATERIALIZED_INACTIVE") == 1, results
    assert ("IDEMPOTENT_REPLAY" if same_key else "REJECTED") in statuses
    assert results[0]["record"] == results[1]["record"]
    with sqlite3.connect(path.parent / "workflow.sqlite3") as conn:
        assert conn.execute("SELECT count(*) FROM graph_materializations").fetchone()[0] == 1


@pytest.mark.parametrize("explicit_communication", [False, True])
def test_real_executed_A_pending_BC_materialized_D_survives_process_restart(tmp_path, explicit_communication):
    from test_react_loop import runtime_at
    from test_planning_commit_runtime import attach
    from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus, StepStatus
    from contracts.planning import PlannedTask, TaskPlanPatch, TaskPlanRelation
    from contracts.runtime_planning import RuntimePlanningDecision
    from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal
    from components.mission_manager.semantic_service import MissionSemanticService
    runtime, workflow, agent = runtime_at(tmp_path)
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="abc", name="abc", domain="general", runtimeEngine="acg",
        planningNodes=tuple(PlannedTask(key="step:"+k, title=k, objective="do "+k,
            capabilityRequirements=("task_understanding",), sourceRefs=("input:brief",)) for k in "ABC"),
        planningRelations=tuple(TaskPlanRelation(sourceKey="step:"+a, targetKey="step:"+b,
            relationType="depends_on") for a,b in (("A","B"),("B","C"))),
        steps=tuple(WorkflowStepDefinition(stepId=k, name=k, agentName="runner") for k in "ABC")))
    workflow._init_semantic_schema()
    workflow.enable_existing_mission_semantics()
    owner = SemanticPrincipal(actorId="owner", tenantId="tenant")
    runtime.mission_semantic_service = MissionSemanticService(store=workflow, authorize=lambda p,m,a:p==owner)
    runtime.semantic_principal_provider = lambda: owner
    runtime.allow_legacy_mission_intent = False
    mission = runtime.create_mission("abc", workflow_id="abc")
    runtime.mission_semantic_service.commit(owner, MissionSemanticRequest(missionId=mission.mission_id,
        operationId="basis", expectedMissionRevision=0, objective="Perform ABC safely", constraints=[], sourceRefs=["input:brief"]))
    class Planner:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="wait" if any(s.step_id == "A" and s.status == "completed" for s in observation.steps) else "continue",
                reason="pause after real A")
    runtime.runtime_planning_coordinator.planner_for_run = lambda _: Planner()
    original_boundary = runtime.runtime_planning_coordinator.boundary
    async def pause_at_completed_boundary(run, state, reason):
        # Force a normal planner observation at the quiescent node boundary,
        # rather than waiting for a verification-capability progress signal.
        return await original_boundary(run, state, "resume" if "A" in state.completed_step_ids else reason)
    runtime.runtime_planning_coordinator.boundary = pause_at_completed_boundary
    if explicit_communication:
        # Construct a complete initial graph fixture BEFORE persistence/execution.
        # Legacy template graphs omit explicit communication contracts; the
        # existing safe-cut deliberately refuses to add them to a settled A.
        from support.acg.planning import CommunicationSpec
        from runtime.semantic_revision import SemanticRevisionService
        original_build = runtime._build_acg_blueprint
        def complete_initial_graph(*args, **kwargs):
            blueprint, plan, bindings = original_build(*args, **kwargs)
            blueprint.resource_plan = blueprint.resource_plan.model_copy(update={"communication": tuple(
                CommunicationSpec(producerStepId=a, consumerStepId=b, channel=a+":"+b)
                for a,b in (("A","B"),("B","C")))})
            SemanticRevisionService._validate_bindings(plan, blueprint, bindings)
            return blueprint, plan, bindings
        runtime._build_acg_blueprint = complete_initial_graph
    _, prepared = runtime.prepare_run(mission.mission_id)
    asyncio.run(runtime.execute_prepared_run(prepared.run_id))
    run = workflow.get_run(prepared.run_id)
    assert run.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A"]
    assert run.get_step("A").status == StepStatus.COMPLETED
    assert all(run.get_step(k).status == StepStatus.PENDING for k in "BC")
    receipts = runtime.execution_value_store.list_node_commits(run_id=run.run_id)
    assert receipts and any(f":A:" in r["commitId"] for r in receipts)
    ledger = attach(runtime, workflow)
    run = workflow.get_run(run.run_id)
    candidate = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=1, planVersion=2,
        addNodes=(PlannedTask(key="step:D", title="D", objective="do D", capabilityRequirements=("task_understanding",),
                             sourceRefs=("input:brief",)),))
    with runtime.run_lock_manager.lock_for(run.run_id):
        source = runtime.planning_commit_authority.accept_patch_locked(run.run_id, candidate,
            proposal_id="D", idempotency_key="D")
    assert source.status == "ACCEPTED", source.model_dump()
    graph = runtime.accept_graph_revision(run.run_id, source.commit_id, idempotency_key="graph-D")
    if not explicit_communication:
        assert graph.status == "REJECTED" and graph.reason == "protected logical implementation changed"
        return
    assert graph.status == "ACCEPTED", graph.model_dump()
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    journal = SQLiteGraphMaterializationStore(workflow.db_path)
    runtime.enable_graph_materialization(journal)
    before = unchanged_except_journal(workflow)
    result = runtime.materialize_graph_revision(graph.commit_id, idempotency_key="audit")
    assert result.status == "MATERIALIZED_INACTIVE", result.model_dump()
    assert unchanged_except_journal(workflow) == before and agent.calls == ["A"]
    record = journal.get_materialization(result.materialization_id)
    assert len(record.package.nodes) == 4 and workflow.get_run(run.run_id).acg_blueprint["version"] == 1
    path = child_input(runtime, workflow, run.run_id, graph.commit_id, tmp_path / "restart", recover=True)
    reconstructed = parse_child(subprocess.run([sys.executable, "-c", CHILD, str(path), "audit"], env=child_environment(),
        capture_output=True, text=True, encoding="utf-8", timeout=120))
    assert reconstructed["receipt"]["status"] == "IDEMPOTENT_REPLAY"
    assert reconstructed["record"] == record.model_dump(mode="json", by_alias=True)
    assert reconstructed["run"] == workflow.get_run(run.run_id).model_dump(mode="json", by_alias=True)
    restarted = SQLiteGraphMaterializationStore(path.parent / "workflow.sqlite3")
    assert restarted.get_materialization(result.materialization_id) == record
    with sqlite3.connect(path.parent / "values.sqlite3") as conn:
        assert not any(":D:" in row[0] for row in conn.execute("SELECT commit_id FROM acg_node_commits"))


@pytest.mark.parametrize("change", ["retry", "committed", "failed", "skipped", "cancelled", "node_review",
                                    "scope", "inbox", "mission", "identity", "checkpoint_ack", "control_history"])
def test_actual_execution_or_authority_progress_during_compilation_refuses_registration(ready_boundary, monkeypatch, change):
    from contracts.workflow import StepStatus
    runtime, workflow, journal, run_id, commit, _ = setup(ready_boundary)
    original = ACGGraphCompiler.compile_package
    progressed = []
    def compile_then_progress(compiler, *args, **kwargs):
        package = original(compiler, *args, **kwargs)
        run = workflow.get_run(run_id)
        if change == "committed":
            key = f"commit:{run_id}:A:1"
            runtime.execution_value_store.prepare_node_commit(run_id=run_id, commit_id=key)
            runtime.execution_value_store.complete_node_commit(run_id=run_id, commit_id=key, payload={"stage": "committed"})
        elif change == "mission":
            from contracts.mission_semantic import MissionSemanticRequest
            runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
                missionId=run.mission_id, operationId="audit-edit", expectedMissionRevision=1, objective="new objective", constraints=[]))
        elif change == "identity":
            plan = runtime.identity_lifecycle.repositories.task_plans.latest(run.mission_id)
            runtime.identity_lifecycle.repositories.persist_task_plan(plan.model_copy(update={"plan_version": plan.plan_version+1}))
        elif change == "inbox":
            from contracts.runtime_planning import RuntimeUserInput
            from contracts.workflow import utc_now
            workflow.save_planning_input(run_id, "new-input", RuntimeUserInput(sourceRunId=run_id,
                operationId="new-input", content="new operator input", submittedAt=utc_now()).model_dump(mode="json", by_alias=True))
        else:
            if change == "retry": run.steps[0].retry_count += 1
            elif change in {"failed", "skipped", "cancelled"}:
                run.steps[0].status = StepStatus.SKIPPED_BY_CONDITION if change == "skipped" else StepStatus(change)
            elif change == "node_review": run.steps[0].status = StepStatus.WAITING_REVIEW
            elif change == "scope": run.execution_scope = run.execution_scope.model_copy(update={"capability_ids": ()})
            elif change == "control_history": run.execution_state["controlReviewDecisions"] = {"branch": "approved"}
            elif change == "checkpoint_ack":
                from runtime.state_persistence import acg_execution_state_from_run
                state = acg_execution_state_from_run(run)
                state.graph_id = run.acg_blueprint["graphId"]
                state.output_summaries["A"] = "new output evidence"
                ref = runtime.checkpoint_store.save(run_id=run_id, state=state.model_dump(mode="json", by_alias=True))
                run.execution_state["checkpointId"] = ref
            workflow.save_run(run)
        progressed.append(change)
        return package
    monkeypatch.setattr(ACGGraphCompiler, "compile_package", compile_then_progress)
    assert runtime.materialize_graph_revision(commit, idempotency_key="audit").status == "REJECTED"
    assert progressed == [change], "the adversarial state change must actually complete"
    assert journal.materialization_for(commit) is None


def test_commit_failure_before_durability_rolls_back_entire_row(ready_boundary, monkeypatch):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    original = journal._connect
    class Connection:
        def __init__(self): self.inner = original()
        def __getattr__(self, name): return getattr(self.inner, name)
        def commit(self): raise sqlite3.OperationalError("commit failed before durability")
    before = unchanged_except_journal(workflow)
    monkeypatch.setattr(journal, "_connect", Connection)
    assert runtime.materialize_graph_revision(commit, idempotency_key="audit").code == Code.STORAGE_UNAVAILABLE
    monkeypatch.setattr(journal, "_connect", original)
    assert journal.materialization_for(commit) is None and unchanged_except_journal(workflow) == before
    assert runtime.materialize_graph_revision(commit, idempotency_key="audit").status == "MATERIALIZED_INACTIVE"


def test_conflicting_historical_journal_blocks_schema_upgrade_atomically(ready_boundary):
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    result = runtime.materialize_graph_revision(commit, idempotency_key="audit")
    record = journal.get_materialization(result.materialization_id)
    duplicate = record.model_copy(update={"materialization_id": "duplicate", "idempotency_key": "other"})
    with journal.connection() as conn, conn:
        conn.execute("DROP INDEX graph_materialization_source_unique")
        conn.execute("INSERT INTO graph_materializations VALUES(?,?,?,?,?)", (duplicate.materialization_id,
            duplicate.idempotency_key, duplicate.source_commit_id, duplicate.model_dump_json(by_alias=True), stable_checksum(duplicate)))
    before = unchanged_except_journal(workflow)
    with pytest.raises(sqlite3.IntegrityError): SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    assert unchanged_except_journal(workflow) == before
    assert runtime.materialize_graph_revision(commit, idempotency_key="audit").status == "REJECTED"


@pytest.mark.parametrize("change", ["source_run", "semantic_bindings"])
def test_rehashed_schema_valid_candidate_cannot_change_source_or_semantics(ready_boundary, change):
    from contracts.graph_revision import GraphRevisionProposal
    from contracts.planning_commit import PlanningCommitRecord
    from support.stores.planning_commit_store import content_fingerprint
    runtime, workflow, journal, _, commit, _ = setup(ready_boundary)
    record = journal.get(commit)
    proposal = record.proposal_payload
    updates = {}
    if change == "source_run":
        provenance = proposal.source_provenance.model_copy(update={"source_run_id": "foreign-run"})
        proposal = proposal.model_copy(update={"source_provenance": provenance})
        updates["source_provenance"] = provenance
    else:
        first, second = proposal.next_bindings
        proposal = proposal.model_copy(update={"next_bindings": (
            first.model_copy(update={"acg_node_id": second.acg_node_id}),
            second.model_copy(update={"acg_node_id": first.acg_node_id}))})
    proposal = GraphRevisionProposal.model_validate_json(proposal.model_dump_json(by_alias=True))
    updates.update(proposal_payload=proposal, proposal_fingerprint=content_fingerprint(proposal))
    forged = PlanningCommitRecord.model_validate_json(record.model_copy(update=updates).model_dump_json(by_alias=True))
    with journal.connection() as conn, conn:
        conn.execute("UPDATE planning_commit_records SET payload=? WHERE commit_id=?", (forged.model_dump_json(by_alias=True), commit))
    before = unchanged_except_journal(workflow)
    assert runtime.materialize_graph_revision(commit, idempotency_key="audit").status == "REJECTED"
    assert journal.materialization_for(commit) is None and unchanged_except_journal(workflow) == before
