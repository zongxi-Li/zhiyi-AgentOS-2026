"""Deterministic, compiler-validated DAG handoff cost and writer contention gates.

All databases are pytest temporary databases. No production policy is patched.
"""
import asyncio
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
import json
import sqlite3
from threading import Event, Thread
import time

import pytest

from components.planner.acg_lowerer import ACGLowerer
from components.planner.lowering_input import build_template_lowering_input
from components.planner.semantic_planner import SemanticPlanner
from components.mission_manager.semantic_service import MissionSemanticService
from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal
from contracts.planning import PlannedTask, TaskPlanPatch, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from runtime.semantic_revision import SemanticRevisionService
from support.acg.planning import CommunicationSpec
from support.stores.graph_activation_store import SQLiteGraphActivationStore
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from test_graph_handoff import attach as attach_handoff
from test_planning_commit_runtime import attach as attach_commit
from test_react_loop import runtime_at


pytestmark = pytest.mark.slow_benchmark


def task(key):
    return PlannedTask(key="step:" + key, title=key, objective="do " + key,
        capabilityRequirements=("task_understanding",), sourceRefs=("input:brief",))


def relation(a, b):
    return TaskPlanRelation(sourceKey="step:" + a, targetKey="step:" + b, relationType="depends_on")


def build_dag(folder, count, completed=1):
    """count includes new D; a real dependency-closed prefix executes first.

    Invoke the real deterministic template Planner/Topology gate/Lowerer directly
    at the Runtime's test fixture construction seam. No model chooses node count.
    """
    rt, workflow, agent = runtime_at(folder)
    keys = ["A", *(f"N{i:03d}" for i in range(1, count - 1))]
    definition = WorkflowDefinition(workflowId="gate", name="gate", domain="general", runtimeEngine="acg",
        planningNodes=tuple(task(k) for k in keys),
        planningRelations=tuple(relation(a, b) for a, b in zip(keys, keys[1:])),
        steps=tuple(WorkflowStepDefinition(stepId=k, name=k, agentName="runner") for k in keys))
    rt.workflow_registry.register(definition)
    writer_definition = WorkflowDefinition(workflowId="gate-writer", name="writer", domain="general", runtimeEngine="acg",
        planningNodes=(task("W"),), steps=(WorkflowStepDefinition(stepId="W", name="W", agentName="runner"),))
    rt.workflow_registry.register(writer_definition)

    def deterministic_template(mission, run, wf):
        plan = SemanticPlanner(rt.capability_catalog).plan_template(
            mission_id=mission.mission_id, workflow=wf, strategy="template")
        frozen = build_template_lowering_input(workflow=wf, task_plan=plan)
        communications = tuple(CommunicationSpec(producerStepId=r.source_key.removeprefix("step:"),
            consumerStepId=r.target_key.removeprefix("step:"),
            channel=r.source_key.removeprefix("step:") + ":" + r.target_key.removeprefix("step:"))
            for r in plan.relations)
        frozen = replace(frozen, resource_plan=frozen.resource_plan.model_copy(update={"communication": communications}))
        graph = ACGLowerer().lower(frozen)
        SemanticRevisionService._validate_bindings(plan, graph, frozen.implementation_bindings)
        return graph, plan, frozen.implementation_bindings

    rt._build_acg_blueprint = deterministic_template
    workflow._init_semantic_schema()
    workflow.enable_existing_mission_semantics()
    owner = SemanticPrincipal(actorId="owner", tenantId="tenant")
    rt.mission_semantic_service = MissionSemanticService(store=workflow, authorize=lambda p, m, a: p == owner)
    rt.semantic_principal_provider = lambda: owner
    rt.allow_legacy_mission_intent = False

    def prepare(wf, objective):
        mission = rt.create_mission(objective, workflow_id=wf)
        rt.mission_semantic_service.commit(owner, MissionSemanticRequest(missionId=mission.mission_id,
            operationId="basis", expectedMissionRevision=0, objective=objective, constraints=[], sourceRefs=["input:brief"]))
        return rt.prepare_run(mission.mission_id)[1]

    writer = prepare("gate-writer", "Save independent Mission diagnostics")
    prepared = prepare("gate", "Execute a deterministic dependency chain safely")
    assert len(prepared.steps) == count - 1
    class Pause:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="wait"
                if sum(s.status == "completed" for s in observation.steps) >= completed else "continue",
                reason="pause after real completed prefix")
    rt.runtime_planning_coordinator.planner_for_run = lambda _: Pause()
    boundary = rt.runtime_planning_coordinator.boundary
    async def observe(run, state, reason):
        return await boundary(run, state, "resume" if len(state.completed_step_ids) >= completed else reason)
    rt.runtime_planning_coordinator.boundary = observe
    asyncio.run(rt.execute_prepared_run(prepared.run_id))
    run = workflow.get_run(prepared.run_id)
    assert run.status == WorkflowStatus.WAITING_REVIEW and agent.calls == keys[:completed]
    assert run.completed_step_ids == keys[:completed]
    attach_commit(rt, workflow)
    patch = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=1, planVersion=2,
        addNodes=(task("D"),), relations=(relation(keys[-1], "D"),))
    with rt.run_lock_manager.lock_for(run.run_id):
        source = rt.planning_commit_authority.accept_patch_locked(run.run_id, patch,
            proposal_id="gate-D", idempotency_key="gate-D")
    assert source.status == "ACCEPTED", source
    accepted = rt.accept_graph_revision(run.run_id, source.commit_id, idempotency_key="gate-graph")
    assert accepted.status == "ACCEPTED", accepted
    SQLiteGraphMaterializationStore.upgrade_schema(workflow.db_path)
    mats = SQLiteGraphMaterializationStore(workflow.db_path)
    rt.enable_graph_materialization(mats)
    materialized = rt.materialize_graph_revision(accepted.commit_id, idempotency_key="gate-mat")
    assert materialized.status == "MATERIALIZED_INACTIVE", materialized
    package = mats.get_materialization(materialized.materialization_id).package
    assert len(package.nodes) == count and len(package.edges) == count - 1
    SQLiteGraphActivationStore.upgrade_schema(workflow.db_path)
    activations = SQLiteGraphActivationStore(workflow.db_path)
    rt.enable_graph_activation(activations)
    assert rt.prepare_graph_activation(materialized.materialization_id, idempotency_key="gate-act").status == "ACTIVATION_PREPARED"
    activation = rt.commit_graph_activation(materialized.materialization_id, idempotency_key="gate-act")
    assert activation.status == "ACTIVATED_PAUSED", activation
    ledger, staged = attach_handoff(rt, workflow)
    return rt, workflow, agent, run.run_id, activation.activation_id, ledger, staged, writer.run_id


class TransactionProbe:
    """Observe real execute/commit boundaries; do not replace the transaction."""
    def __init__(self, inner, samples, on_begin=None, on_attempt=None):
        self.inner, self.samples = inner, samples
        self.on_begin, self.on_attempt = on_begin, on_attempt
        self.sample = None

    def __getattr__(self, key):
        return getattr(self.inner, key)

    @property
    def row_factory(self):
        return self.inner.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self.inner.row_factory = value

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    def execute(self, sql, *args):
        if sql.strip().upper() != "BEGIN IMMEDIATE":
            return self.inner.execute(sql, *args)
        start = time.perf_counter()
        if self.on_attempt:
            self.on_attempt()
        try:
            cursor = self.inner.execute(sql, *args)
        except sqlite3.OperationalError as exc:
            self.samples.append(dict(begin_start=start, wait_ms=(time.perf_counter()-start)*1000, error=str(exc)))
            raise
        acquired = time.perf_counter()
        self.sample = dict(begin_start=start, acquired=acquired, wait_ms=(acquired-start)*1000)
        self.samples.append(self.sample)
        if self.on_begin:
            self.on_begin(len(self.samples), self.sample)
        return cursor

    def commit(self):
        start = time.perf_counter()
        result = self.inner.commit()
        end = time.perf_counter()
        if self.sample is not None:
            self.sample.update(commit_start=start, released=end,
                hold_body_ms=(start-self.sample["acquired"])*1000,
                hold_ms=(end-self.sample["acquired"])*1000,
                transaction_ms=(end-self.sample["begin_start"])*1000,
                commit_ms=(end-start)*1000)
            self.sample = None
        return result


@contextmanager
def observe_cost(rt, ledger, staged, *, on_begin=None, before_validate=None):
    """Test-side wrappers preserve source order and original SQLite settings.

    prefix_evidence_span covers load_ledger through the final Run re-read and
    preceding Identity Attempt checks, ending before IdentityLink construction.
    Source Identity plan-map validation is earlier, included in validation_ms.
    SELECT counts are statements, not pages, objects or returned rows.
    """
    import runtime.graph_handoff as handoff
    from components.executor import ACGGraphCompiler
    metrics = dict(transactions=[], validation_ms=[], compiler_ms=[], safe_cut_ms=[],
        prefix_evidence_span_ms=[], stage_ms=[], selects=Counter())
    prefix_start = [None]
    def timed(original, field):
        def call(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                metrics[field].append((time.perf_counter()-start)*1000)
        return call
    with pytest.MonkeyPatch.context() as patch:
        connect = sqlite3.connect
        def callback_for(name):
            def statement(sql):
                if sql.lstrip().upper().startswith("SELECT"):
                    metrics["selects"][name] += 1
            return statement
        def traced_connect(database, *args, **kwargs):
            conn = connect(database, *args, **kwargs)
            name = next((n for n in ("workflow", "identity", "values", "checkpoint", "audit", "memory", "provenance")
                         if n + ".sqlite3" in str(database)), "other")
            conn.set_trace_callback(callback_for(name))
            return conn
        patch.setattr(sqlite3, "connect", traced_connect)
        original_connect = ledger._connect
        patch.setattr(ledger, "_connect", lambda: TransactionProbe(
            original_connect(), metrics["transactions"], on_begin=on_begin))
        validate = rt.graph_handoff_authority._validated_candidate
        def validation(*args, **kwargs):
            if before_validate:
                before_validate(len(metrics["validation_ms"]) + 1)
            return timed(validate, "validation_ms")(*args, **kwargs)
        patch.setattr(rt.graph_handoff_authority, "_validated_candidate", validation)
        patch.setattr(ACGGraphCompiler, "compile_package", timed(ACGGraphCompiler.compile_package, "compiler_ms"))
        patch.setattr(handoff, "safe_cut", timed(handoff.safe_cut, "safe_cut_ms"))
        patch.setattr(staged, "stage", timed(staged.stage, "stage_ms"))
        load = rt.provenance_store.load_ledger
        def start_prefix(*args, **kwargs):
            prefix_start[0] = time.perf_counter()
            return load(*args, **kwargs)
        patch.setattr(rt.provenance_store, "load_ledger", start_prefix)
        link = handoff.GraphVersionIdentityLink
        def end_prefix(*args, **kwargs):
            metrics["prefix_evidence_span_ms"].append((time.perf_counter()-prefix_start[0])*1000)
            return link(*args, **kwargs)
        patch.setattr(handoff, "GraphVersionIdentityLink", end_prefix)
        persistent = []
        for name, obj in (("identity", rt.identity_lifecycle.repositories.storage),
                ("checkpoint", rt.checkpoint_store), ("values", rt.execution_value_store),
                ("audit", rt.decision_store), ("memory", rt.memory_store), ("provenance", rt.provenance_store)):
            conn = getattr(obj, "_connection", None)
            if isinstance(conn, sqlite3.Connection):
                conn.set_trace_callback(callback_for(name))
                persistent.append(conn)
        try:
            yield metrics
        finally:
            for conn in persistent:
                conn.set_trace_callback(None)


def protected_facts(rt, workflow, run_id):
    # Logical contents, not database file bytes (journals legitimately grow).
    with sqlite3.connect(rt.checkpoint_store.db_path) as conn:
        checkpoints = conn.execute("SELECT * FROM acg_execution_checkpoints ORDER BY rowid").fetchall()
    external = {}
    for name in ("identity", "values", "audit", "memory", "provenance", "content"):
        path = workflow.db_path.parent / (name + ".sqlite3")
        with sqlite3.connect(path) as conn:
            external[name] = tuple(conn.iterdump())
    with sqlite3.connect(workflow.db_path) as conn:
        head = conn.execute("SELECT * FROM graph_activation_heads WHERE run_id=?", (run_id,)).fetchall()
    return (workflow.get_run(run_id), checkpoints, external, head)


def assert_prepared(fixture, before, result, count):
    rt, workflow, agent, run_id, activation, ledger, staged, _ = fixture
    assert result.status == "STATE_PREPARED", result
    assert protected_facts(rt, workflow, run_id) == before
    record = ledger.get_handoff(result.handoff_id)
    completed = before[0].completed_step_ids
    assert record.status == "STATE_PREPARED" and record.graph_version == 2
    assert record.candidate == staged.get(record.candidate.checkpoint_id)
    assert record.candidate.state["completedStepIds"] == completed
    assert rt.checkpoint_store.load(run_id=run_id, checkpoint_id=record.candidate.checkpoint_id) is None
    assert len(workflow.get_run(run_id).steps) == count
    assert all(s.status.value == "pending" and not s.attempt and not s.retry_count
        and not s.output and not s.resolved_input and not s.started_at and not s.completed_at
        for s in workflow.get_run(run_id).steps if s.step_id not in completed)
    assert len(before[3]) == 1 and before[3][0][3] == 2
    receipts = rt.execution_value_store.list_node_commits(run_id=run_id)
    assert len(receipts) == len(completed) and {r["nodeExecution"]["stepId"] for r in receipts} == set(completed)
    assert all(r["nodeExecution"]["auditRef"] == r["auditDecisionRef"] for r in receipts)
    assert len(record.identity_link.prefix_attempt_ids) == len(completed)
    assert agent.calls == completed
    assert workflow.get_run(run_id).execution_state.get("executionPermit") is None
    with ledger.connection() as conn:
        assert conn.execute("SELECT count(*) FROM graph_handoffs WHERE activation_id=?", (activation,)).fetchone()[0] == 1
    with pytest.raises(ValueError, match="execution permit"):
        asyncio.run(rt.execute_prepared_run(run_id))
    assert agent.calls == completed
    assert protected_facts(rt, workflow, run_id) == before


def persisted_sizes(fixture, result):
    rt, workflow, _, run_id, activation, ledger, staged, _ = fixture
    with ledger.connection() as conn:
        mat = ledger.get_materialization(ledger.get_activation(activation).materialization_id)
        run_bytes = conn.execute("SELECT length(CAST(payload AS BLOB)) FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
    with sqlite3.connect(workflow.db_path.parent / "identity.sqlite3") as conn:
        identity_logical_bytes = conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
        identity_sql_dump_bytes = len("\n".join(conn.iterdump()).encode())
    return dict(run_bytes=run_bytes,
        checkpoint_json_bytes=len(json.dumps(rt.checkpoint_store.load_latest(run_id=run_id)[1], ensure_ascii=False).encode()),
        package_json_bytes=len(mat.package.model_dump_json(by_alias=True).encode()),
        stage_json_bytes=len(staged.get(ledger.get_handoff(result.handoff_id).candidate.checkpoint_id).model_dump_json(by_alias=True).encode()),
        identity_logical_bytes=identity_logical_bytes, identity_sql_dump_bytes=identity_sql_dump_bytes,
        database_file_bytes={p.name:p.stat().st_size for p in workflow.db_path.parent.glob("*.sqlite3*")})


@pytest.mark.parametrize("count,completed", [(4,1), (8,1), (16,1), (32,1), (64,1), (128,1), (32,4), (32,8)])
def test_valid_dag_cost_and_no_execution(tmp_path, count, completed):
    samples = []
    for repeat in range(3):
        folder = tmp_path / str(repeat)
        folder.mkdir()
        fixture = build_dag(folder, count, completed)
        rt, workflow, _, run_id, activation, ledger, staged, _ = fixture
        before = protected_facts(rt, workflow, run_id)
        with observe_cost(rt, ledger, staged) as metrics:
            start = time.perf_counter()
            result = rt.prepare_graph_handoff(activation, idempotency_key="gate-handoff")
            metrics["api_ms"] = (time.perf_counter()-start)*1000
        assert_prepared(fixture, before, result, count)
        assert len(metrics["transactions"]) == 2 and len(metrics["validation_ms"]) == 3
        assert len(metrics["safe_cut_ms"]) == 3 and len(metrics["compiler_ms"]) == 6
        assert len(metrics["prefix_evidence_span_ms"]) == 3
        assert all(t["transaction_ms"] >= t["hold_ms"] >= 0 and t["wait_ms"] >= 0 for t in metrics["transactions"])
        assert metrics["selects"]["identity"] > 0 and metrics["selects"]["audit"] > 0
        metrics.update(nodes=count, completed=completed, repeat=repeat, status=result.status, sizes=persisted_sizes(fixture, result))
        samples.append(metrics)
    (tmp_path / "measurements.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
    print("HANDOFF_GATE_RESULT " + json.dumps(samples))


@pytest.mark.parametrize("count", [4, 32, 128])
def test_other_mission_writer_outside_and_inside_final_transaction(tmp_path, count):
    from contracts.workflow import utc_now
    from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
    fixture = build_dag(tmp_path, count)
    rt, workflow, _, run_id, activation, ledger, staged, writer_id = fixture
    before = protected_facts(rt, workflow, run_id)
    independent = SQLiteWorkflowStore(workflow.db_path)
    independent.enable_existing_mission_semantics()
    assert independent.busy_timeout_ms == workflow.busy_timeout_ms
    original_connect = independent._connect
    writer_transactions, writer_results = [], []
    attempted = Event()
    workers = []
    final_snapshot = [None]
    def write(phase):
        start = time.perf_counter()
        try:
            if phase == "retry":
                run = final_snapshot[0].model_copy(deep=True)
            else:
                run = independent.get_run(writer_id)
                run.updated_at = utc_now()
            if phase == "final":
                final_snapshot[0] = run.model_copy(deep=True)
            independent.save_run(run)
            writer_results.append(dict(phase=phase, status="SAVED", elapsed_ms=(time.perf_counter()-start)*1000))
        except sqlite3.OperationalError as exc:
            writer_results.append(dict(phase=phase, status="BUSY_TIMEOUT" if "locked" in str(exc).lower() else "ERROR",
                error=str(exc), elapsed_ms=(time.perf_counter()-start)*1000))
        except Exception as exc:
            writer_results.append(dict(phase=phase, status="ERROR", error=repr(exc)))
    def before_validate(index):
        if index == 1:
            write("outside")
            assert writer_results[-1]["status"] == "SAVED"
    def after_begin(index, sample):
        if index == 2:
            attempted.clear()
            worker = Thread(target=write, args=("final",), daemon=True)
            workers.append(worker)
            worker.start()
            assert attempted.wait(15), "independent writer never attempted BEGIN"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(independent, "_connect", lambda: TransactionProbe(
            original_connect(), writer_transactions, on_attempt=attempted.set))
        with observe_cost(rt, ledger, staged, on_begin=after_begin, before_validate=before_validate) as metrics:
            start = time.perf_counter()
            result = rt.prepare_graph_handoff(activation, idempotency_key="gate-contention")
            metrics["api_ms"] = (time.perf_counter()-start)*1000
        for worker in workers:
            worker.join(20)
            assert not worker.is_alive()
    assert_prepared(fixture, before, result, count)
    assert [r["phase"] for r in writer_results] == ["outside", "final"]
    assert writer_results[0]["status"] == "SAVED"
    assert writer_results[1]["status"] in {"SAVED", "BUSY_TIMEOUT"}, writer_results
    final_tx = metrics["transactions"][1]
    competing_tx = writer_transactions[1]
    assert final_tx["acquired"] <= competing_tx["begin_start"] < final_tx["released"]
    if writer_results[1]["status"] == "SAVED":
        assert competing_tx["acquired"] >= final_tx["commit_start"]
    with sqlite3.connect(workflow.db_path) as conn:
        outbox_before = conn.execute("SELECT count(*) FROM lifecycle_outbox").fetchone()[0]
    # Retry normal save and handoff after contention, without changing timeouts.
    write("retry")
    assert writer_results[-1]["status"] == "SAVED"
    if writer_results[1]["status"] == "SAVED":
        with sqlite3.connect(workflow.db_path) as conn:
            assert conn.execute("SELECT count(*) FROM lifecycle_outbox").fetchone()[0] == outbox_before
    assert rt.prepare_graph_handoff(activation, idempotency_key="gate-contention").status == "IDEMPOTENT_REPLAY"
    assert independent.get_run(writer_id) == workflow.get_run(writer_id)
    metrics.update(nodes=count, status=result.status, busy_timeout_ms=independent.busy_timeout_ms,
        writers=writer_results, writer_transactions=writer_transactions)
    (tmp_path / "contention.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print("HANDOFF_GATE_CONTENTION " + json.dumps(metrics))
