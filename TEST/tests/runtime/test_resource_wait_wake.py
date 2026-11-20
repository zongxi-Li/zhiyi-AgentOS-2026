"""Resource facts can wake a plain workspace wait without inventing waitFor."""

import asyncio

import pytest

from contracts.runtime_planning import RuntimePlanningDecision
from contracts.workflow import StepStatus, WorkflowStatus
from runtime.orchestration.state_persistence import acg_execution_state_from_run
from TEST.tests.runtime.test_planning_loop import Planner, PowerLoss, attach, prepared, runtime_at
from TEST.tests.runtime.test_resource_planning import ModelAdapter, endpoint, resource_plane


def plain_workspace_wait(tmp_path, *, owner_input=None):
    runtime, agent, run = prepared(tmp_path, resource_plane=resource_plane(tmp_path), input={
        **(owner_input or {}),
        "workspaceBinding": {"workspaceId": "fixture", "grantId": "grant"},
        "workspaceObservations": [{"path": ".", "kind": "directory", "operation": "read"}],
    })
    run.execution_state["bindingRequirements"]["B"]["model"] = {
        "requiredFeatures": ["json_schema"], "minContextTokens": 8000,
    }
    runtime.workflow_store.save_run(run)

    def choose(observation, plan):
        restored = any(fact.step_id == "B" and fact.ready for fact in observation.resource_requirements)
        return RuntimePlanningDecision(observationId=observation.fingerprint(), action="wait",
            reason="review restored resources" if restored else "missing compatible resource",
            question={"prompt": "Review restored resources before changing the plan?"} if restored else None)

    planner = Planner(choose)
    attach(runtime, planner)
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A"]
    assert paused.execution_state["planningLoop"]["waiting"] is None
    assert not planner.observations[0].resource_requirements[0].ready
    return runtime, agent, paused, planner


def test_plain_resource_wait_reobserves_after_restart_without_reexecuting_committed_work(tmp_path):
    runtime, agent, paused, planner = plain_workspace_wait(tmp_path, owner_input={
        "authenticatedUserId": "reviewer", "authenticatedTenantId": "tenant-a",
    })
    assert runtime.workflow_store.list_runs().total == 0
    assert runtime.workflow_store.list_runs(owner_user_id="reviewer", owner_tenant_id="tenant-a").total == 1
    assert runtime.workflow_store.list_runs(owner_user_id="reviewer", owner_tenant_id="tenant-b").total == 0
    assert runtime.workflow_store.list_runs(owner_user_id="other", owner_tenant_id="tenant-a").total == 0
    original_checkpoint = paused.execution_state["checkpointId"]
    original_decision = paused.execution_state["planningLoop"]["current"]["decision"]
    output_ref = paused.execution_state["outputRefs"]["A"]
    assert asyncio.run(runtime.prepare_planning_wakeups()) == []
    assert len(planner.observations) == 1

    recovered, agent2 = runtime_at(tmp_path, resource_plane=resource_plane(tmp_path))
    recovered.model_registry.register(ModelAdapter())
    recovered.resource_plane.upsert_model_endpoint(endpoint(supported=False))
    assert asyncio.run(recovered.prepare_planning_wakeups()) == []
    recovered.resource_plane.upsert_model_endpoint(endpoint())
    assert asyncio.run(recovered.prepare_planning_wakeups()) == [paused.run_id]
    ready = recovered.workflow_store.get_run(paused.run_id)
    assert ready.status == WorkflowStatus.RETRYING
    assert ready.execution_state["planningLoop"]["restartPending"] is True
    assert ready.execution_state["planningLoop"]["waiting"] is None
    assert ready.execution_state["planningLoop"]["current"]["decision"] == original_decision
    latest_id, latest = recovered.checkpoint_store.load_latest(run_id=paused.run_id)
    assert latest_id == ready.execution_state["checkpointId"] != original_checkpoint
    assert latest["reviewPayload"] is None
    assert recovered.checkpoint_store.load(run_id=paused.run_id,
        checkpoint_id=original_checkpoint)["reviewPayload"] is not None

    resumed, agent3 = runtime_at(tmp_path, resource_plane=resource_plane(tmp_path))
    resumed.model_registry.register(ModelAdapter())
    attach(resumed, planner)
    assert asyncio.run(resumed.prepare_planning_wakeups()) == [paused.run_id]
    result = asyncio.run(resumed.execute_prepared_run(paused.run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW
    assert len(planner.observations) == 2 and planner.observations[-1].resource_requirements[0].ready
    assert planner.observations[-1].condition_wake is None
    assert result.execution_state["planningLoop"]["current"]["decision"]["question"]
    assert result.execution_state["outputRefs"]["A"] == output_ref
    assert agent2.calls == agent3.calls == []
    assert "inPlaceRetryRequests" not in result.execution_state
    assert asyncio.run(resumed.prepare_planning_wakeups()) == []


@pytest.mark.parametrize("change", ["manual", "revoked", "question", "requirement", "observation", "node", "control", "head"])
def test_resource_wait_preserves_other_review_owners_and_frozen_requirements(tmp_path, change):
    runtime, agent, paused, planner = plain_workspace_wait(tmp_path)
    run = runtime.workflow_store.get_run(paused.run_id)
    if change == "manual":
        run.review_mode = "human_in_loop"
    elif change == "revoked":
        run.input["workspaceBinding"]["revoked"] = True
    elif change == "question":
        run.execution_state["planningLoop"]["current"]["decision"]["question"] = {"prompt": "Human decision?"}
    elif change == "requirement":
        run.execution_state["bindingRequirements"]["B"]["requiredCapabilities"].append("missing.capability")
    elif change == "observation":
        run.execution_state["planningLoop"]["current"]["observation"]["graphVersion"] += 1
    elif change in {"node", "control"}:
        subject = "B" if change == "node" else "fixture:control"
        run.execution_state["reviewPayload"].update(subjectType="step" if change == "node" else "control",
            subjectId=subject)
        run.current_step_id = subject
        if change == "node":
            run.get_step("B").status = StepStatus.WAITING_REVIEW
        else:
            run.acg_blueprint["nodes"].append({"nodeId": subject, "nodeType": "control"})
    else:
        state = acg_execution_state_from_run(run)
        state.output_summaries["unrelated"] = "another unfinished transition"
        runtime.acg_state_persistence.save_checkpoint(run, state)
    runtime.workflow_store.save_run(run)
    before = runtime.workflow_store.get_run(run.run_id)
    version = runtime.checkpoint_store.latest_version(run_id=run.run_id)
    runtime.resource_plane.upsert_model_endpoint(endpoint())
    assert asyncio.run(runtime.prepare_planning_wakeups()) == []
    assert runtime.workflow_store.get_run(run.run_id) == before
    assert runtime.checkpoint_store.latest_version(run_id=run.run_id) == version
    assert agent.calls == ["A"] and len(planner.observations) == 1


def test_plain_resource_wake_replays_checkpoint_ack_loss(tmp_path):
    runtime, agent, paused, planner = plain_workspace_wait(tmp_path)
    runtime.resource_plane.upsert_model_endpoint(endpoint())

    def crash():
        raise PowerLoss("after cleared wait checkpoint")

    runtime.acg_state_persistence.after_checkpoint_hook = crash
    with pytest.raises(PowerLoss):
        asyncio.run(runtime.prepare_planning_wakeups())
    committed = runtime.checkpoint_store.load_latest(run_id=paused.run_id)
    version = runtime.checkpoint_store.latest_version(run_id=paused.run_id)
    assert committed[1]["reviewPayload"] is None
    assert runtime.workflow_store.get_run(paused.run_id).status == WorkflowStatus.WAITING_REVIEW

    recovered, agent2 = runtime_at(tmp_path, resource_plane=resource_plane(tmp_path))
    recovered.model_registry.register(ModelAdapter())
    assert asyncio.run(recovered.prepare_planning_wakeups()) == [paused.run_id]
    assert recovered.checkpoint_store.load_latest(run_id=paused.run_id) == committed
    assert recovered.checkpoint_store.latest_version(run_id=paused.run_id) == version
    assert recovered.workflow_store.get_run(paused.run_id).execution_state["checkpointId"] == committed[0]
    assert agent.calls == ["A"] and agent2.calls == [] and len(planner.observations) == 1


def test_cleared_wait_checkpoint_advances_head_even_when_body_already_exists(tmp_path):
    runtime, agent, paused, planner = plain_workspace_wait(tmp_path)
    state = acg_execution_state_from_run(paused)
    state.review_payload = None
    historical_id = runtime.acg_state_persistence.save_checkpoint(paused, state)
    # An earlier occurrence of the same state body must not become today's head.
    barrier = acg_execution_state_from_run(paused)
    barrier.checkpoint_id = "fixture:later-planner-barrier"
    runtime.checkpoint_store.save(run_id=paused.run_id, checkpoint_id=barrier.checkpoint_id,
        state=barrier.model_dump(by_alias=True, mode="json"))
    paused.execution_state.update(barrier.model_dump(by_alias=True, mode="json"))
    runtime.workflow_store.save_run(paused)
    version = runtime.checkpoint_store.latest_version(run_id=paused.run_id)
    runtime.resource_plane.upsert_model_endpoint(endpoint())
    assert asyncio.run(runtime.prepare_planning_wakeups()) == [paused.run_id]
    latest_id, latest = runtime.checkpoint_store.load_latest(run_id=paused.run_id)
    assert latest_id != historical_id and latest["reviewPayload"] is None
    assert runtime.checkpoint_store.latest_version(run_id=paused.run_id) == version + 1
