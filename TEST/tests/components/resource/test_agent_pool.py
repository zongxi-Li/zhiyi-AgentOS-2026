"""AgentPool is a join over registrations and ResourcePlane, never a scheduler."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import json

import pytest

from components.resource.application.resource_plane import ResourcePlane, compute_registration_id
from components.resource.domain.runtime_health import ResourceHealthMonitor
from components.resource.infrastructure.health_store import SQLiteResourceHealthStore
from components.resource.infrastructure.runtime_store import SQLiteResourceStore, VersionConflict
from components.resource.runtime.embedded_runtime import EMBEDDED_AGENTS_RUNTIME_ID, register_embedded_agents_runtime, refresh_embedded_agents_runtime
from components.resource.scheduler.binder import ResourceBinder
from contracts.resource import ExecutionRequirement, Placement, RuntimeKind, RuntimeProfile, RuntimeSnapshot
from adapters.agent import AgentNotFound, AgentOutput, AgentProfile, AgentRegistry, BaseAgent
from components.resource.agents.pool import AgentPool


class _Agent(BaseAgent):
    async def run(self, context):
        return AgentOutput(output={})


def _agent(version="1"):
    return _Agent(AgentProfile(agentName="analyst", agentId="analyst", domain="general",
                              capabilities=["analysis"], definitionVersion=version, capacity=2))


@pytest.fixture(params=["memory", "sqlite"])
def pool(request, tmp_path):
    registry = AgentRegistry()
    registry.register(_agent())
    store = health_store = None
    if request.param == "sqlite":
        store = SQLiteResourceStore(tmp_path / "instances.sqlite3")
        health_store = SQLiteResourceHealthStore(tmp_path / "health.sqlite3")
    plane = ResourcePlane(store=store, health_monitor=(ResourceHealthMonitor(store=health_store) if health_store else None))
    register_embedded_agents_runtime(plane, registry.all())
    result = AgentPool(registry=registry, resource_plane=plane, host_runtime_id=EMBEDDED_AGENTS_RUNTIME_ID)
    result.synchronize()
    yield result
    if store:
        store.close()
    if health_store:
        health_store.close()


def test_pool_exposes_separate_definition_registration_and_resource_facts(pool):
    instance, = pool.instances()
    assert instance.definition.definition_version == "1"
    assert instance.ref.generation == 1
    assert instance.capacity == 2 and not instance.draining
    assert not instance.health.healthy  # no fabricated heartbeat
    assert instance.resource.kind is RuntimeKind.AGENT_INSTANCE
    assert instance.resource.host_runtime_id == EMBEDDED_AGENTS_RUNTIME_ID
    assert pool.registry.resolve_by_id("analyst") is pool.registry.registrations()[0].implementation


def test_global_host_refresh_uses_local_instance_state_and_not_remote_replicas(pool):
    local = pool.register_instance(_agent(), instance_id="local-replica", enabled=False)
    assert refresh_embedded_agents_runtime(pool.resource_plane, pool.registry).capacity == 2
    pool.update(local, expected_version=1, enabled=True, capacity=3)
    assert refresh_embedded_agents_runtime(pool.resource_plane, pool.registry).capacity == 5
    plane = pool.resource_plane
    plane.ensure_node("node:other", placement=Placement.EDGE)
    plane.register_runtime(RuntimeProfile(runtimeId="host:other", nodeId="node:other",
        placement=Placement.EDGE, capabilities=["exec.agents"], capacity=20))
    pool.register_instance(_agent(), instance_id="other", host_runtime_id="host:other")
    assert refresh_embedded_agents_runtime(plane, pool.registry).capacity == 5
    pool.update(local, expected_version=2, draining=True)
    assert refresh_embedded_agents_runtime(plane, pool.registry).capacity == 2


def test_agent_and_host_capacity_are_both_reserved_and_partial_allocation_is_compensated(pool, monkeypatch):
    plane = pool.resource_plane
    ref = pool.instances()[0].ref
    pool.update(ref, expected_version=1, capacity=1)
    plane.heartbeat_runtime(EMBEDDED_AGENTS_RUNTIME_ID)
    binder = ResourceBinder(plane)
    common = dict(run_id="run", step_id="step", requirement=ExecutionRequirement(requiredCapabilities=["analysis"]))
    first = binder.bind_ready(attempt_id="one", agent_candidates=pool.local_candidates(), **common)
    assert first.status == "allocated" and first.binding.agent_registration == ref
    resumed = binder.bind_ready(attempt_id="one", agent_candidates=pool.local_candidates(),
                                existing_binding=first.binding, **common)
    assert resumed.binding == first.binding
    assert binder.coordinator.active_slots(ref.resource_id) == 1
    second = binder.bind_ready(attempt_id="two", agent_candidates=pool.local_candidates(), **common)
    assert second.status == "queued"
    assert binder.coordinator.active_slots(EMBEDDED_AGENTS_RUNTIME_ID) == 1
    assert binder.release_binding(first.binding)
    assert binder.coordinator.active_slots(ref.resource_id) == 0

    acquire = binder.coordinator.acquire
    def fail_instance(**kwargs):
        if kwargs["resource_id"] == ref.resource_id:
            raise RuntimeError("instance reservation unavailable")
        return acquire(**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(binder.coordinator, "acquire", fail_instance)
        with pytest.raises(RuntimeError, match="instance reservation unavailable"):
            binder.bind_ready(attempt_id="three", agent_candidates=pool.local_candidates(), **common)
    assert binder.coordinator.active_slots(EMBEDDED_AGENTS_RUNTIME_ID) == 0
    retry = binder.bind_ready(attempt_id="three", agent_candidates=pool.local_candidates(), **common)
    assert retry.status == "allocated"
    pool.register_instance(_agent(), instance_id=ref.instance_id, expected_generation=ref.generation)
    pinned = binder.bind_ready(attempt_id="three", existing_binding=retry.binding,
                               agent_candidates=pool.local_candidates(), **common)
    assert pinned.status == "rejected" and pinned.reason == "PINNED_AGENT_UNAVAILABLE"
    binder.release_binding(retry.binding)


def test_free_replica_cannot_bypass_host_capacity_and_renewal_keeps_binding_identity(pool):
    from datetime import datetime, timedelta, timezone
    from components.resource.scheduler.leases import LeaseRenewalFailedError

    plane = pool.resource_plane
    first_ref = pool.instances()[0].ref
    second_ref = pool.register_instance(_agent(), instance_id="replica")
    for ref in (first_ref, second_ref):
        pool.update(ref, expected_version=1, capacity=1)
    plane.update_runtime_capacity(EMBEDDED_AGENTS_RUNTIME_ID, 1, expected_capacity=2)
    plane.heartbeat_runtime(EMBEDDED_AGENTS_RUNTIME_ID)
    binder = ResourceBinder(plane)
    common = dict(run_id="run", step_id="step", requirement=ExecutionRequirement(requiredCapabilities=["analysis"]))
    first = binder.bind_ready(attempt_id="one", agent_candidates=pool.local_candidates(), **common)
    assert first.status == "allocated"
    assert binder.bind_ready(attempt_id="two", agent_candidates=pool.local_candidates(), **common).status == "queued"
    plane.update_runtime_capacity(EMBEDDED_AGENTS_RUNTIME_ID, 2, expected_capacity=1)
    second = binder.bind_ready(attempt_id="two", agent_candidates=pool.local_candidates(), **common)
    assert second.status == "allocated" and second.binding.agent_registration != first.binding.agent_registration
    for lease in (first.lease, first.agent_lease):
        binder.coordinator.renew(lease_id=lease.lease_id, owner_id=lease.owner_id, version=lease.version,
                                 ttl=timedelta(seconds=60), now=datetime.now(timezone.utc))
    binder.assert_binding(first.binding)
    binder.release(first.agent_lease.lease_id)
    with pytest.raises(LeaseRenewalFailedError):
        binder.assert_binding(first.binding)
    binder.release_binding(first.binding)
    binder.release_binding(second.binding)


def test_health_drain_disabled_and_capacity_are_independent_and_refresh_does_not_reset_them(pool):
    ref = pool.instances()[0].ref
    instance = pool.update(ref, expected_version=1, enabled=False, draining=True, capacity=3)
    assert instance.resource.version == 2
    health = pool.heartbeat(ref)
    assert health.healthy
    pool.synchronize()
    current = pool.describe(ref)
    assert current.capacity == 3 and current.draining and not current.resource.enabled
    assert current.health.healthy
    assert pool.resource_plane.runtime_snapshot(ref.resource_id).snapshot.available_slots == 3
    current.resource.capacity = 99
    assert pool.describe(ref).capacity == 3
    with pytest.raises(VersionConflict):
        pool.update(ref, expected_version=1, draining=False)


def test_replacement_and_old_operations_cannot_modify_the_new_registration(pool):
    old = pool.instances()[0].ref
    pool.heartbeat(old)
    pool.update(old, expected_version=1, draining=True)
    new = pool.register_instance(_agent(), instance_id=old.instance_id, expected_generation=old.generation)
    assert new.generation == old.generation + 1
    assert not pool.describe(new).health.healthy
    assert not pool.describe(new).draining
    for operation in (lambda: pool.heartbeat(old), lambda: pool.update(old, expected_version=2, capacity=5),
                      lambda: pool.unregister(old, expected_version=2)):
        with pytest.raises(AgentNotFound):
            operation()
    assert pool.describe(new).capacity == 2
    # Even a late resource observation bypassing the pool targets the old,
    # distinct health namespace, never the replacement's current facts.
    pool.resource_plane.heartbeat_agent_instance(old)
    assert not pool.describe(new).health.healthy


def test_healthy_registered_instances_are_never_dispatched_by_current_binder(pool):
    instance, = pool.instances()
    pool.heartbeat(instance.ref)
    pool.resource_plane.heartbeat_runtime(EMBEDDED_AGENTS_RUNTIME_ID)
    binder = ResourceBinder(plane=pool.resource_plane)
    decisions = binder.evaluate(ExecutionRequirement(requiredCapabilities=["analysis"]))
    decision = next(item for item in decisions if item.resource_id == instance.ref.resource_id)
    assert not decision.accepted
    assert "AGENT_INSTANCE_NOT_SCHEDULABLE" in [reason.value for reason in decision.reasons]
    assert instance.ref.resource_id not in [item.profile.runtime_id for item in pool.resource_plane.runtime_candidates(["analysis"])]
    explicit = binder.bind_ready(run_id="run", step_id="step", attempt_id="attempt",
        requirement=ExecutionRequirement(requiredCapabilities=["analysis"],
            runtimeKinds=[RuntimeKind.AGENT_INSTANCE], allowedRuntimeIds=[instance.ref.resource_id]))
    assert explicit.status == "rejected" and explicit.lease is None
    assert binder.coordinator.active_slots(instance.ref.resource_id) == 0


def test_pool_scope_is_read_only_and_nested_scope_cannot_expand(pool):
    ref = pool.instances()[0].ref
    assert len(pool.scoped(["analyst"]).instances()) == 1
    hidden = pool.scoped([]).scoped(["analyst"])
    assert hidden.instances() == ()
    with pytest.raises(AgentNotFound):
        hidden.describe(ref)
    assert not hasattr(hidden, "update") and not hasattr(hidden, "register_instance")


def test_health_expires_without_changing_registration_or_capacity(pool):
    ref = pool.instances()[0].ref
    heartbeat = pool.heartbeat(ref)
    later = heartbeat.last_heartbeat + timedelta(seconds=61)
    expired = pool.describe(ref, now=later)
    assert not expired.health.healthy
    assert expired.ref == ref and expired.capacity == 2


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5, "3"])
def test_pool_rejects_invalid_declared_capacity(pool, capacity):
    ref = pool.instances()[0].ref
    with pytest.raises(ValueError, match="positive integer"):
        pool.update(ref, expected_version=1, capacity=capacity)
    assert pool.describe(ref).capacity == 2


def test_logical_disable_is_not_undone_by_instance_health_or_administrative_enable(pool):
    ref = pool.instances()[0].ref
    pool.registry.registrations()[0].implementation.profile.enabled = False
    pool.update(ref, expected_version=1, draining=True)
    pool.heartbeat(ref)
    current = pool.update(ref, expected_version=2, draining=False, enabled=True)
    assert current.health.healthy and current.resource.enabled
    assert not current.logical_enabled
    with pytest.raises(AgentNotFound):
        pool.registry.resolve_registration(ref)


def test_different_definition_versions_can_have_distinct_host_environments(pool):
    plane = pool.resource_plane
    plane.ensure_node("node:edge", placement=Placement.EDGE)
    plane.register_runtime(RuntimeProfile(runtimeId="runtime:edge", nodeId="node:edge", placement=Placement.EDGE,
                                          capabilities=["exec.agents"], capacity=4))
    ref = pool.register_instance(_agent("2"), instance_id="edge-instance", host_runtime_id="runtime:edge")
    instance = pool.describe(ref)
    assert instance.resource.node_id == "node:edge" and instance.resource.placement is Placement.EDGE
    assert instance.definition.definition_version == "2"
    pool.synchronize()
    assert len(pool.instances()) == 2


def test_instance_capability_and_host_environment_are_matched_separately(pool):
    plane = pool.resource_plane
    plane.ensure_node("node:edge", placement=Placement.EDGE)
    plane.register_runtime(RuntimeProfile(runtimeId="runtime:edge", nodeId="node:edge", placement=Placement.EDGE,
        capabilities=["exec.agents"], labels={"sandbox": "linux"}, capacity=1))
    plane.heartbeat_runtime("runtime:edge")
    plane.heartbeat_node("node:edge")
    ref = pool.register_instance(_agent("2"), instance_id="edge", host_runtime_id="runtime:edge")
    binder = ResourceBinder(plane)
    result = binder.bind_ready(run_id="run", step_id="step", attempt_id="attempt",
        requirement=ExecutionRequirement(requiredCapabilities=["analysis"], allowedPlacements=[Placement.EDGE],
                                         labels={"sandbox": "linux"}),
        agent_candidates=pool.local_candidates(["analyst"]))
    assert result.status == "allocated" and result.binding.resource_id == "runtime:edge"
    assert result.binding.agent_registration == ref
    binder.release_binding(result.binding)


def test_agent_instance_resource_and_state_survive_sqlite_reopen(tmp_path):
    store = SQLiteResourceStore(tmp_path / "instances.sqlite3")
    plane = ResourcePlane(store=store)
    registry = AgentRegistry()
    registry.register(_agent())
    register_embedded_agents_runtime(plane, registry.all())
    pool = AgentPool(registry=registry, resource_plane=plane, host_runtime_id=EMBEDDED_AGENTS_RUNTIME_ID)
    pool.synchronize()
    ref = pool.instances()[0].ref
    pool.update(ref, expected_version=1, capacity=4, draining=True)
    store.close()
    reopened = SQLiteResourceStore(tmp_path / "instances.sqlite3")
    try:
        restored = ResourcePlane(store=reopened).runtime(ref.resource_id)
        assert restored.agent_registration == ref and restored.capacity == 4 and restored.draining
    finally:
        reopened.close()


@pytest.mark.parametrize("cut", ["before_write", "after_commit"])
def test_failed_fact_publication_never_replaces_the_current_implementation(pool, monkeypatch, cut):
    previous, = pool.registry.registrations()
    publish = pool.resource_plane.register_agent_instance
    orphan_refs = []

    def failing(ref, *args, **kwargs):
        if cut == "after_commit":
            publish(ref, *args, **kwargs)
            orphan_refs.append(ref)
        raise RuntimeError("injected publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(pool.resource_plane, "register_agent_instance", failing)
        with pytest.raises(RuntimeError, match="publication failure"):
            pool.register_instance(_agent(), instance_id=previous.ref.instance_id,
                                   expected_generation=previous.ref.generation)
    assert pool.registry.resolve_registration(previous.ref) is previous.implementation
    assert [item.ref for item in pool.instances()] == [previous.ref]
    current = pool.register_instance(_agent(), instance_id=previous.ref.instance_id,
                                    expected_generation=previous.ref.generation)
    assert current.generation >= previous.ref.generation + 2
    assert current not in orphan_refs


def test_two_sqlite_connections_cas_the_entire_profile_without_lost_fields(pool, tmp_path):
    path = tmp_path / "shared.sqlite3"
    first, second = SQLiteResourceStore(path), SQLiteResourceStore(path)
    ref = pool.instances()[0].ref
    profile = pool.describe(ref).resource
    snapshot = RuntimeSnapshot(runtimeId=ref.resource_id, availableSlots=profile.capacity, utilization=0)
    first.register(profile, snapshot)
    barrier = Barrier(2)

    def change(store, field):
        before = store.get_profile(ref.resource_id)
        barrier.wait(timeout=3)
        try:
            updated = before.model_copy(update={field: field == "draining", "version": before.version + 1})
            store.update_profile(updated, expected_profile=before)
            return field
        except VersionConflict:
            return None

    try:
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda item: change(*item), ((first, "draining"), (second, "enabled"))))
        assert sum(item is not None for item in results) == 1
        assert first.get_profile(ref.resource_id) == second.get_profile(ref.resource_id)
        assert first.get_profile(ref.resource_id).version == profile.version + 1
        winner = next(item for item in results if item is not None)
        current = first.get_profile(ref.resource_id)
        assert current.draining == (winner == "draining")
        assert current.enabled == (winner == "draining")
    finally:
        first.close()
        second.close()


def test_legacy_resource_payload_and_registration_fingerprint_remain_compatible():
    profile = RuntimeProfile(runtimeId="legacy", nodeId="node", capabilities=["analysis"], capacity=3,
                             enabled=False, ownerScope="owner")
    legacy = profile.model_dump(by_alias=True, mode="json")
    for key in ("agentRegistration", "hostRuntimeId", "draining"):
        legacy.pop(key)
    restored = RuntimeProfile.model_validate(legacy)
    assert restored.kind is RuntimeKind.EXECUTION_BACKEND
    assert restored.capacity == 3 and not restored.enabled and restored.owner_scope == "owner"
    assert restored.agent_registration is None and not restored.draining
    legacy.pop("version")
    fingerprint = hashlib.sha256(json.dumps(legacy, ensure_ascii=False, sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()[:16]
    assert compute_registration_id("legacy", "owner", restored) == f"owner:legacy:{fingerprint}"


def test_instance_view_reads_current_host_and_node_without_promoting_instance_health(pool):
    ref = pool.instances()[0].ref
    plane = pool.resource_plane
    plane.set_runtime_enabled(EMBEDDED_AGENTS_RUNTIME_ID, enabled=False)
    plane.set_node_enabled(plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID).node_id, enabled=False)
    current = pool.describe(ref)
    assert not current.host.enabled and not current.host_node.enabled
    assert current.resource.enabled and not current.health.healthy
    # Administrative draining is still possible on a disabled host.
    assert pool.update(ref, expected_version=1, draining=True).draining


def test_concurrent_first_projection_preserves_the_winners_administrative_changes(pool, monkeypatch):
    ref = pool.registry.register_instance(_agent("2"), instance_id="new")
    original = pool.resource_plane.store.register

    def competing_writer(profile, snapshot):
        result = original(profile, snapshot)
        if profile.runtime_id == ref.resource_id:
            pool.resource_plane.set_agent_instance_state(ref, expected_version=1, capacity=4,
                                                        enabled=False, draining=True)
            raise ValueError("concurrent registration won")
        return result

    monkeypatch.setattr(pool.resource_plane.store, "register", competing_writer)
    pool.synchronize()
    current = pool.describe(ref)
    assert current.capacity == 4 and current.draining and not current.resource.enabled


def test_sqlite_restart_keeps_old_facts_separate_from_the_new_registry_epoch(tmp_path):
    resource_path, health_path = tmp_path / "resources.sqlite3", tmp_path / "health.sqlite3"
    store, health_store = SQLiteResourceStore(resource_path), SQLiteResourceHealthStore(health_path)
    first_registry = AgentRegistry()
    first_registry.register(_agent())
    plane = ResourcePlane(store=store, health_monitor=ResourceHealthMonitor(store=health_store))
    register_embedded_agents_runtime(plane, first_registry.all())
    first = AgentPool(registry=first_registry, resource_plane=plane, host_runtime_id=EMBEDDED_AGENTS_RUNTIME_ID)
    first.synchronize()
    old = first.instances()[0].ref
    heartbeat = first.heartbeat(old)
    first.update(old, expected_version=1, draining=True, capacity=4)
    store.close()
    health_store.close()

    reopened_store, reopened_health = SQLiteResourceStore(resource_path), SQLiteResourceHealthStore(health_path)
    try:
        registry = AgentRegistry()
        registry.register(_agent())
        restored = ResourcePlane(store=reopened_store, health_monitor=ResourceHealthMonitor(store=reopened_health))
        register_embedded_agents_runtime(restored, registry.all())
        second = AgentPool(registry=registry, resource_plane=restored, host_runtime_id=EMBEDDED_AGENTS_RUNTIME_ID)
        second.synchronize()
        current, = second.instances()
        assert current.ref.registry_id != old.registry_id
        assert current.ref.generation == old.generation == 1
        assert not current.health.healthy
        assert restored.runtime(old.resource_id).capacity == 4
        assert restored.runtime(old.resource_id).draining
        with pytest.raises(AgentNotFound):
            second.heartbeat(old)
        expired = restored.health_monitor.health(old.resource_id, now=heartbeat.last_heartbeat + timedelta(seconds=61))
        assert not expired.healthy
    finally:
        reopened_store.close()
        reopened_health.close()
