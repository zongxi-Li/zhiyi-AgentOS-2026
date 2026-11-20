"""Graph handoff remains readable without borrowing a parent graph's admission."""
import asyncio
import sqlite3

import pytest

from contracts import stable_checksum
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.workflow import WorkflowStatus
from app.security.internal_auth import current_semantic_principal
from support.stores.execution_dispatch_store import DispatchCommand, SQLiteExecutionDispatchStore
from test_agentos_formal_recovery import HttpHarness, PREFIX, trusted_call
from test_agentos_formal_recovery import ready_handoff, recovery_seed  # noqa: F401 - shared durable fixtures
from TEST.tests.components.planner.test_graph_handoff_generation import activate_next_graph
from TEST.tests.components.planner.test_planning_commit_runtime import dump_databases


@pytest.fixture
def transitioning_graph(ready_handoff):  # noqa: F811
    runtime, store, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    issued = runtime.issue_execution_permit(handoff_id, idempotency_key="projection-parent-permit")
    assert issued.status == "ISSUED", issued
    SQLiteExecutionDispatchStore.upgrade_schema(store.db_path)
    dispatches = SQLiteExecutionDispatchStore(store.db_path)
    runtime.execution_dispatch_store = dispatches
    source = store.get_run(run_id)
    principal = runtime.semantic_principal_provider()
    command = DispatchCommand(dispatch_id="dispatch:projection-parent", operation_key="projection-parent",
        request_fingerprint="projection-parent", mission_id=source.mission_id, run_id=run_id,
        permit_id=issued.permit_id, graph_id=source.execution_state["graphId"],
        graph_version=source.execution_state["graphVersion"], runtime_revision=source.runtime_revision,
        actor_id=principal.actor_id, tenant_id=principal.tenant_id)
    dispatches.accept(command, runtime.execution_permit_authority.assert_dispatchable)

    class Pause:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="wait" if any(step.step_id == "B" and step.status == "completed"
                                     for step in observation.steps) else "continue",
                reason="Inspect the graph transition projection")

    runtime.runtime_planning_coordinator.planner_for_run = lambda _: Pause()
    boundary = runtime.runtime_planning_coordinator.boundary

    async def observe(run, state, reason):
        return await boundary(run, state, "resume" if "B" in state.completed_step_ids else reason)

    runtime.runtime_planning_coordinator.boundary = observe
    paused = asyncio.run(runtime.execute_prepared_run(run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW, (paused.status, paused.error)
    assert paused.completed_step_ids == ["A", "B"] and agent.calls == ["B"]
    activation_id = activate_next_graph(runtime, paused, key="projection-next-graph")
    runtime.execution_dispatch_enabled = True
    runtime.semantic_principal_provider = current_semantic_principal
    store.enable_existing_mission_semantics()
    client = HttpHarness(runtime)
    try:
        yield client, runtime, store, agent, command, activation_id
    finally:
        client.close()


def read_control(client, store, run_id):
    before = dump_databases(store, include_ledger=True)
    response = client.get(PREFIX + "/runs/" + run_id)
    assert response.status_code == 200, response.text
    assert dump_databases(store, include_ledger=True) == before
    return response.json()["formalControl"]


def test_handoff_projection_tracks_current_dispatch_across_durable_stages(transitioning_graph):
    client, runtime, store, agent, parent, activation_id = transitioning_graph
    paused = read_control(client, store, parent.run_id)
    assert paused["graphVersion"] == parent.graph_version + 1
    assert paused["status"] == "ACTIVATED_PAUSED" and paused["dispatch"] is None
    assert not paused["permitIssued"] and not paused["executionAuthorized"]

    handoff = trusted_call(client, lambda: runtime.prepare_graph_handoff(activation_id,
        idempotency_key="projection-next-handoff"))
    assert handoff.status == "STATE_PREPARED", handoff
    permit = trusted_call(client, lambda: runtime.issue_execution_permit(handoff.handoff_id,
        idempotency_key="projection-next-permit"))
    assert permit.status == "ISSUED", permit
    permitted = read_control(client, store, parent.run_id)
    assert permitted["permitIssued"] and permitted["dispatchEligible"]
    assert permitted["dispatch"] is None and not permitted["executionAuthorized"]

    run = store.get_run(parent.run_id)
    command = parent.model_copy(update={"dispatch_id": "dispatch:projection-next",
        "operation_key": "projection-next", "request_fingerprint": "projection-next",
        "permit_id": permit.permit_id, "graph_version": run.execution_state["graphVersion"],
        "runtime_revision": run.runtime_revision})
    trusted_call(client, lambda: runtime.execution_dispatch_store.accept_continuation(command, parent,
        runtime.execution_permit_authority.assert_dispatchable))
    admitted = read_control(client, store, parent.run_id)
    assert admitted["dispatch"] == command.public() and admitted["executionAuthorized"]
    assert agent.calls == ["B"]


@pytest.mark.parametrize("damage", ["unrelated_graph", "unproved_permit", "corrupt_permit"])
def test_handoff_projection_rejects_unproved_historical_admission(transitioning_graph, damage):
    client, runtime, store, agent, parent, _ = transitioning_graph
    with sqlite3.connect(store.db_path) as conn:
        if damage == "corrupt_permit":
            conn.execute("UPDATE graph_execution_permits SET checksum=? WHERE permit_id=?",
                         ("0" * 64, parent.permit_id))
        else:
            changed = parent.model_copy(update={"graph_version": parent.graph_version - 1}
                if damage == "unrelated_graph" else {"permit_id": "permit:unproved"})
            conn.execute("UPDATE execution_dispatch_commands SET payload=?,checksum=? WHERE run_id=?",
                         (changed.model_dump_json(), stable_checksum(changed), parent.run_id))
    before = dump_databases(store, include_ledger=True)
    response = client.get(PREFIX + "/runs/" + parent.run_id)
    assert response.status_code == 503
    assert "checksum" not in response.text and "actor_id" not in response.text
    assert dump_databases(store, include_ledger=True) == before and agent.calls == ["B"]
