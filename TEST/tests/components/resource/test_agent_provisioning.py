from datetime import datetime, timedelta, timezone

import pytest

from components.marketplace.infrastructure import InMemoryInstallationJobs
from components.resource.application.resource_plane import ResourcePlane
from components.resource.runtime.embedded_runtime import (
    EMBEDDED_AGENTS_RUNTIME_ID,
    register_embedded_agents_runtime,
    refresh_embedded_agents_runtime,
)
from components.resource.scheduler.leases import InMemoryLeaseCoordinator
from service.agents import AgentOutput, AgentProfile, AgentRegistry, BaseAgent
from service.agents.pool import AgentPool
from service.agents.provisioning import AgentProvisioner


class _Agent(BaseAgent):
    async def run(self, context):
        return AgentOutput(output={})


def _agent():
    return _Agent(AgentProfile(
        agentName="analyst", agentId="analyst", domain="general",
        capabilities=["analysis"], definitionVersion="1", capacity=2,
    ))


@pytest.fixture
def setup():
    registry = AgentRegistry()
    seed = _agent()
    registry.register(seed)
    plane = ResourcePlane()
    register_embedded_agents_runtime(plane, registry.all())
    pool = AgentPool(registry=registry, resource_plane=plane, host_runtime_id=EMBEDDED_AGENTS_RUNTIME_ID)
    pool.synchronize()
    jobs = InMemoryInstallationJobs()
    coordinator = InMemoryLeaseCoordinator()
    refresh = lambda: refresh_embedded_agents_runtime(plane, registry)
    provisioner = AgentProvisioner(
        pool=pool, jobs=jobs, coordinator=coordinator, refresh_runtime=refresh,
    )
    provisioner.register_agent_template("analyst", seed=seed, factory=_agent, max_instances=2)
    return provisioner, pool, jobs, coordinator


def test_provision_is_idempotent_and_publishes_disabled_then_ready_instance(setup):
    provisioner, pool, jobs, _ = setup
    job = provisioner.provision("analyst", "request-1")
    assert job.status.value == "running"
    assert provisioner.provision("analyst", "request-1").job_id == job.job_id
    instance = next(item for item in pool.instances() if item.ref.resource_id == job.runtime_id)
    assert instance.resource.enabled and not instance.resource.draining and instance.health.healthy
    assert len(provisioner.instances()) == 1
    assert pool.resource_plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID).capacity == 4


def test_stop_drains_and_uninstall_waits_for_active_lease(setup):
    provisioner, pool, jobs, coordinator = setup
    job = provisioner.provision("analyst", "request-2")
    ref = next(item.ref for item in pool.instances() if item.ref.resource_id == job.runtime_id)
    lease = coordinator.acquire(
        lease_id="lease-1", resource_id=ref.resource_id, capacity=2,
        run_id="run", step_id="step", attempt_id="attempt", slot_count=1,
        ttl=timedelta(minutes=1), now=datetime.now(timezone.utc),
    )
    assert lease is not None
    stopped = provisioner.stop(job.job_id)
    assert stopped.status.value == "stopped"
    assert pool.resource_plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID).capacity == 2
    with pytest.raises(ValueError, match="active or unknown"):
        provisioner.uninstall(job.job_id)
    coordinator.release(lease.lease_id)
    removed = provisioner.uninstall(job.job_id)
    assert removed.status.value == "removed"
    with pytest.raises(KeyError):
        pool.resource_plane.runtime(ref.resource_id)


def test_template_capacity_and_untrusted_factory_are_rejected(setup):
    provisioner, _, _, _ = setup
    provisioner.provision("analyst", "request-3")
    provisioner.provision("analyst", "request-4")
    with pytest.raises(ValueError, match="capacity exhausted"):
        provisioner.provision("analyst", "request-5")

    seed = provisioner.pool.registry.resolve_by_id("analyst")
    with pytest.raises(ValueError, match="cannot be redefined"):
        provisioner.register_agent_template("analyst", seed=seed, factory=lambda: seed)


def test_existing_object_and_definition_drift_never_modify_or_dispose_seed(setup):
    provisioner, pool, jobs, _ = setup
    seed = pool.registry.resolve_by_id("analyst")
    original = seed.profile.model_copy(deep=True)
    disposed = []
    seed.close = lambda: disposed.append(seed)
    provisioner.register_agent_template("existing", seed=seed, factory=lambda: seed)
    assert provisioner.provision("existing", "one").status.value == "failed"
    assert seed.profile == original and disposed == []

    def wrong_definition():
        agent = _agent()
        agent.profile.capabilities.append("unapproved")
        agent.close = lambda: disposed.append(agent)
        return agent

    provisioner.register_agent_template("drift", seed=seed, factory=wrong_definition)
    failed = provisioner.provision("drift", "one")
    assert failed.status.value == "failed" and len(disposed) == 1
    assert len(pool.instances()) == 1
    assert provisioner.uninstall(failed.job_id).status.value == "removed"


def test_health_or_dependency_failure_cleans_only_new_disabled_instance(setup):
    provisioner, pool, _, _ = setup
    seed = pool.registry.resolve_by_id("analyst")
    seen = []

    def unhealthy(agent):
        ref = pool.registry.registration_for(agent)
        seen.append(pool.describe(ref).resource.enabled)
        return False

    provisioner.register_agent_template("unhealthy", seed=seed, factory=_agent, health_check=unhealthy)
    failed = provisioner.provision("unhealthy", "one")
    assert failed.status.value == "failed" and seen == [False]
    assert len(pool.instances()) == 1
    assert len(pool.resource_plane.runtimes()) == 2  # host and seed

    provisioner.register_agent_template("dependency", seed=seed, factory=_agent, dependencies=["missing"])
    assert provisioner.provision("dependency", "one").status.value == "failed"
    assert len(pool.instances()) == 1


def test_committed_job_ack_loss_reads_back_running_without_compensation(setup, monkeypatch):
    provisioner, pool, jobs, _ = setup
    update = jobs.update

    def lose_running_ack(job):
        result = update(job)
        if job.status.value == "running":
            raise RuntimeError("lost ACK")
        return result

    monkeypatch.setattr(jobs, "update", lose_running_ack)
    job = provisioner.provision("analyst", "lost-job-ack")
    assert job.status.value == "running"
    assert pool.resource_plane.runtime(job.runtime_id).enabled


def test_disabled_fact_ack_loss_cleans_orphan_without_touching_seed(setup, monkeypatch):
    provisioner, pool, _, _ = setup
    publish = pool.resource_plane.register_agent_instance

    def lose_fact_ack(*args, **kwargs):
        publish(*args, **kwargs)
        raise RuntimeError("lost fact ACK")

    monkeypatch.setattr(pool.resource_plane, "register_agent_instance", lose_fact_ack)
    assert provisioner.provision("analyst", "lost-fact-ack").status.value == "failed"
    assert len(pool.registry.registrations()) == 1
    assert len(pool.resource_plane.runtimes()) == 2


def test_enabled_ack_loss_with_active_work_drains_but_does_not_dispose(setup, monkeypatch):
    provisioner, pool, _, coordinator = setup
    disposed = []
    seed = pool.registry.resolve_by_id("analyst")

    def factory():
        agent = _agent()
        agent.close = lambda: disposed.append(agent)
        return agent

    provisioner.register_agent_template("uncertain", seed=seed, factory=factory)
    update = pool.update

    def lose_enabled_ack(ref, **kwargs):
        result = update(ref, **kwargs)
        if kwargs.get("enabled") is True:
            coordinator.acquire(lease_id="active", resource_id=ref.resource_id, capacity=2,
                run_id="run", step_id="step", attempt_id="attempt", now=datetime.now(timezone.utc))
            raise RuntimeError("lost enabled ACK")
        return result

    monkeypatch.setattr(pool, "update", lose_enabled_ack)
    failed = provisioner.provision("uncertain", "one")
    assert failed.status.value == "failed"
    resource = pool.resource_plane.runtime(failed.runtime_id)
    assert resource.draining and not resource.enabled and disposed == []
    coordinator.release("active")
    assert provisioner.uninstall(failed.job_id).status.value == "removed"
    assert len(disposed) == 1


def test_unknown_marker_survives_lease_expiry_and_blocks_reenable_and_removal(setup):
    provisioner, pool, _, coordinator = setup
    job = provisioner.provision("analyst", "unknown")
    ref = next(item.ref for item in pool.instances() if item.ref.resource_id == job.runtime_id)
    pool.resource_plane.quarantine_agent_instance(ref)
    assert coordinator.active_slots(ref.resource_id) == 0
    provisioner.stop(job.job_id)
    with pytest.raises(ValueError, match="active or unknown"):
        provisioner.uninstall(job.job_id)
    current = pool.describe(ref)
    with pytest.raises(ValueError, match="requires reconciliation"):
        pool.update(ref, expected_version=current.resource.version, enabled=True, draining=False)


def test_restart_does_not_reuse_durable_running_job_as_live_instance(setup):
    provisioner, pool, jobs, coordinator = setup
    job = provisioner.provision("analyst", "restart")
    registry = AgentRegistry()
    seed = _agent()
    registry.register(seed)
    fresh = AgentProvisioner(pool=AgentPool(registry=registry, resource_plane=pool.resource_plane,
        host_runtime_id=EMBEDDED_AGENTS_RUNTIME_ID), jobs=jobs, coordinator=coordinator)
    fresh.register_agent_template("analyst", seed=seed, factory=_agent)
    with pytest.raises(ValueError, match="requires reconciliation"):
        fresh.provision("analyst", "restart")
    item, = fresh.instances()
    assert item["jobId"] == job.job_id and not item["callable"] and item["reconciliationRequired"]
    with pytest.raises(ValueError, match="shared local pool"):
        provisioner.provision("analyst", "tenant", owner_scope="tenant-a")
