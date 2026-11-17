"""Planner readiness and READY dispatch share live, scoped registration facts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from components.resource.application.resource_plane import ResourcePlane
from components.resource.domain.runtime_health import ResourceHealthMonitor
from components.resource.infrastructure.health_store import SQLiteResourceHealthStore
from components.resource.infrastructure.runtime_store import SQLiteResourceStore
from components.resource.runtime.embedded_runtime import EMBEDDED_AGENTS_RUNTIME_ID, refresh_embedded_agents_runtime
from components.resource.scheduler.binder import ResourceBinder
from contracts.resource import ExecutionRequirement, Placement, ResourceEndpoint, RuntimeKind, RuntimeProfile
from runtime.binding import RuntimeBindingService, assess_run_requirement
from service.agents import AgentProfile, AgentRegistry, BaseAgent


class _Agent(BaseAgent):
    async def run(self, context):
        raise AssertionError("readiness must never invoke an Agent")


def _agent(agent_id="analyst", *, capabilities=("analysis",), capacity=2):
    return _Agent(AgentProfile(agentId=agent_id, agentName=agent_id, domain="general",
                              capabilities=list(capabilities), capacity=capacity))


@pytest.fixture(params=["memory", "sqlite"])
def services(request, tmp_path):
    registry = AgentRegistry()
    registry.register(_agent())
    store = health_store = None
    if request.param == "sqlite":
        store = SQLiteResourceStore(tmp_path / "resources.sqlite3")
        health_store = SQLiteResourceHealthStore(tmp_path / "health.sqlite3")
    plane = ResourcePlane(store=store,
        health_monitor=ResourceHealthMonitor(store=health_store) if health_store else None)
    refresh_embedded_agents_runtime(plane, registry)
    binding = RuntimeBindingService(agent_registry=registry, resource_plane=plane, resource_execution_adapters={})
    binding.agent_pool.synchronize()
    result = SimpleNamespace(agent_registry=registry, resource_plane=plane,
        resource_execution_adapters={}, resource_binder=ResourceBinder(plane), binding=binding)
    yield result
    if store is not None:
        store.close()
    if health_store is not None:
        health_store.close()


def _run(agent_ids=("analyst",)):
    return SimpleNamespace(execution_scope=SimpleNamespace(agent_ids=agent_ids))


def _requirement(capability="analysis"):
    return ExecutionRequirement(requiredCapabilities=[capability], runtimeKinds=[RuntimeKind.EXECUTION_BACKEND])


def test_readiness_refreshes_local_host_node_and_current_instance_without_allocating(services):
    plane = services.resource_plane
    ref = services.agent_registry.registrations()[0].ref
    host = plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    plane.heartbeat_runtime(host.runtime_id, received_at=past)
    plane.heartbeat_node(host.node_id, observed_at=past)
    plane.health_monitor.heartbeat(ref.resource_id, received_at=past)
    assert not plane.health_monitor.health(host.runtime_id).healthy
    assert not plane.health_monitor.health(ref.resource_id).healthy

    readiness = assess_run_requirement(services, _run(), _requirement())

    assert readiness.ready
    assert next(c for c in readiness.candidates if c.resource_id == host.runtime_id).accepted
    instance = next(c for c in readiness.candidates if c.resource_id == ref.resource_id)
    assert not instance.accepted
    assert "AGENT_INSTANCE_NOT_SCHEDULABLE" in {r.value for r in instance.reasons}
    assert plane.health_monitor.health(ref.resource_id).healthy
    assert plane.runtime(host.runtime_id) == host
    for resource_id in (host.runtime_id, ref.resource_id):
        assert services.resource_binder.coordinator.active_slots(resource_id) == 0


@pytest.mark.parametrize("blocked", ["host_disabled", "host_draining", "node_disabled",
                                    "instance_disabled", "instance_draining", "outcome_unknown"])
def test_liveness_cannot_undo_administration_or_unknown_work(services, blocked):
    plane = services.resource_plane
    ref = services.agent_registry.registrations()[0].ref
    host = plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID)
    if blocked == "host_disabled":
        plane.set_runtime_enabled(host.runtime_id, enabled=False)
    elif blocked == "host_draining":
        plane.store.update_profile(host.model_copy(update={"draining": True}))
    elif blocked == "node_disabled":
        plane.set_node_enabled(host.node_id, enabled=False)
    elif blocked == "instance_disabled":
        plane.set_agent_instance_state(ref, expected_version=1, enabled=False)
    elif blocked == "instance_draining":
        plane.set_agent_instance_state(ref, expected_version=1, draining=True)
    else:
        plane.quarantine_agent_instance(ref)
    before_host, before_instance = plane.runtime(host.runtime_id), plane.runtime(ref.resource_id)
    before_node = plane.node(host.node_id)

    assert not assess_run_requirement(services, _run(), _requirement()).ready

    assert plane.runtime(host.runtime_id) == before_host
    assert plane.runtime(ref.resource_id) == before_instance
    assert plane.node(host.node_id) == before_node


def test_scoped_readiness_cannot_use_another_agent_or_shrink_shared_host(services):
    services.agent_registry.register(_agent("writer", capabilities=("writing",), capacity=3))
    refresh_embedded_agents_runtime(services.resource_plane, services.agent_registry)
    host = services.resource_plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID)
    assert host.capacity == 5 and "writing" in host.capabilities

    assert not assess_run_requirement(services, _run(), _requirement("writing")).ready
    assert assess_run_requirement(services, _run(("writer",)), _requirement("writing")).ready
    assert services.resource_plane.runtime(host.runtime_id) == host


def test_current_registry_epoch_renews_only_its_own_instances(services):
    plane = services.resource_plane
    old = services.agent_registry.registrations()[0].ref
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    plane.health_monitor.heartbeat(old.resource_id, received_at=past)
    registry = AgentRegistry()
    registry.register(_agent())
    services.agent_registry = registry
    current = registry.registrations()[0].ref
    assert current.resource_id != old.resource_id

    assert assess_run_requirement(services, _run(), _requirement()).ready

    assert plane.health_monitor.health(current.resource_id).healthy
    assert plane.health_monitor.health(old.resource_id).last_heartbeat == past
    assert not plane.health_monitor.health(old.resource_id).healthy


def test_remote_replica_does_not_receive_local_heartbeat_or_satisfy_local_scope(services):
    plane = services.resource_plane
    plane.ensure_node("node:remote", placement=Placement.EDGE)
    plane.register_runtime(RuntimeProfile(runtimeId="host:remote", nodeId="node:remote",
        placement=Placement.EDGE, capabilities=["writing"],
        endpoint=ResourceEndpoint(protocol="http", address="http://example.invalid")))
    ref = services.binding.agent_pool.register_instance(
        _agent("writer", capabilities=("writing",)), instance_id="remote-writer", host_runtime_id="host:remote")

    assert not assess_run_requirement(services, _run(("writer",)), _requirement("writing")).ready

    assert plane.health_monitor.health(ref.resource_id).last_heartbeat is None
    assert plane.health_monitor.health("host:remote").last_heartbeat is None


def test_planner_observes_real_local_readiness_before_dispatch_and_keeps_round_identity(tmp_path):
    from runtime.state_persistence import acg_execution_state_from_run
    from test_planning_loop import prepared

    runtime, agent, run = prepared(tmp_path)
    plane = runtime.resource_plane
    host = plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    plane.heartbeat_runtime(host.runtime_id, received_at=past)
    plane.heartbeat_node(host.node_id, observed_at=past)
    assert all(not plane.health_monitor.health(r.ref.resource_id).healthy
               for r in runtime.agent_registry.registrations())
    state = acg_execution_state_from_run(run)

    first = runtime.runtime_planning_coordinator.observe(run, state, "resume")
    second = runtime.runtime_planning_coordinator.observe(run, state, "resume")

    assert first.resource_requirements and all(r.ready for r in first.resource_requirements)
    assert (host.node_id, "online") in first.resources
    assert first.fingerprint() == second.fingerprint()
    assert agent.calls == []
