"""Production-composition Initial chain, restart recovery and legacy coexistence.

Every Runtime here is constructed through the real application composition
root (apps/agent/app/execution/wiring.build_default_runtime).  Authorities
are never wired by hand: only the business workflow/agent registration and
the trusted-principal seam (in production stamped by the HTTP boundary) are
installed on top, exactly as the offline example and existing chain tests do.
"""
import asyncio
from pathlib import Path
import sqlite3

import pytest

from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal
from examples.contract_review import (
    CONTRACT,
    WORKFLOW_ID,
    BoundaryPlanner,
    ContractReviewAgent,
    workflow as contract_workflow,
)
from support.stores import c2_schema_upgrade as ops
from test_horizon import ready_resource


ROOT = Path(__file__).resolve().parents[5]
OWNER = SemanticPrincipal(actorId="assembly-owner", tenantId="assembly-tenant")

ENV_KEYS = ("AGENTOS_WORKFLOW_DB_PATH", "AGENTOS_LANGGRAPH_CHECKPOINT_DB", "AGENTOS_EXECUTION_VALUE_DB",
            "AGENTOS_CONTENT_MANIFEST_DB", "AGENTOS_EXECUTION_MEMORY_DB", "AGENTOS_PROVENANCE_DB",
            "AGENTOS_AUDIT_DB", "AGENTOS_RESOURCE_DB", "AGENTOS_NODE_DB", "AGENTOS_AGENT_DB",
            "AGENTOS_RESOURCE_HEALTH_DB", "AGENTOS_EVOLUTION_DB", "AGENTOS_IDENTITY_DB")


class ScopedTools:
    def scoped(self, allowed_tools):
        return self


class FailingIntentLLM:
    """Deterministic planning must never fall back to a model in these paths."""

    def generate_json(self, *args, **kwargs):
        raise AssertionError("assembly planning must stay deterministic")


@pytest.fixture(autouse=True)
def _app_composition_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "apps" / "agent"))


def prepared_folder(tmp_path, name="agentos"):
    """Operator-prepared trio; the CLI-equivalent explicit upgrade on test DBs."""
    folder = tmp_path / name
    paths = {
        "workflow": folder / "workflow.sqlite",
        "checkpoint": folder / "checkpoint.sqlite",
        "identity": folder / "identity.sqlite",
    }
    for role, path in paths.items():
        ops._initialize(role, path)
    assert ops.upgrade_databases(**paths)["status"] == "READY"
    return folder


def composition_env(folder, *, semantic, c2):
    trio = {
        "AGENTOS_WORKFLOW_DB_PATH": folder / "workflow.sqlite",
        "AGENTOS_LANGGRAPH_CHECKPOINT_DB": folder / "checkpoint.sqlite",
        "AGENTOS_IDENTITY_DB": folder / "identity.sqlite",
    }
    env = {key: str(trio.get(key, folder / f"{key}.sqlite")) for key in ENV_KEYS}
    env["AGENTOS_MISSION_SEMANTIC_CONVERGENCE"] = "true" if semantic else "false"
    env["AGENTOS_C2_EXECUTION_AUTHORITIES"] = "true" if c2 else "false"
    return env


def build(folder, *, semantic=True, c2=True):
    from app.execution.wiring import build_default_runtime
    runtime = build_default_runtime(
        environment=composition_env(folder, semantic=semantic, c2=c2),
        tool_runtime=ScopedTools(), model_runtime=object(), intent_llm=FailingIntentLLM(),
    )
    agent = ContractReviewAgent()
    runtime.agent_registry.register(agent)
    runtime.workflow_registry.register(contract_workflow())
    # Production supplies the trusted semantic principal at the HTTP boundary;
    # tests inject the same seam with a fixed principal. Ownership is still
    # verified by the wiring's own authorize function against stamped input.
    runtime.semantic_principal_provider = lambda: OWNER
    runtime.runtime_planning_coordinator.planner_for_run = lambda run: BoundaryPlanner()
    return runtime, agent


def semantic_mission(runtime, title="装配级合同审查"):
    mission = runtime.create_mission(title, workflow_id=WORKFLOW_ID, input={
        "contractText": CONTRACT,
        "authenticatedUserId": OWNER.actor_id,
        "authenticatedTenantId": OWNER.tenant_id,
        "deterministicIntent": True,
    })
    runtime.mission_semantic_service.commit(OWNER, MissionSemanticRequest(
        missionId=mission.mission_id, operationId=f"assembly:{mission.mission_id}",
        expectedMissionRevision=0, objective="审查CRM开发合同并交付可追溯报告",
        constraints=[], sourceRefs=["input:contractText"]))
    _, run = runtime.prepare_run(mission.mission_id, workflow_id=WORKFLOW_ID, defer_acg_planning=True)
    return run


def drive_initial_chain(runtime, agent, *, stop_at="permit"):
    """Drive the explicit Initial chain through runtime facades only.

    stop_at: accepted | materialized | activated | handoff | permit | executed
    """
    agent.calls.clear()
    run = semantic_mission(runtime)
    keys = {name: f"assembly-{name}:{run.run_id}" for name in ("materialize", "activate", "handoff", "permit")}
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert paused.execution_state.get("planningCommitRequired") is True
    assert paused.execution_state.get("planningDeferred") is True
    assert "compiledACGPackage" not in paused.execution_state
    assert not agent.calls, "Initial acceptance must not dispatch any node"
    ledger = runtime.planning_commit_authority.store
    commit = ledger.get_by_idempotency_key("initial-planning:" + run.run_id)
    assert commit is not None
    if stop_at == "accepted":
        return {"run": run, "commit": commit, "keys": keys}
    mat = runtime.materialize_initial_commit(commit.commit_id, idempotency_key=keys["materialize"])
    assert mat.status == "MATERIALIZED_INACTIVE", mat
    if stop_at == "materialized":
        return {"run": run, "commit": commit, "materialization": mat, "keys": keys}
    prepared = runtime.prepare_graph_activation(mat.materialization_id, idempotency_key=keys["activate"])
    assert prepared.status == "ACTIVATION_PREPARED", prepared
    act = runtime.commit_graph_activation(mat.materialization_id, idempotency_key=keys["activate"])
    assert act.status == "ACTIVATED_PAUSED", act
    ready_resource(runtime, runtime.workflow_store.get_run(run.run_id))
    if stop_at == "activated":
        return {"run": run, "commit": commit, "materialization": mat, "activation": act, "keys": keys}
    handoff = runtime.prepare_graph_handoff(act.activation_id, idempotency_key=keys["handoff"])
    assert handoff.status == "STATE_PREPARED", handoff
    if stop_at == "handoff":
        return {"run": run, "commit": commit, "materialization": mat, "activation": act, "handoff": handoff, "keys": keys}
    permit = runtime.issue_execution_permit(handoff.handoff_id, idempotency_key=keys["permit"])
    assert permit.status == "ISSUED", permit
    if stop_at == "permit":
        return {"run": run, "commit": commit, "materialization": mat, "activation": act,
                "handoff": handoff, "permit": permit, "keys": keys}
    completed = asyncio.run(runtime.execute_prepared_run(run.run_id))
    # The Initial graph executes exactly once in one permitted stream.
    assert agent.calls == ["A", "B", "C"], agent.calls
    assert completed.completed_step_ids == ["A", "B", "C"], completed.completed_step_ids
    return {"run": run, "commit": commit, "materialization": mat, "activation": act,
            "handoff": handoff, "permit": permit, "keys": keys}


def test_initial_execution_requires_permit_through_production_assembly(tmp_path):
    runtime, agent = build(prepared_folder(tmp_path))
    try:
        # Accepted -> materialized -> ACTIVATED_PAUSED; no permit anywhere yet.
        state = drive_initial_chain(runtime, agent, stop_at="activated")
        run_id, act = state["run"].run_id, state["activation"]
        activated = runtime.workflow_store.get_run(run_id)
        assert activated.execution_state["graphActivation"]["executionPermit"] is None
        with pytest.raises(ValueError):
            asyncio.run(runtime.execute_prepared_run(run_id))
        assert not agent.calls
        handoff = runtime.prepare_graph_handoff(act.activation_id, idempotency_key=state["keys"]["handoff"])
        assert handoff.status == "STATE_PREPARED", handoff
        permit = runtime.issue_execution_permit(handoff.handoff_id, idempotency_key=state["keys"]["permit"])
        assert permit.status == "ISSUED", permit
        replay = runtime.issue_execution_permit(handoff.handoff_id, idempotency_key=state["keys"]["permit"])
        assert replay.status == "IDEMPOTENT_REPLAY" and replay.permit_id == permit.permit_id
        assert runtime.issue_execution_permit(handoff.handoff_id, idempotency_key="other").status == "REJECTED"
        # Only the formal permit unlocks execution; settled nodes never rerun.
        completed = asyncio.run(runtime.execute_prepared_run(run_id))
        assert agent.calls == ["A", "B", "C"] and completed.completed_step_ids == ["A", "B", "C"]
        asyncio.run(runtime.execute_prepared_run(run_id))
        assert agent.calls == ["A", "B", "C"]
        receipts = runtime.execution_value_store.list_node_commits(run_id=run_id)
        assert len(receipts) == 3 and all(r["stage"] == "committed" for r in receipts)
    finally:
        from app.execution.wiring import close_runtime
        close_runtime(runtime)


def test_restart_recovery_restores_authorities_without_implicit_dispatch(tmp_path, monkeypatch):
    folder = prepared_folder(tmp_path)
    runtime, agent = build(folder)
    from app.execution.wiring import close_runtime
    try:
        executed = drive_initial_chain(runtime, agent, stop_at="executed")
        paused_chain = drive_initial_chain(runtime, agent, stop_at="activated")
    finally:
        close_runtime(runtime)

    runtime, agent = build(folder)
    try:
        # Historical authorization records are recovered from disk, not memory.
        permit_store = runtime.execution_permit_authority.store
        stored = permit_store.get_permit(executed["permit"].permit_id)
        assert stored is not None and stored.status == "ISSUED"
        replay = runtime.issue_execution_permit(
            executed["handoff"].handoff_id, idempotency_key=executed["keys"]["permit"])
        assert replay.status == "IDEMPOTENT_REPLAY" and replay.permit_id == stored.permit_id

        # Startup recovery does not dispatch an ACTIVATED_PAUSED Run, and the
        # paused Run still refuses execution exactly as before the restart.
        paused_run_id = paused_chain["run"].run_id
        asyncio.run(runtime.close_orphaned_runs())
        paused = runtime.workflow_store.get_run(paused_run_id)
        assert paused.execution_state["graphActivation"]["executionPermit"] is None
        assert paused.status not in {"completed", "failed", "cancelled"}
        with pytest.raises(ValueError):
            asyncio.run(runtime.execute_prepared_run(paused_run_id))
        assert not agent.calls

        # Settled nodes are never re-executed after the restart.
        asyncio.run(runtime.execute_prepared_run(executed["run"].run_id))
        assert agent.calls == []

        # A PREPARING permit (checkpoint promotion interrupted) converges to
        # ISSUED with the same idempotency key on the restarted assembly.
        cut = drive_initial_chain(runtime, agent, stop_at="handoff")
        with monkeypatch.context() as patch:
            def interrupt(*args, **kwargs):
                raise RuntimeError("checkpoint promotion interrupted")
            patch.setattr(runtime.checkpoint_store, "save_promoted", interrupt)
            interrupted = runtime.issue_execution_permit(
                cut["handoff"].handoff_id, idempotency_key=cut["keys"]["permit"])
        # The saga keeps its PREPARING record and answers STORAGE_UNAVAILABLE;
        # reconciling with the original key is the only sanctioned retry.
        assert interrupted.status == "REJECTED", interrupted
        assert getattr(interrupted.code, "value", interrupted.code) == "STORAGE_UNAVAILABLE", interrupted
        half = permit_store.permit_by_key(cut["keys"]["permit"])
        assert half is not None and half.status == "PREPARING", half
        converged = runtime.issue_execution_permit(
            cut["handoff"].handoff_id, idempotency_key=cut["keys"]["permit"])
        assert converged.status == "ISSUED", converged
        asyncio.run(runtime.execute_prepared_run(cut["run"].run_id))
        assert agent.calls == ["A", "B", "C"]
        assert len(runtime.execution_value_store.list_node_commits(run_id=cut["run"].run_id)) == 3

        # Unknown side effects in the value ledger block a permitted Run from
        # starting; the pause itself never dispatches anything.
        paused_handoff = runtime.prepare_graph_handoff(
            paused_chain["activation"].activation_id, idempotency_key=paused_chain["keys"]["handoff"])
        assert paused_handoff.status == "STATE_PREPARED", paused_handoff
        paused_permit = runtime.issue_execution_permit(
            paused_handoff.handoff_id, idempotency_key=paused_chain["keys"]["permit"])
        assert paused_permit.status == "ISSUED", paused_permit
        with sqlite3.connect(folder / "AGENTOS_EXECUTION_VALUE_DB.sqlite") as conn:
            conn.execute(
                "INSERT INTO acg_node_executions(operation_id, run_id, payload_json, phase) VALUES(?,?,?,?)",
                ("unexplained-operation", paused_run_id, "{}", "started"))
        with pytest.raises(ValueError, match="unexplained execution operations"):
            asyncio.run(runtime.execute_prepared_run(paused_run_id))
        # The blocked Run dispatched nothing; the calls are still exactly the
        # settled cut-chain execution from above.
        assert agent.calls == ["A", "B", "C"]
    finally:
        close_runtime(runtime)


def test_legacy_runs_execute_without_authorities_when_c2_is_off(tmp_path):
    # A separate folder that no operator ever upgraded: exactly today's shape.
    folder = tmp_path / "legacy"
    runtime, agent = build(folder, semantic=False, c2=False)
    from app.execution.wiring import close_runtime
    try:
        for attribute in ("planning_commit_authority", "graph_materialization_authority",
                          "graph_activation_authority", "graph_handoff_authority",
                          "execution_permit_authority"):
            assert getattr(runtime, attribute) is None
        assert runtime.mission_semantic_service is None
        mission = runtime.create_mission("兼容路径合同审查", workflow_id=WORKFLOW_ID, input={
            "contractText": CONTRACT,
            "authenticatedUserId": OWNER.actor_id,
            "authenticatedTenantId": OWNER.tenant_id,
            "deterministicIntent": True,
        })
        _, prepared = runtime.prepare_run(mission.mission_id, workflow_id=WORKFLOW_ID, defer_acg_planning=True)
        assert prepared.execution_state.get("planningCommitRequired") is None
        result = asyncio.run(runtime.execute_prepared_run(prepared.run_id))
        # Legacy coexistence: the very same Run record shape executes directly,
        # with no activation projection anywhere in its execution state.  This
        # path is only reachable while the C2 switch is off; an activated Run
        # (graphActivation present) never takes it, with or without authorities.
        assert "graphActivation" not in result.execution_state
        assert "A" in agent.calls
        assert "compiledACGPackage" in result.execution_state
        with sqlite3.connect(folder / "workflow.sqlite") as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables & ops.C2_TABLES
    finally:
        close_runtime(runtime)
