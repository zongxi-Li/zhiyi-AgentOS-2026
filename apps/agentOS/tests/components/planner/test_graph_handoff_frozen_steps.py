"""Formal initial compilation preferences survive local graph revision."""
import asyncio

import pytest

from contracts.runtime_planning import RuntimePlanningDecision
from contracts.workflow import WorkflowStatus
from runtime.graph_step_projection import restore_initial_source_steps
from test_graph_handoff_generation import activate_next_graph
from test_horizon import ready_boundary as ready_boundary, runtime_boundary as runtime_boundary
from test_initial_planning_sources import initial_run as initial_run
from test_initial_execution_permit import prepared_initial


@pytest.mark.parametrize("legacy_overlay", [False, True])
def test_explicit_run_reasoning_cannot_rewrite_frozen_initial_steps_during_revision(initial_run, monkeypatch, legacy_overlay):
    from support.acg.schema import RuntimeBlueprintSpec

    rt, workflow, agent, run, _ = initial_run
    # This preference is frozen as business input, while the formal compiler
    # chooses the step inputs from its sealed blueprint.
    run.input["reasoningEffort"] = "high"
    workflow.save_run(run)
    rt, workflow, agent, prepared, _, handoff = prepared_initial((rt, workflow, agent, run, initial_run[4]))
    if prepared.input.get("reasoningEffort") != "high":
        pytest.fail("fixture must retain explicit reasoning before initial acceptance")
    issued = rt.issue_execution_permit(handoff, idempotency_key="initial-frozen-permit")
    assert issued.status == "ISSUED", issued

    class Pause:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="wait" if any(step.status == "completed" for step in observation.steps) else "continue",
                reason="inspect frozen initial inputs")

    rt.runtime_planning_coordinator.planner_for_run = lambda _: Pause()
    boundary = rt.runtime_planning_coordinator.boundary

    async def observe(current, state, reason):
        return await boundary(current, state, "resume" if state.completed_step_ids else reason)

    rt.runtime_planning_coordinator.boundary = observe
    paused = asyncio.run(rt.execute_prepared_run(prepared.run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW, paused.status
    original_steps = {step.step_id: step.model_copy(deep=True) for step in paused.steps}
    assert all(step.input.get("reasoningPolicyReason") != "run_explicit" for step in paused.steps)
    old = RuntimeBlueprintSpec.model_validate(paused.acg_blueprint)
    source_view = paused.model_copy(deep=True)
    # Simulate an already activated legacy projection only in the temporary
    # validation view. Execution history and business input must survive.
    rt._sync_run_steps_to_acg(source_view, old)
    assert any(step.input.get("reasoningPolicyReason") == "run_explicit" for step in source_view.steps)
    restore_initial_source_steps(rt, source_view, old)
    assert source_view.steps == list(original_steps.values())
    assert source_view.input == paused.input
    unexplained = source_view.model_copy(deep=True)
    rt._sync_run_steps_to_acg(unexplained, old)
    unexplained.steps[0].input["unacceptedInput"] = "must remain visible to the source hash"
    unexplained.steps[0].goal = "unaccepted goal"
    restore_initial_source_steps(rt, unexplained, old)
    assert unexplained.steps[0].input["unacceptedInput"]
    assert unexplained.steps[0].goal == "unaccepted goal"
    if legacy_overlay:
        activate = rt.graph_activation_authority._activated_run

        def previous_recipe(*args):
            activated = activate(*args)
            rt._sync_run_steps_to_acg(activated, RuntimeBlueprintSpec.model_validate(activated.acg_blueprint))
            return activated

        monkeypatch.setattr(rt.graph_activation_authority, "_activated_run", previous_recipe)
    activation = activate_next_graph(rt, paused, key="frozen-revision", node="B", predecessor=paused.steps[-1].step_id)
    activated = workflow.get_run(prepared.run_id)
    if not legacy_overlay:
        assert [step for step in activated.steps if step.step_id in original_steps] == list(original_steps.values())
        assert activated.steps[-1].input.get("reasoningPolicyReason") != "run_explicit"
        authority = rt.graph_activation_authority
        record = authority.store.get_activation(activation)
        materialization = rt.graph_materialization_authority.store.get_materialization(record.materialization_id)
        rebound = rt.planning_commit_authority.store.get(record.source_commit_id).model_copy(deep=True)
        rebound.proposal_payload.candidate_graph.resource_plan.bindings[0].planned_agent_id = "changed-agent"
        projection = authority._activated_run(paused, materialization, rebound, record)
        assert projection.steps[0].agent_name == "changed-agent"
    result = rt.prepare_graph_handoff(activation, idempotency_key="frozen-handoff")
    assert result.status == "STATE_PREPARED", result
    assert workflow.get_run(prepared.run_id) == activated
    permit = rt.issue_execution_permit(result.handoff_id, idempotency_key="frozen-revision-permit")
    assert permit.status == "ISSUED", permit
    assert agent.calls == ["A"]
