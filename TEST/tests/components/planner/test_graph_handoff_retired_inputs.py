"""Retired pending producers remain authenticated historical handoff sources."""

import pytest

from contracts.planning import TaskPlanPatch, TaskPlanRelation
from contracts.runtime_planning import RuntimePlanningRound, RuntimePlanningState
from domain.repository.errors import IdentityConflictError
from runtime.orchestration.state_persistence import acg_execution_state_from_run
from TEST.tests.components.planner.test_execution_permit import ready_handoff


def retired_predecessor_activation(ready_handoff):
    rt, workflow, agent, run_id, _, ledger, staged, _, handoff_id = ready_handoff
    issued = rt.issue_execution_permit(handoff_id, idempotency_key="before-retirement")
    assert issued.status == "ISSUED", issued
    run = workflow.get_run(run_id)
    observation = rt.runtime_planning_coordinator.observe(run, acg_execution_state_from_run(run), "resume")
    run.execution_state["planningLoop"] = RuntimePlanningState(current=RuntimePlanningRound(
        observationId=observation.fingerprint(), observation=observation)).model_dump(by_alias=True, mode="json")
    workflow.save_run(run)
    source_steps = {step.step_id: step.model_copy(deep=True) for step in run.steps}
    assert set(source_steps) == {"A", "B", "C", "D"}
    assert "C" in source_steps["D"].input["from"]
    patch = TaskPlanPatch(missionId=run.mission_id, basePlanVersion=2, planVersion=3,
        retireKeys=("step:B", "step:C"),
        relations=(TaskPlanRelation(sourceKey="step:A", targetKey="step:D", relationType="depends_on"),))
    with rt.run_lock_manager.lock_for(run_id):
        source = rt.planning_commit_authority.accept_patch_locked(run_id, patch,
            proposal_id="retire-producers", idempotency_key="retire-producers")
    assert source.status == "ACCEPTED", source
    graph = rt.accept_graph_revision(run_id, source.commit_id, idempotency_key="retire-producers-graph")
    assert graph.status == "ACCEPTED", graph
    materialized = rt.materialize_graph_revision(graph.commit_id, idempotency_key="retire-producers-materialize")
    assert materialized.status == "MATERIALIZED_INACTIVE", materialized
    prepared = rt.prepare_graph_activation(materialized.materialization_id, idempotency_key="retire-producers-activate")
    assert prepared.status == "ACTIVATION_PREPARED", prepared
    activation = rt.commit_graph_activation(materialized.materialization_id, idempotency_key="retire-producers-activate")
    assert activation.status == "ACTIVATED_PAUSED", activation
    activated = workflow.get_run(run_id)
    assert {step.step_id for step in activated.steps} == {"A", "D"}
    assert activated.steps[0] == source_steps["A"]
    assert set(activated.steps[1].input["from"]) == {"A"}
    return rt, workflow, agent, run_id, activation.activation_id, ledger, staged, source_steps


@pytest.mark.parametrize("restart", [False, True])
def test_retired_producers_and_rewired_pending_input_handoff_preserve_completed_prefix(ready_handoff, restart):
    rt, workflow, agent, run_id, activation, ledger, staged, source_steps = retired_predecessor_activation(ready_handoff)
    if restart:
        from TEST.tests.components.planner.test_permit_recovery import _open

        definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
        rt, workflow, restored_agent = _open(workflow.db_path.parent, definition)
        restored_agent.calls.extend(agent.calls)
        agent = restored_agent
        ledger, staged = rt.graph_handoff_authority.store, rt.graph_handoff_authority.staged_store
    before = workflow.get_run(run_id)
    receipts = rt.execution_value_store.list_node_commits(run_id=run_id)
    result = rt.prepare_graph_handoff(activation, idempotency_key="retired-input-handoff")
    assert result.status == "STATE_PREPARED", result
    record = ledger.get_handoff(result.handoff_id)
    assert staged.get(record.candidate.checkpoint_id) == record.candidate
    assert record.candidate.state["completedStepIds"] == ["A"]
    assert record.candidate.state["outputRefs"] == before.execution_state["outputRefs"]
    assert workflow.get_run(run_id) == before and agent.calls == ["A"]
    permit = rt.issue_execution_permit(result.handoff_id, idempotency_key="retired-input-permit")
    assert permit.status == "ISSUED", permit
    promoted = workflow.get_run(run_id)
    assert {step.step_id for step in promoted.steps} == {"A", "D"}
    assert promoted.steps[0] == source_steps["A"]
    assert promoted.completed_step_ids == ["A"]
    assert rt.execution_value_store.list_node_commits(run_id=run_id) == receipts and agent.calls == ["A"]


@pytest.mark.parametrize("damage", ["unauthorized", "attempted"])
def test_identity_retirement_requires_exact_authorization_and_unattempted_work(ready_handoff, damage):
    from types import SimpleNamespace

    rt, workflow, agent, run_id, activation, ledger, _, _ = retired_predecessor_activation(ready_handoff)
    proposal = rt.planning_commit_authority.store.get(ledger.get_activation(activation).source_commit_id).proposal_payload
    candidate = proposal.candidate_graph.model_copy(deep=True)
    retired = ()
    lifecycle = rt.identity_lifecycle
    if damage == "attempted":
        from domain.models import Attempt

        identity = lifecycle.repositories.runs.get(run_id)
        binding = lifecycle.repositories.task_bindings.find_for_acg_node("B", identity.blueprint_id)[0]
        lifecycle.repositories.attempts.add(Attempt(runId=run_id, taskId=binding.task_id, attemptNumber=1))
        retired = ("B", "C")
    before = lifecycle.repositories.runs.get(run_id)
    before_plan = lifecycle.repositories.task_plans.latest(before.mission_id)
    with pytest.raises(IdentityConflictError, match="accepted retirement|attempted or unbound"):
        lifecycle.on_execution_permit_blueprint_promoted(
            SimpleNamespace(run_id=run_id, mission_id=before.mission_id), candidate,
            proposal.next_plan, proposal.next_bindings, "unauthorized-retirement",
            retired_node_ids=retired)
    assert lifecycle.repositories.runs.get(run_id) == before
    assert lifecycle.repositories.task_plans.latest(before.mission_id) == before_plan
    assert agent.calls == ["A"]


@pytest.mark.parametrize("crash", ["before_identity", "after_identity"])
def test_retirement_projection_journal_replays_across_permit_restart(ready_handoff, monkeypatch, crash):
    from TEST.tests.components.planner.test_permit_recovery import _open

    rt, workflow, agent, run_id, activation, _, _, _ = retired_predecessor_activation(ready_handoff)
    result = rt.prepare_graph_handoff(activation, idempotency_key="retirement-replay-handoff")
    assert result.status == "STATE_PREPARED", result
    lifecycle = rt.identity_lifecycle
    promote = lifecycle._promote_execution_permit_identity

    def interrupted(*args, **kwargs):
        if crash == "after_identity":
            promote(*args, **kwargs)
        raise RuntimeError("simulated interruption during retirement projection")

    monkeypatch.setattr(lifecycle, "_promote_execution_permit_identity", interrupted)
    failed = rt.issue_execution_permit(result.handoff_id, idempotency_key="retirement-replay-permit")
    assert failed.status == "REJECTED", failed
    pending = rt.execution_permit_authority.store.permit_by_key("retirement-replay-permit")
    assert pending is not None and pending.status == "PREPARING"
    event_id = "execution.permit.identity:" + pending.permit_id
    event = lifecycle.repositories.projection_events.get(event_id)
    assert set(event.payload["retiredNodeIds"]) == {"B", "C"}
    definition = rt._workflow_for_run(workflow.get_run(run_id)).model_dump(mode="json", by_alias=True)
    restored, restored_workflow, restored_agent = _open(workflow.db_path.parent, definition)
    restored_agent.calls.extend(agent.calls)
    replay = restored.identity_lifecycle.replay_unapplied()
    assert replay["failed"] == 0 and replay["applied"] >= 1
    issued = restored.issue_execution_permit(result.handoff_id, idempotency_key="retirement-replay-permit")
    assert issued.status == "ISSUED", issued
    assert restored_workflow.get_run(run_id).completed_step_ids == ["A"]
    assert restored_agent.calls == ["A"]
