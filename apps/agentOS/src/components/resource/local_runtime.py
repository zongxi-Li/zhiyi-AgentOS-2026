"""AgentOS Resource registration and health projection for Local Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Protocol

from contracts.local_runtime import LOCAL_RUNTIME_PROTOCOL_VERSION, LocalRuntimeCapability
from contracts.resource import (
    DeploymentTier,
    ResourceEndpoint,
    ResourceHealthStatus,
    ResourceProfile,
    ResourceSnapshot,
    ResourceType,
)

from .service import IssuedResourceCredential, ResourceService


LOCAL_RUNTIME_RESOURCE_CAPABILITIES: tuple[str, ...] = (
    LocalRuntimeCapability.FS_READ.value,
    LocalRuntimeCapability.FS_LIST.value,
    LocalRuntimeCapability.FS_WRITE.value,
    LocalRuntimeCapability.FS_PATCH.value,
)
LOCAL_RUNTIME_SHELL_CAPABILITY = LocalRuntimeCapability.SHELL_EXEC.value


class LocalRuntimeHealthTransport(Protocol):
    async def health(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LocalRuntimeResourceConfig:
    resource_id: str
    owner_scope: str
    execution_endpoint: str
    version: int = 1
    capacity: int = 1
    credential_id: str | None = None
    credential_secret: str | None = None
    capabilities: tuple[str, ...] = LOCAL_RUNTIME_RESOURCE_CAPABILITIES
    shell_exec_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.resource_id.strip() or not self.owner_scope.strip():
            raise ValueError("local runtime resource_id and owner_scope are required")
        if not self.execution_endpoint.strip():
            raise ValueError("local runtime execution_endpoint is required")
        if self.version < 1 or self.capacity < 1:
            raise ValueError("local runtime version and capacity must be positive")
        if (self.credential_id is None) != (self.credential_secret is None):
            raise ValueError("local runtime credential_id and credential_secret must be supplied together")
        normalized_capabilities = tuple(dict.fromkeys(
            str(capability).strip() for capability in self.capabilities if str(capability).strip()
        ))
        if not normalized_capabilities:
            raise ValueError("local runtime capabilities must not be empty")
        unsupported = set(normalized_capabilities) - set(LOCAL_RUNTIME_RESOURCE_CAPABILITIES)
        if unsupported:
            raise ValueError("local runtime capabilities contain unsupported values")
        object.__setattr__(self, "capabilities", normalized_capabilities)


@dataclass(frozen=True)
class RegisteredLocalRuntimeResource:
    profile: ResourceProfile
    credential: IssuedResourceCredential


def local_runtime_profile(config: LocalRuntimeResourceConfig) -> ResourceProfile:
    """Build the only advertised Resource profile for the host runtime."""
    capabilities = list(config.capabilities)
    if config.shell_exec_enabled:
        capabilities.append(LOCAL_RUNTIME_SHELL_CAPABILITY)
    return ResourceProfile(
        resourceId=config.resource_id,
        resourceType=ResourceType.WORKER,
        deploymentTier=DeploymentTier.TERMINAL,
        capabilities=capabilities,
        ownerScope=config.owner_scope,
        executionEndpoint=ResourceEndpoint(
            protocol="http",
            address=config.execution_endpoint,
            authReference=f"resource-credential:{config.resource_id}",
        ),
        capacity=config.capacity,
        enabled=True,
        version=config.version,
        metadata={
            "runtime": "zhiyi-local-runtime",
            "protocolVersion": LOCAL_RUNTIME_PROTOCOL_VERSION,
        },
    )


def ensure_local_runtime_resource(
    resource_service: ResourceService,
    config: LocalRuntimeResourceConfig,
) -> RegisteredLocalRuntimeResource:
    """Register or validate one Local Runtime through the existing ResourceService."""
    profile = local_runtime_profile(config)
    snapshot = ResourceSnapshot(
        resourceId=config.resource_id,
        availableSlots=config.capacity,
        utilization=0.0,
        healthStatus=ResourceHealthStatus.UNKNOWN,
    )
    try:
        existing = resource_service.profile(config.resource_id)
    except KeyError:
        credential = resource_service.register_remote(
            profile,
            snapshot,
            credential_id=config.credential_id,
            secret=config.credential_secret,
        )
        return RegisteredLocalRuntimeResource(profile=profile, credential=credential)
    if existing != profile:
        raise ValueError(f"local runtime resource conflicts with existing profile: {config.resource_id}")
    record = resource_service.credential(config.resource_id)
    credential_id, secret = resource_service.current_signing_credential(config.resource_id)
    if config.credential_id is not None and credential_id != config.credential_id:
        raise ValueError(f"local runtime credential does not match configured bootstrap: {config.resource_id}")
    return RegisteredLocalRuntimeResource(
        profile=existing,
        credential=IssuedResourceCredential(
            resource_id=config.resource_id,
            credential_id=credential_id,
            owner_scope=record.owner_scope,
            secret=secret,
        ),
    )


class LocalRuntimeHealthProjector:
    """Project runtime health into the existing ResourceService semantics."""

    def __init__(self, resource_service: ResourceService, resource_id: str) -> None:
        self.resource_service = resource_service
        self.resource_id = resource_id

    async def refresh(self, transport: LocalRuntimeHealthTransport) -> bool:
        started = time.perf_counter()
        try:
            payload = await transport.health()
            profile = self.resource_service.profile(self.resource_id)
            if not self._valid_health_payload(payload, profile):
                self.resource_service.set_health(self.resource_id, healthy=False)
                return False
            current = self.resource_service.snapshot(self.resource_id)
            now = datetime.now(timezone.utc)
            self.resource_service.observe_remote(
                self.resource_id,
                available_slots=int(payload.get("availableSlots") or profile.capacity),
                utilization=float(payload.get("utilization") or 0.0),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                observed_at=now,
                observation_sequence=current.snapshot.observation_sequence + 1,
            )
            return True
        except Exception:
            try:
                self.resource_service.set_health(self.resource_id, healthy=False)
            except KeyError:
                pass
            return False

    @staticmethod
    def _valid_health_payload(payload: dict[str, Any], profile: ResourceProfile) -> bool:
        capabilities = set(payload.get("capabilities") or [])
        available_slots = payload.get("availableSlots")
        utilization = payload.get("utilization")
        return (
            payload.get("resourceId") == profile.resource_id
            and payload.get("protocolVersion") == LOCAL_RUNTIME_PROTOCOL_VERSION
            and payload.get("status") == "online"
            and set(profile.capabilities).issubset(capabilities)
            and (
                LOCAL_RUNTIME_SHELL_CAPABILITY not in capabilities
                or LOCAL_RUNTIME_SHELL_CAPABILITY in profile.capabilities
            )
            and isinstance(available_slots, int)
            and not isinstance(available_slots, bool)
            and 0 <= available_slots <= profile.capacity
            and isinstance(utilization, (int, float))
            and not isinstance(utilization, bool)
            and 0.0 <= float(utilization) <= 1.0
        )


__all__ = [
    "LOCAL_RUNTIME_RESOURCE_CAPABILITIES",
    "LOCAL_RUNTIME_SHELL_CAPABILITY",
    "LocalRuntimeHealthProjector",
    "LocalRuntimeResourceConfig",
    "RegisteredLocalRuntimeResource",
    "ensure_local_runtime_resource",
    "local_runtime_profile",
]
