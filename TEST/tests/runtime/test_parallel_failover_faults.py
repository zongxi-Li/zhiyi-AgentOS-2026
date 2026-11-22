"""Transparent remote failover cannot replay an independently failed sibling."""

import asyncio

import pytest

from adapters.agent.resource_execution import ResourceExecutionError
from components.executor.value_store import ExecutionValueAccessError
from contracts.planning import PlannedTask
from contracts.resource import Placement, ResourceEndpoint, RuntimeProfile, RuntimeSnapshot, TrustLevel
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.tools import HostToolExecutionError
from contracts.workflow import StepStatus, WorkflowDefinition, WorkflowStatus, WorkflowStepDefinition
from TEST.tests.runtime.test_planning_loop import Agent, Planner, attach, prepared


@pytest.mark.parametrize("sibling_failure", ["policy", "storage", "contract", "hands_unknown"])
def test_parallel_remote_failover_preserves_independent_sibling_fault(tmp_path, sibling_failure):
    entered = asyncio.Event()

    class LocalAgent(Agent):
        async def run(self, context):
            self.calls.append(context.step.step_id)
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                if sibling_failure in {"policy", "hands_unknown"}:
                    code = "EXECUTION_AUTHORIZATION_LOST" if sibling_failure == "policy" else "HANDS_OUTCOME_UNKNOWN"
                    raise HostToolExecutionError(code, "tool authority or settlement unavailable",
                        details={"stepId": context.step.step_id, "attemptId": context.attempt_id,
                            "commitId": context.commit_id, "tool": "fs.read", "resourceId": "hands"})
                if sibling_failure == "storage":
                    raise ExecutionValueAccessError("artifact ledger unavailable")
                raise ValueError("independent output contract failure")

    workflow = WorkflowDefinition(workflowId="seq", name="parallel faults", domain="general", runtimeEngine="acg",
        planningNodes=tuple(PlannedTask(key=f"step:{step}", title=step, objective=f"do {step}") for step in ("A", "B")),
        steps=tuple(WorkflowStepDefinition(stepId=step, name=step, agentName="runner") for step in ("A", "B")))
    runtime, agent, run = prepared(tmp_path, LocalAgent(), workflow)
    plane = runtime.resource_plane
    plane.ensure_node("node:edge", placement=Placement.CLOUD, trust=TrustLevel.HOST_TRUSTED)
    capabilities = sorted({capability for requirement in run.execution_state["bindingRequirements"].values()
        for capability in requirement["requiredCapabilities"]})
    plane.register_remote_runtime(RuntimeProfile(runtimeId="edge", nodeId="node:edge", placement=Placement.CLOUD,
        capabilities=capabilities, trust=TrustLevel.TRUSTED,
        endpoint=ResourceEndpoint(protocol="http", address="http://edge.invalid/execute"), ownerScope="fixture"),
        RuntimeSnapshot(runtimeId="edge", availableSlots=1, utilization=0))
    plane.observe_remote_runtime("edge", available_slots=1, utilization=0, latency_ms=1, observation_sequence=1)
    remote_calls = []

    class Remote:
        async def run(self, context):
            remote_calls.append(context.step.step_id)
            await entered.wait()
            raise ResourceExecutionError("remote admission rejected before execution")

    runtime.resource_execution_adapters["edge"] = Remote()
    run.execution_state["bindingRequirements"]["A"]["allowedRuntimeIds"] = ["edge"]
    run.execution_state["bindingRequirements"]["B"]["excludedRuntimeIds"] = ["edge"]
    runtime.workflow_store.save_run(run)
    planner = Planner(lambda observation, _: RuntimePlanningDecision(observationId=observation.fingerprint(),
        action="wait", reason="Preserve independent failures for Recovery"))
    attach(runtime, planner)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert result.status == WorkflowStatus.WAITING_REVIEW
    assert remote_calls == ["A"] and agent.calls == ["B"]
    assert "resourceFailoverHistory" not in result.execution_state
    assert result.recovery_count == 0
    assert all(step.status == StepStatus.FAILED and step.attempt == 0 for step in result.steps)
    assert len(result.execution_state["failureEvents"]) == 2
    assert {fact["details"]["stepId"] for fact in result.execution_state["failureEvents"]} == {"A", "B"}
    expected = {"policy": "policy", "storage": "storage", "contract": "permanent",
        "hands_unknown": "permanent"}[sibling_failure]
    assert planner.observations[0].failure_type == expected
    if sibling_failure == "hands_unknown":
        assert planner.observations[0].failure_reason == "HANDS_OUTCOME_UNKNOWN"
        assert result.execution_state["failureEvents"][-1]["details"]["stepId"] == "B"
    assert set(planner.observations[0].failed_step_ids) == {"A", "B"}
