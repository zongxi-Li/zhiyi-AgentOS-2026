"""Resource blockers cross the durable Planner barrier, not a parallel runtime."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from components.resource.application.resource_plane import ResourcePlane
from components.resource.infrastructure.runtime_store import SQLiteResourceStore
from components.resource.infrastructure.node_store import SQLiteNodeStore
from components.resource.runtime.embedded_runtime import EMBEDDED_AGENTS_RUNTIME_ID
from contracts.capability import CapabilityKind, CapabilityManifest
from contracts.resource import ExecutionRequirement, ModelEndpointProfile, RuntimeProfile
from contracts.runtime_planning import RuntimePlanningDecision, RuntimeWaitCondition
from contracts.tools import HostToolExecutionError
from contracts.workflow import StepStatus, WorkflowStatus
from runtime.orchestration.binding import assess_run_requirement, effective_recovery_requirement
from TEST.tests.runtime.test_planning_loop import Agent, Planner, prepared, runtime_at, attach


class ModelAdapter:
    manifest = CapabilityManifest(capabilityId="fixture.resource-model", kind=CapabilityKind.MODEL,
        displayName="fixture", provider="fixture", capabilities=["fixture-model"])

    def is_available(self):
        return True

    async def invoke(self, request):
        raise AssertionError("The deterministic execution fixture must not call a model")


def endpoint(*, supported=True):
    return ModelEndpointProfile(endpointId="model:fixture", provider="fixture", model="fixture-model",
        contextWindowTokens=10000, features={"jsonSchema": supported}, metadata={"secret": "DO_NOT_EXPORT"})


def resource_plane(path):
    return ResourcePlane(store=SQLiteResourceStore(path / "resources.sqlite3"),
        node_store=SQLiteNodeStore(path / "nodes.sqlite3"))


def blocked_model_run(tmp_path, *, owner_input=None):
    plane = resource_plane(tmp_path)
    runtime, agent, run = prepared(tmp_path, resource_plane=plane, input=owner_input)
    run.execution_state["bindingRequirements"]["B"].update(
        model={"requiredFeatures": ["json_schema"], "minContextTokens": 8000},
        policyMetadata={"secret": "DO_NOT_EXPORT"})
    runtime.workflow_store.save_run(run)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)

    def choose(observation, plan):
        if observation.failed_step_ids:
            fact = next(r for r in observation.resource_requirements if r.step_id == "B")
            if observation.condition_wake and observation.condition_wake.outcome == "expired":
                return RuntimePlanningDecision(observationId=observation.fingerprint(), action="wait",
                    reason="resource wait expired", question={"prompt": "Supply a compatible model or revise the task?"})
            if observation.wake_reason == "failure":
                return RuntimePlanningDecision(observationId=observation.fingerprint(), action="wait",
                    reason="missing compatible model", waitFor={"kind": "requirement_available",
                        "stepId": "B", "requirementId": fact.requirement_id, "expiresAt": deadline})
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="recover",
                reason="Recovery rechecks current eligibility")
        return RuntimePlanningDecision(observationId=observation.fingerprint(),
            action="continue" if observation.remaining_step_ids else "complete", reason="current committed state")

    planner = Planner(choose)
    attach(runtime, planner)
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW
    assert agent.calls == ["A"]
    return runtime, agent, paused, planner, deadline


def test_missing_model_wait_restart_then_recover_without_reexecuting_upstream(tmp_path):
    runtime, agent, paused, planner, deadline = blocked_model_run(tmp_path, owner_input={
        "authenticatedUserId": "reviewer", "authenticatedTenantId": "tenant-b",
    })
    assert runtime.workflow_store.list_runs().total == 0
    assert runtime.workflow_store.list_runs(owner_user_id="reviewer", owner_tenant_id="tenant-a").total == 0
    failure = planner.observations[0]
    assert failure.failure_source == "scheduler" and failure.failure_reason == "NO_MODEL_ENDPOINT"
    assert failure.failure_step_id == "B"
    fact = failure.resource_requirements[0]
    assert fact.step_id == "B" and fact.reason == "NO_MODEL_ENDPOINT" and not fact.ready
    assert fact.model_demand.min_context_tokens == 8000
    assert "DO_NOT_EXPORT" not in json.dumps(failure.model_dump(mode="json"))
    upstream_ref = paused.execution_state["outputRefs"]["A"]
    for _ in range(3):
        assert asyncio.run(runtime.prepare_planning_wakeups()) == []
    assert len(planner.observations) == 1
    recovered, agent2 = runtime_at(tmp_path, resource_plane=resource_plane(tmp_path))
    recovered.model_registry.register(ModelAdapter())
    attach(recovered, planner)
    recovered.resource_plane.upsert_model_endpoint(endpoint(supported=False))
    assert asyncio.run(recovered.prepare_planning_wakeups()) == []  # Node online is insufficient.
    recovered.resource_plane.upsert_model_endpoint(endpoint())
    assert asyncio.run(recovered.prepare_planning_wakeups()) == [paused.run_id]
    ready = recovered.workflow_store.get_run(paused.run_id)
    wake = ready.execution_state["planningLoop"]["waiting"]["wake"]
    assert wake["outcome"] == "ready" and wake["modelEndpointVersions"]["model:fixture"] >= 2
    assert recovered.resource_binder.coordinator.active_slots(EMBEDDED_AGENTS_RUNTIME_ID) == 0
    # A committed wake can be redelivered after a second restart.
    resumed, agent3 = runtime_at(tmp_path, resource_plane=resource_plane(tmp_path))
    resumed.model_registry.register(ModelAdapter())
    attach(resumed, planner)
    assert asyncio.run(resumed.prepare_planning_wakeups()) == [paused.run_id]
    result = asyncio.run(resumed.execute_prepared_run(paused.run_id))
    assert result.status == WorkflowStatus.COMPLETED
    assert agent2.calls == [] and agent3.calls == ["B"]
    assert result.execution_state["outputRefs"]["A"] == upstream_ref
    assert result.execution_state["executionBindings"]["B"]["modelBinding"]["endpointId"] == "model:fixture"
    assert [o.wake_reason for o in planner.observations] == ["failure", "condition", "exhausted"]
    assert len(result.execution_state["inPlaceRetryRequests"]) == 1


def test_resource_wait_expires_to_planner_question_without_retry(tmp_path):
    runtime, agent, paused, planner, deadline = blocked_model_run(tmp_path)
    assert asyncio.run(runtime.prepare_planning_wakeups(now=deadline)) == [paused.run_id]
    result = asyncio.run(runtime.execute_prepared_run(paused.run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A"]
    assert planner.observations[-1].condition_wake.outcome == "expired"
    assert result.execution_state["planningLoop"]["current"]["decision"]["question"]
    assert result.execution_state["planningLoop"]["waiting"] is None
    assert asyncio.run(runtime.prepare_planning_wakeups()) == []
    assert len(planner.observations) == 2


@pytest.mark.parametrize("at_decision", [False, True])
def test_resource_disappears_after_wake_recovery_cannot_bypass_binder(tmp_path, at_decision):
    runtime, agent, paused, planner, _ = blocked_model_run(tmp_path)
    runtime.resource_plane.upsert_model_endpoint(endpoint())
    assert asyncio.run(runtime.prepare_planning_wakeups()) == [paused.run_id]
    def disable():
        runtime.resource_plane.upsert_model_endpoint(endpoint().model_copy(update={"enabled": False}))
    if at_decision:
        original_choose = planner.choose
        def choose(o, p):
            if o.wake_reason == "condition":
                disable()
            return original_choose(o, p)
        planner.choose = choose
    else:
        disable()
    result = asyncio.run(runtime.execute_prepared_run(paused.run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A"]
    assert result.execution_state["planningLoop"]["current"]["status"] == "rejected"
    assert "inPlaceRetryRequests" not in result.execution_state
    assert asyncio.run(runtime.prepare_planning_wakeups()) == []


def test_changed_frozen_requirement_never_wakes_old_wait(tmp_path):
    runtime, agent, paused, planner, _ = blocked_model_run(tmp_path)
    latest = runtime.workflow_store.get_run(paused.run_id)
    latest.execution_state["bindingRequirements"]["B"]["requiredCapabilities"].append("unavailable.capability")
    runtime.workflow_store.save_run(latest)
    runtime.resource_plane.upsert_model_endpoint(endpoint())
    assert asyncio.run(runtime.prepare_planning_wakeups()) == []
    assert agent.calls == ["A"] and len(planner.observations) == 1


@pytest.mark.parametrize("change", ["step", "hash", "deadline"])
def test_invalid_resource_wait_is_rejected_at_existing_planner_barrier(tmp_path, change):
    runtime, agent, run = prepared(tmp_path)
    run.execution_state["bindingRequirements"]["B"]["requiredCapabilities"].append("missing.capability")
    runtime.workflow_store.save_run(run)

    def choose(o, p):
        fact = o.resource_requirements[0]
        condition = {"kind": "requirement_available", "stepId": "B", "requirementId": fact.requirement_id,
            "expiresAt": datetime.now(timezone.utc) + timedelta(minutes=5)}
        if change == "step":
            condition["stepId"] = "A"
        elif change == "hash":
            condition["requirementId"] = "0" * 64
        else:
            condition["expiresAt"] = datetime.now(timezone.utc) + timedelta(days=2)
        return RuntimePlanningDecision(observationId=o.fingerprint(), action="wait", reason="invalid target", waitFor=condition)

    attach(runtime, Planner(choose))
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A"]
    assert result.execution_state["planningLoop"]["current"]["status"] == "rejected"
    assert result.execution_state["planningLoop"]["waiting"] is None


def test_online_node_with_wrong_capability_does_not_wake(tmp_path):
    runtime, agent, run = prepared(tmp_path)
    run.execution_state["bindingRequirements"]["B"]["requiredCapabilities"].append("missing.capability")
    runtime.workflow_store.save_run(run)
    def choose(o, p):
        fact = o.resource_requirements[0]
        return RuntimePlanningDecision(observationId=o.fingerprint(), action="wait", reason="missing capability",
            waitFor={"kind": "requirement_available", "stepId": "B", "requirementId": fact.requirement_id,
                "expiresAt": datetime.now(timezone.utc) + timedelta(minutes=5)})
    planner = Planner(choose)
    attach(runtime, planner)
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW
    assert "CAPABILITY_MISMATCH" in planner.observations[0].resource_requirements[0].candidates[0].reasons
    for _ in range(3):
        assert asyncio.run(runtime.prepare_planning_wakeups()) == []
    assert len(planner.observations) == 1 and agent.calls == ["A"]


def test_resource_condition_requires_exact_fields_and_aware_deadline():
    with pytest.raises(ValueError):
        RuntimeWaitCondition(kind="requirement_available", stepId="B", requirementId="a" * 64,
            expiresAt=datetime.now())
    with pytest.raises(ValueError):
        RuntimeWaitCondition(kind="node_available", nodeId="node", stepId="B")


@pytest.mark.parametrize("backup_fails", [False, True])
def test_local_failover_is_sparse_and_exhaustion_reaches_planner(tmp_path, backup_fails):
    from adapters.agent.resource_execution import ResourceExecutionError
    from contracts.resource import Placement, ResourceEndpoint, RuntimeProfile, RuntimeSnapshot, TrustLevel
    runtime, agent, run = prepared(tmp_path)
    capabilities = sorted({c for req in run.execution_state["bindingRequirements"].values()
        for c in req["requiredCapabilities"]})
    attempts = []
    class Remote:
        def __init__(self, name, fail):
            self.name, self.fail = name, fail
        async def run(self, context):
            attempts.append((self.name, context.step.step_id))
            if self.fail:
                raise ResourceExecutionError("remote unavailable")
            return await agent.run(context)
    for index, name in enumerate(("edge", "backup")):
        runtime.resource_plane.ensure_node(f"node:{name}", placement=Placement.CLOUD, trust=TrustLevel.HOST_TRUSTED)
        runtime.resource_plane.register_remote_runtime(RuntimeProfile(runtimeId=name, nodeId=f"node:{name}",
            placement=Placement.CLOUD, capabilities=capabilities, trust=TrustLevel.TRUSTED,
            endpoint=ResourceEndpoint(protocol="http", address=f"http://{name}.invalid/execute"), ownerScope="fixture"),
            RuntimeSnapshot(runtimeId=name, availableSlots=1, utilization=0))
        runtime.resource_plane.observe_remote_runtime(name, available_slots=1, utilization=0,
            latency_ms=10 + index * 100, observation_sequence=1)
        runtime.resource_execution_adapters[name] = Remote(name, index == 0 or backup_fails)
    for requirement in run.execution_state["bindingRequirements"].values():
        requirement["allowedRuntimeIds"] = ["edge", "backup"]
    runtime.workflow_store.save_run(run)
    def choose(o, p):
        return RuntimePlanningDecision(observationId=o.fingerprint(),
            action="wait" if o.failed_step_ids else "complete", reason="persisted state")
    planner = Planner(choose)
    attach(runtime, planner)
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert len(planner.observations) == 1
    if backup_fails:
        assert result.status == WorkflowStatus.WAITING_REVIEW
        assert planner.observations[0].wake_reason == "failure"
        assert [f.runtime_id for f in planner.observations[0].resource_failovers] == ["edge", "backup"]
        assert agent.calls == []
    else:
        assert result.status == WorkflowStatus.COMPLETED
        assert planner.observations[0].wake_reason == "exhausted"
        assert agent.calls == ["A", "B"]
    assert attempts[0] == ("edge", "A")


def test_legacy_decided_failure_round_is_not_replanned_after_restart(tmp_path):
    from contracts.runtime_planning import RuntimePlanningObservation
    from TEST.tests.runtime.test_planning_loop import PowerLoss
    runtime, agent, run = prepared(tmp_path, Agent(fail=True))
    attach(runtime, Planner(lambda o, p: RuntimePlanningDecision(observationId=o.fingerprint(),
        action="wait", reason="external resolution")))
    save = runtime.runtime_planning_coordinator.guarded_save
    def crash(snapshot):
        current = snapshot.execution_state["planningLoop"]["current"]
        if current and current["status"] == "decided":
            raw = current["observation"]
            for key in ("failureReason", "failureSource", "failureStepId", "resourceRequirements", "resourceFailovers"):
                raw.pop(key, None)
            current["observationId"] = RuntimePlanningObservation.model_validate(raw).fingerprint()
            current["decision"]["observationId"] = current["observationId"]
            save(snapshot)
            raise PowerLoss("legacy decided round")
        save(snapshot)
    runtime.runtime_planning_coordinator.guarded_save = crash
    with pytest.raises(PowerLoss):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    recovered, agent2 = runtime_at(tmp_path)
    planner = Planner()
    attach(recovered, planner)
    asyncio.run(recovered.close_orphaned_runs())
    result = asyncio.run(recovered.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW
    assert not planner.observations and not agent2.calls


class BlockedHandsAgent(Agent):
    def __init__(self):
        super().__init__()
        self.failed_once = False

    async def run(self, context):
        if context.step.step_id == "B" and not self.failed_once:
            self.failed_once = True
            self.calls.append("B")
            raise HostToolExecutionError("NO_ELIGIBLE_RESOURCE", "Hands backend is disabled", details={
                "stepId": "B", "attemptId": context.attempt_id, "commitId": context.commit_id,
                "tool": "fs.read", "resourceId": "n01a-host", "operationKey": "read:fixture",
                "phase": "bind", "schedulingReason": "NO_ELIGIBLE_RESOURCE",
                "candidateReasons": [{"resourceId": "n01a-host", "reasons": ["DISABLED"]}],
            })
        return await super().run(context)


def blocked_hands_run(tmp_path):
    runtime, agent, run = prepared(tmp_path, BlockedHandsAgent(), resource_plane=resource_plane(tmp_path))
    host_node = runtime.resource_plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID).node_id
    runtime.resource_plane.register_runtime(RuntimeProfile(runtimeId="n01a-host", nodeId=host_node,
        capabilities=["fs.read"], enabled=False, metadata={"managedBy": "bootstrap"}))
    runtime.resource_plane.heartbeat_runtime("n01a-host")
    original = json.loads(json.dumps(run.execution_state["bindingRequirements"]))
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)

    def choose(observation, plan):
        if observation.failed_step_ids:
            fact = next(r for r in observation.resource_requirements if r.step_id == "B")
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="recover" if fact.ready else "wait", reason="Observe the failed tool dependency",
                waitFor=None if fact.ready else {"kind": "requirement_available", "stepId": "B",
                    "requirementId": fact.requirement_id, "expiresAt": deadline})
        return RuntimePlanningDecision(observationId=observation.fingerprint(),
            action="continue" if observation.remaining_step_ids else "complete", reason="Committed facts")

    planner = Planner(choose)
    attach(runtime, planner)
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW
    assert paused.execution_state["bindingRequirements"] == original
    assert agent.calls == ["A", "B"]
    return runtime, agent, paused, planner


def test_disabled_hands_waits_for_tool_backend_despite_ready_agent_then_resumes_after_restart(tmp_path):
    runtime, agent, paused, planner = blocked_hands_run(tmp_path)
    assert assess_run_requirement(runtime, paused,
        ExecutionRequirement.model_validate(paused.execution_state["bindingRequirements"]["B"])).ready
    failure = planner.observations[0]
    assert failure.failure_source == "scheduler" and failure.failure_reason == "NO_ELIGIBLE_RESOURCE"
    assert failure.failure_step_id == "B" and failure.recovery_action == "rebind"
    fact = failure.resource_requirements[0]
    assert fact.step_id == "B" and fact.required_capabilities == ("fs.read",) and not fact.ready
    hands = next(candidate for candidate in fact.candidates if candidate.runtime_id == "n01a-host")
    assert not hands.accepted and "DISABLED" in hands.reasons
    assert asyncio.run(runtime.prepare_planning_wakeups()) == []
    upstream = paused.execution_state["outputRefs"]["A"]

    resumed, agent2 = runtime_at(tmp_path, resource_plane=resource_plane(tmp_path))
    attach(resumed, planner)
    resumed.resource_plane.heartbeat_runtime("n01a-host")
    assert asyncio.run(resumed.prepare_planning_wakeups()) == []
    resumed.resource_plane.set_runtime_enabled("n01a-host", enabled=True)
    assert asyncio.run(resumed.prepare_planning_wakeups()) == [paused.run_id]
    result = asyncio.run(resumed.execute_prepared_run(paused.run_id))
    assert result.status == WorkflowStatus.COMPLETED and agent2.calls == ["B"]
    assert result.execution_state["outputRefs"]["A"] == upstream
    assert [o.wake_reason for o in planner.observations] == ["failure", "condition", "exhausted"]
    assert effective_recovery_requirement(result, "B") == ExecutionRequirement.model_validate(
        result.execution_state["bindingRequirements"]["B"])


@pytest.mark.parametrize("change", ["step", "attempt", "commit", "generation", "loop", "settled", "status", "tool"])
def test_tool_recovery_requirement_cannot_reuse_stale_or_settled_failure(tmp_path, change):
    _, _, paused, _ = blocked_hands_run(tmp_path)
    expected = ExecutionRequirement.model_validate(paused.execution_state["bindingRequirements"]["B"])
    failure = paused.execution_state["failureEvents"][-1]["details"]
    if change in {"step", "attempt", "commit"}:
        failure[f"{change}Id"] = "stale"
    elif change == "generation":
        paused.execution_state["executionGeneration"] = "new-generation"
    elif change == "loop":
        paused.execution_state.setdefault("loopPaths", {})["B"] = [1]
    elif change == "settled":
        paused.execution_state.setdefault("completedStepIds", []).append("B")
    elif change == "status":
        paused.get_step("B").status = StepStatus.COMPLETED
    else:
        failure["tool"] = "arbitrary.not-a-host-tool"
    assert effective_recovery_requirement(paused, "B") == expected


def test_tool_backend_disappearing_during_planning_cannot_trigger_agent_retry(tmp_path):
    runtime, agent, paused, planner = blocked_hands_run(tmp_path)
    runtime.resource_plane.set_runtime_enabled("n01a-host", enabled=True)
    assert asyncio.run(runtime.prepare_planning_wakeups()) == [paused.run_id]
    choose = planner.choose

    def disable_during_planning(observation, plan):
        if observation.wake_reason == "condition":
            runtime.resource_plane.set_runtime_enabled("n01a-host", enabled=False)
        return choose(observation, plan)

    planner.choose = disable_during_planning
    result = asyncio.run(runtime.execute_prepared_run(paused.run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW and agent.calls == ["A", "B"]
    assert result.execution_state["planningLoop"]["current"]["status"] == "rejected"
    assert "inPlaceRetryRequests" not in result.execution_state


def test_executor_tool_failure_also_requires_current_tool_readiness(tmp_path):
    from runtime.orchestration.planning_loop import RuntimePlanningCoordinator

    _, _, _, planner = blocked_hands_run(tmp_path)
    observation = planner.observations[0].model_copy(update={
        "failure_source": "executor", "failure_reason": "HANDS_OUTCOME_UNKNOWN", "recovery_action": "retry"})
    decision = RuntimePlanningDecision(observationId=observation.fingerprint(), action="recover", reason="Read-only retry")
    with pytest.raises(ValueError, match="currently eligible execution resources"):
        RuntimePlanningCoordinator.validate_decision(observation, decision)
    unrelated = observation.model_copy(update={"failure_reason": "EXECUTION_TIMEOUT"})
    RuntimePlanningCoordinator.validate_decision(unrelated,
        decision.model_copy(update={"observation_id": unrelated.fingerprint()}))
