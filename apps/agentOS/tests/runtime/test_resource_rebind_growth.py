"""Recovery exhausts exact registered candidates, not an arbitrary retry quota."""
import asyncio
from copy import deepcopy

import pytest

from contracts.resource import ExecutionRequirement
from contracts.workflow import ReviewDecision, ReviewDecisionType
from runtime.binding import requirements_match_manifest
from runtime.runtime_recovery import ResourceNotFoundError
from service.agents import AgentRegistry
from test_graph_patch import _Agent, _runtime


def test_repeated_rebind_exhausts_candidates_and_allows_a_fresh_registration_generation(tmp_path):
    calls = []
    agents = AgentRegistry()
    reviewer = _Agent()
    reviewer.profile.capabilities = ["task_understanding"]
    agents.register(reviewer)
    primary = _Agent("primary", "primary", calls, 10)
    agents.register(primary)
    agents.register(_Agent("alternate-a", "alternate-a", calls, 5))
    agents.register(_Agent("alternate-b", "alternate-b", calls, 2))
    runtime, lifecycle = _runtime(tmp_path, identity=True, agents=agents)
    try:
        mission = runtime.create_mission("rebind until a new candidate is available", workflow_id="patchable")
        paused = asyncio.run(runtime.start(mission.mission_id, workflow_id="patchable"))
        paused.execution_state["resourceBindings"]["deliver"] = "primary"
        runtime.workflow_store.save_run(paused)
        original_graph = paused.execution_state["graphVersion"]
        original_plan = deepcopy(paused.execution_state["taskPlan"])
        assert asyncio.run(runtime.rebind_step(run_id=paused.run_id, step_id="deliver", reason="primary unavailable")) == "alternate-a"
        assert asyncio.run(runtime.rebind_step(run_id=paused.run_id, step_id="deliver", reason="first alternate unavailable")) == "alternate-b"
        exhausted = runtime.workflow_store.get_run(paused.run_id)
        requirement = ExecutionRequirement.model_validate(exhausted.execution_state["bindingRequirements"]["deliver"])
        assert len(exhausted.execution_state["bindingHistory"]) == 2 and len(requirement.excluded_runtime_ids) == 2
        # A later global registration cannot broaden this Run's frozen scope.
        agents.register(_Agent("outside", "outside", calls, 100))
        runtime.runtime_binding_service.agent_pool.synchronize()
        with pytest.raises(ResourceNotFoundError, match="no healthy alternate"):
            asyncio.run(runtime.rebind_step(run_id=paused.run_id, step_id="deliver", reason="all old candidates unavailable"))
        assert runtime.workflow_store.get_run(paused.run_id).model_dump() == exhausted.model_dump()
        old = agents.registration_for(primary)
        fresh = runtime.runtime_binding_service.agent_pool.register_instance(
            _Agent("primary", "primary", calls, 10), instance_id=old.instance_id, expected_generation=old.generation)
        runtime.runtime_binding_service.agent_pool.heartbeat(fresh)
        assert fresh.agent_id == old.agent_id and fresh.resource_id != old.resource_id
        assert asyncio.run(runtime.rebind_step(run_id=paused.run_id, step_id="deliver", reason="fresh generation is available")) == "primary"
        rebound = runtime.workflow_store.get_run(paused.run_id)
        requirement = ExecutionRequirement.model_validate(rebound.execution_state["bindingRequirements"]["deliver"])
        assert old.resource_id in requirement.excluded_runtime_ids and fresh.resource_id not in requirement.excluded_runtime_ids
        assert len(rebound.execution_state["bindingHistory"]) == 3
        assert rebound.execution_state["graphVersion"] == original_graph and rebound.execution_state["taskPlan"] == original_plan
        asyncio.run(runtime.apply_review(ReviewDecision(runId=paused.run_id, stepId="review",
            decision=ReviewDecisionType.APPROVED, operationId="approve-fresh-generation")))
        assert calls == ["primary"]
    finally:
        lifecycle.close()


def test_reviewed_failure_isolation_may_only_add_exclusions_to_a_compiled_requirement():
    expected = {"step": ExecutionRequirement(requiredCapabilities=["analysis"],
        excludedRuntimeIds=["blocked-by-policy"]).model_dump(by_alias=True, mode="json")}
    actual = deepcopy(expected)
    actual["step"]["excludedRuntimeIds"].append("failed-registration")
    actual["step"]["preferences"] = {"agentRole": "new-candidate"}
    assert requirements_match_manifest(actual, expected)
    actual["step"]["excludedRuntimeIds"].remove("blocked-by-policy")
    assert not requirements_match_manifest(actual, expected)
    actual = deepcopy(expected)
    actual["step"]["requiredCapabilities"] = ["different-capability"]
    assert not requirements_match_manifest(actual, expected)
