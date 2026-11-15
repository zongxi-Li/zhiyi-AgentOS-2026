"""Changing an implementation after READY cannot redirect an admitted call."""

import asyncio
import pytest

from components.executor.graph import ACGSuperstepError
from runtime import live_events
from service.agents import AgentOutput
from TEST.tests.runtime.test_model_binding_capacity import _Agent, _prepare, _runtime


def test_replacement_after_node_started_rejects_stale_registration_before_any_agent_effect(monkeypatch):
    runtime, _, _ = _runtime()
    run = _prepare(runtime)
    selected = runtime.agent_registry.resolve_by_id("first")
    original_calls, replacement_calls, replacements = [], [], []
    old_run = selected.run

    async def record_old(context):
        original_calls.append(context.step.step_id)
        return await old_run(context)

    selected.run = record_old
    publish = live_events.runtime_event_broker.publish

    async def replace_after_start(run_id, event):
        await publish(run_id, event)
        if event.event_type == "node.started" and event.node_id == "first":
            replacements.append(True)
            runtime.agent_registry.register(_Agent(selected.profile.model_copy(deep=True), replacement_calls))

    monkeypatch.setattr(live_events.runtime_event_broker, "publish", replace_after_start)
    with pytest.raises(ACGSuperstepError) as error:
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert error.value.cause.code == "AGENT_NOT_IN_SCOPE"
    result = runtime.workflow_store.get_run(run.run_id)

    assert replacements == [True]
    assert original_calls == replacement_calls == []
    assert result.get_step("first").status.value != "completed"
    commits = runtime.execution_value_store.list_node_commits(run_id=run.run_id)
    assert not [item for item in commits if ":first:" in item["commitId"] and item.get("outputRef")]

    # A later, explicitly prepared execution can use the replacement normally.
    monkeypatch.setattr(live_events.runtime_event_broker, "publish", publish)
    later = _prepare(runtime)
    assert asyncio.run(runtime.execute_prepared_run(later.run_id)).status.value == "completed"
    assert replacement_calls
    later_result = runtime.workflow_store.get_run(later.run_id)
    assert later_result.execution_state["executionBindings"]["first"]["agentRegistration"] == (
        runtime.agent_registry.registration_for(runtime.agent_registry.resolve_by_id("first")).model_dump(by_alias=True, mode="json"))


@pytest.mark.parametrize("replicas", [1, 2])
def test_ready_steps_observe_instance_capacity_and_use_a_free_replica(replicas):
    runtime, _, _ = _runtime()
    registry = runtime.agent_registry
    first, writer = registry.resolve_by_id("first"), registry.resolve_by_id("second")
    writer.profile.capabilities = ["writing"]
    registry.register(writer)
    active = peak = 0
    seen = []

    async def execute(context):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        seen.append(context.agent_registration)
        try:
            await asyncio.sleep(0.02)
            return AgentOutput(output={"answer": "ok"})
        finally:
            active -= 1

    first.run = execute
    run = _prepare(runtime)  # Freeze logical scope before creating a replica.
    if replicas == 2:
        from components.marketplace.infrastructure import InMemoryInstallationJobs
        from service.agents.provisioning import AgentProvisioner

        def factory():
            replica = _Agent(first.profile.model_copy(deep=True), [])
            replica.run = execute
            return replica

        provisioner = AgentProvisioner(pool=runtime.runtime_binding_service.agent_pool,
            jobs=InMemoryInstallationJobs(), coordinator=runtime.resource_binder.coordinator,
            refresh_runtime=runtime.runtime_binding_service.refresh_embedded_runtime)
        provisioner.register_agent_template("first", seed=first, factory=factory)
        assert provisioner.provision("first", "parallel").status.value == "running"
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status.value == "completed" and peak == replicas
    assert len({ref.instance_id for ref in seen}) == replicas
    for binding in result.execution_state["executionBindings"].values():
        assert binding["agentRegistration"]["agentId"] == "first" and binding["agentLeaseId"]
        assert runtime.resource_binder.coordinator.active_slots(binding["resourceId"]) == 0


def test_draining_after_ready_prevents_invocation_and_releases_both_leases(monkeypatch):
    runtime, _, _ = _runtime()
    run = _prepare(runtime)
    called = []
    async def execute(context):
        called.append(True)
        return AgentOutput(output={"answer": "ok"})
    runtime.agent_registry.resolve_by_id("first").run = execute
    publish = live_events.runtime_event_broker.publish
    async def drain(run_id, event):
        await publish(run_id, event)
        if event.event_type == "node.started" and event.node_id == "first":
            from contracts.agents import AgentRegistrationRef
            current = runtime.workflow_store.get_run(run_id)
            ref = AgentRegistrationRef.model_validate(current.execution_state["executionBindings"]["first"]["agentRegistration"])
            runtime.runtime_binding_service.agent_pool.update(ref, expected_version=1, draining=True)
    monkeypatch.setattr(live_events.runtime_event_broker, "publish", drain)
    with pytest.raises(ACGSuperstepError):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert called == []
    result = runtime.workflow_store.get_run(run.run_id)
    binding = result.execution_state["executionBindings"]["first"]
    assert runtime.resource_binder.coordinator.get(binding["leaseId"]).status == "released"
    assert runtime.resource_binder.coordinator.get(binding["agentLeaseId"]).status == "released"


@pytest.mark.parametrize("committed", [True, False])
def test_resume_replays_committed_results_and_never_reinvokes_unsettled_work(monkeypatch, committed):
    from adapters.resource_execution import ResourceExecutionError
    from runtime.state_persistence import acg_execution_state_from_run

    runtime, _, _ = _runtime()
    first = runtime.agent_registry.resolve_by_id("first")
    calls, runners = [], []
    async def execute(context):
        calls.append(context.commit_id)
        if not committed:
            raise ResourceExecutionError("external effect completed but response was lost", outcome_unknown=True)
        return AgentOutput(output={"answer": "ok"})
    first.run = execute
    service = runtime.acg_execution_service
    build = service._build_runner
    def capture(**kwargs):
        runner = build(**kwargs)
        runners.append(runner)
        return runner
    monkeypatch.setattr(service, "_build_runner", capture)
    run = _prepare(runtime)
    if committed:
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    else:
        with pytest.raises(ACGSuperstepError):
            asyncio.run(runtime.execute_prepared_run(run.run_id))
    saved = runtime.workflow_store.get_run(run.run_id)
    binding = saved.execution_state["executionBindings"]["first"]
    runtime.agent_registry.register(_Agent(first.profile.model_copy(deep=True), []))
    runners[0].agents.clear()
    decorated = service._ready_node_runner(run=saved, runner=runners[0])
    state = acg_execution_state_from_run(saved)
    if committed:
        result = asyncio.run(decorated("first", state))
        assert result["outputRef"] == saved.execution_state["outputRefs"]["first"]
    else:
        with pytest.raises(ResourceExecutionError) as error:
            asyncio.run(decorated("first", state))
        assert error.value.outcome_unknown
        assert runtime.resource_binder.coordinator.get(binding["agentLeaseId"]).status == "active"
        from contracts.agents import AgentRegistrationRef
        ref = AgentRegistrationRef.model_validate(binding["agentRegistration"])
        assert runtime.resource_plane.runtime(ref.resource_id).metadata["outcomeUnknown"] is True
    assert len(calls) == 1


def test_run_scope_filters_candidates_without_shrinking_shared_host_capacity():
    from contracts.compiled_acg import BindingManifest, BindingRule
    from components.resource.runtime.embedded_runtime import EMBEDDED_AGENTS_RUNTIME_ID

    runtime, _, _ = _runtime()
    run = _prepare(runtime)
    service = runtime.runtime_binding_service
    scope = run.execution_scope.model_copy(update={"agent_ids": ("first",)})
    service.prepare(run=run, workflow=runtime.workflow_registry.get("model-capacity"), scope=scope,
        binding_manifest=BindingManifest(rules=tuple(BindingRule(
            stepId=step.step_id, requiredCapabilities=("analysis",)) for step in run.steps)))
    assert runtime.resource_plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID).capacity == 2
    candidates = service.agent_pool.local_candidates(scope.agent_ids)
    assert {item.agent_registration.agent_id for items in candidates.values() for item in items} == {"first"}


def test_legacy_local_attempt_is_not_silently_rebound_to_an_instance():
    from contracts.resource import ExecutionBinding, RuntimeKind
    from components.resource.runtime.embedded_runtime import EMBEDDED_AGENTS_RUNTIME_ID
    from TEST.tests.runtime.test_resource_binding import _runtime as resource_runtime

    calls = []
    runtime, _ = resource_runtime(calls)
    task = runtime.create_mission("legacy allocation", workflow_id="resource-run")
    _, run = runtime.prepare_run(task.mission_id)
    legacy = ExecutionBinding(bindingId="legacy-binding", runId=run.run_id, stepId="analyse",
        attemptId="legacy-attempt", resourceId=EMBEDDED_AGENTS_RUNTIME_ID,
        runtimeKind=RuntimeKind.EXECUTION_BACKEND, snapshotVersion=1, leaseId="legacy-lease")
    body = legacy.model_dump(by_alias=True, mode="json", exclude_none=True)
    run.execution_state["attemptIds"] = {"analyse:1:root": "legacy-attempt"}
    run.execution_state["executionBindings"] = {"analyse": body}
    runtime.workflow_store.save_run(run)
    with pytest.raises(ACGSuperstepError) as error:
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert error.value.cause.reason_code == "LEGACY_LOCAL_BINDING"
    assert calls == []
    assert runtime.workflow_store.get_run(run.run_id).execution_state["executionBindings"]["analyse"] == body
