from __future__ import annotations

import asyncio
from datetime import timedelta

from components.resource.local_runtime import (
    LOCAL_RUNTIME_RESOURCE_CAPABILITIES,
    LocalRuntimeHealthProjector,
    LocalRuntimeResourceConfig,
    ensure_local_runtime_resource,
)
from components.resource.service import ResourceService
from contracts.local_runtime import LocalRuntimeCapability
from contracts.resource import DeploymentTier, ResourceType


def _config() -> LocalRuntimeResourceConfig:
    return LocalRuntimeResourceConfig(
        resource_id="zhiyi-local-runtime",
        owner_scope="desktop-user",
        execution_endpoint="http://host.docker.internal:8765/v1/executions",
    )


def test_local_runtime_registers_as_worker_terminal_without_shell():
    resources = ResourceService()

    registered = ensure_local_runtime_resource(resources, _config())

    assert registered.profile.resource_type is ResourceType.WORKER
    assert registered.profile.deployment_tier is DeploymentTier.TERMINAL
    assert registered.profile.capabilities == list(LOCAL_RUNTIME_RESOURCE_CAPABILITIES)
    assert LocalRuntimeCapability.SHELL_EXEC.value not in registered.profile.capabilities
    assert registered.profile.execution_endpoint.address.endswith("/v1/executions")
    assert registered.credential.secret not in registered.profile.model_dump_json()


def test_local_runtime_can_use_out_of_band_bootstrap_credential():
    resources = ResourceService()
    config = LocalRuntimeResourceConfig(
        resource_id="zhiyi-local-runtime-bootstrap",
        owner_scope="desktop-user",
        execution_endpoint="http://host.docker.internal:8765/v1/executions",
        credential_id="bootstrap-credential",
        credential_secret="provided-out-of-band-secret",
    )

    registered = ensure_local_runtime_resource(resources, config)

    assert registered.credential.credential_id == "bootstrap-credential"
    assert registered.credential.secret == "provided-out-of-band-secret"


def test_local_runtime_registration_is_idempotent_and_uses_resource_credential_rotation():
    resources = ResourceService()
    first = ensure_local_runtime_resource(resources, _config())
    second = ensure_local_runtime_resource(resources, _config())

    assert second.profile == first.profile
    assert second.credential.credential_id == first.credential.credential_id
    assert second.credential.secret == first.credential.secret

    rotated = resources.rotate_credential(first.profile.resource_id)
    third = ensure_local_runtime_resource(resources, _config())
    assert third.credential.credential_id == rotated.credential_id
    assert third.credential.secret == rotated.secret


def test_health_projector_updates_remote_observation_and_stale_health_is_unavailable():
    resources = ResourceService(heartbeat_timeout=timedelta(seconds=1))
    registered = ensure_local_runtime_resource(resources, _config())

    class HealthyTransport:
        async def health(self):
            return {
                "runtimeId": "runtime-test",
                "resourceId": registered.profile.resource_id,
                "protocolVersion": "1",
                "status": "online",
                "capabilities": list(LOCAL_RUNTIME_RESOURCE_CAPABILITIES),
                "availableSlots": 1,
                "utilization": 0.0,
            }

    projector = LocalRuntimeHealthProjector(resources, registered.profile.resource_id)
    assert asyncio.run(projector.refresh(HealthyTransport())) is True
    assert resources.health_monitor.health(registered.profile.resource_id).healthy is True
    state = resources.health_monitor.store.get(registered.profile.resource_id)
    assert state is not None and state.last_heartbeat is not None
    stale = resources.health_monitor.health(
        registered.profile.resource_id,
        now=state.last_heartbeat + timedelta(seconds=2),
    )
    assert stale.healthy is False


def test_health_projector_rejects_wrong_identity_and_forces_offline():
    resources = ResourceService()
    registered = ensure_local_runtime_resource(resources, _config())

    class WrongRuntime:
        async def health(self):
            return {
                "resourceId": "another-runtime",
                "protocolVersion": "1",
                "status": "online",
                "capabilities": list(LOCAL_RUNTIME_RESOURCE_CAPABILITIES),
            }

    projector = LocalRuntimeHealthProjector(resources, registered.profile.resource_id)
    assert asyncio.run(projector.refresh(WrongRuntime())) is False
    assert resources.health_monitor.health(registered.profile.resource_id).healthy is False
