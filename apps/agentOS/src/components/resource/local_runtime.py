"""Local Runtime 的资源平面注册与健康投影。

Local Runtime 是新资源模型的第一个真实实例：一个 Device Node 承载一个
EXECUTION_BACKEND Runtime，后者暴露 filesystem / shell 执行能力。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Protocol

from contracts.local_runtime import LOCAL_RUNTIME_PROTOCOL_VERSION, LocalRuntimeCapability
from contracts.resource import (
    HealthStatus,
    Placement,
    ResourceEndpoint,
    RuntimeKind,
    RuntimeProfile,
    RuntimeSnapshot,
    TrustLevel,
)

from .service import IssuedResourceCredential, ResourcePlane


LOCAL_RUNTIME_RESOURCE_CAPABILITIES: tuple[str, ...] = (
    LocalRuntimeCapability.FS_READ.value,
    LocalRuntimeCapability.FS_LIST.value,
    LocalRuntimeCapability.FS_WRITE.value,
    LocalRuntimeCapability.FS_PATCH.value,
)
LOCAL_RUNTIME_SHELL_CAPABILITY = LocalRuntimeCapability.SHELL_EXEC.value

DEFAULT_LOCAL_RUNTIME_NODE_ID = "node:device:local"


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
    node_id: str = DEFAULT_LOCAL_RUNTIME_NODE_ID

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
    profile: RuntimeProfile
    credential: IssuedResourceCredential | None


def local_runtime_node_id(config: LocalRuntimeResourceConfig) -> str:
    return config.node_id


def local_runtime_profile(config: LocalRuntimeResourceConfig) -> RuntimeProfile:
    """构建宿主 Local Runtime 的 EXECUTION_BACKEND 画像。"""
    capabilities = list(config.capabilities)
    if config.shell_exec_enabled:
        capabilities.append(LOCAL_RUNTIME_SHELL_CAPABILITY)
    return RuntimeProfile(
        runtimeId=config.resource_id,
        kind=RuntimeKind.EXECUTION_BACKEND,
        displayName="Local Runtime",
        nodeId=config.node_id,
        placement=Placement.DEVICE,
        capabilities=capabilities,
        trust=TrustLevel.HOST_TRUSTED,
        ownerScope=config.owner_scope,
        endpoint=ResourceEndpoint(
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
            "managedBy": "bootstrap",
        },
    )


def ensure_local_runtime_resource(
    plane: ResourcePlane,
    config: LocalRuntimeResourceConfig,
) -> RegisteredLocalRuntimeResource:
    """登记 Device Node 与其承载的 Local Runtime，并校验既有凭据一致。"""
    plane.ensure_node(
        config.node_id,
        placement=Placement.DEVICE,
        display_name="本机设备节点",
        trust=TrustLevel.HOST_TRUSTED,
    )
    profile = local_runtime_profile(config)
    snapshot = RuntimeSnapshot(
        runtimeId=config.resource_id,
        availableSlots=config.capacity,
        utilization=0.0,
        healthStatus=HealthStatus.UNKNOWN,
    )
    credential_id, secret = plane.current_signing_credential_or_none(config.resource_id)
    if credential_id is None:
        issued = plane.register_remote_runtime(
            profile,
            snapshot,
            credential_id=config.credential_id,
            secret=config.credential_secret,
        )
        return RegisteredLocalRuntimeResource(profile=profile, credential=issued)
    if config.credential_id is not None and credential_id != config.credential_id:
        raise ValueError(f"local runtime credential does not match configured bootstrap: {config.resource_id}")
    plane.register_runtime(profile, snapshot)
    return RegisteredLocalRuntimeResource(
        profile=profile,
        credential=IssuedResourceCredential(
            resource_id=config.resource_id,
            credential_id=credential_id,
            owner_scope=profile.owner_scope or "",
            secret=secret or "",
        ),
    )


class LocalRuntimeHealthProjector:
    """把 Local Runtime 的健康观测投影进资源平面。"""

    def __init__(self, plane: ResourcePlane, resource_id: str) -> None:
        self.plane = plane
        self.resource_id = resource_id

    async def refresh(self, transport: LocalRuntimeHealthTransport) -> bool:
        started = time.perf_counter()
        try:
            payload = await transport.health()
            profile = self.plane.runtime(self.resource_id)
            if not self._valid_health_payload(payload, profile):
                self.plane.set_runtime_health(self.resource_id, healthy=False)
                return False
            current = self.plane.runtime_snapshot(self.resource_id)
            now = datetime.now(timezone.utc)
            self.plane.observe_remote_runtime(
                self.resource_id,
                available_slots=int(payload.get("availableSlots") or profile.capacity),
                utilization=float(payload.get("utilization") or 0.0),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                observed_at=now,
                observation_sequence=current.snapshot.observation_sequence + 1,
            )
            # Local Runtime 应答即证明宿主设备节点在线。
            self.plane.heartbeat_node(profile.node_id, observed_at=now)
            return True
        except Exception:
            try:
                self.plane.set_runtime_health(self.resource_id, healthy=False)
            except KeyError:
                pass
            return False

    @staticmethod
    def _valid_health_payload(payload: dict[str, Any], profile: RuntimeProfile) -> bool:
        capabilities = set(payload.get("capabilities") or [])
        available_slots = payload.get("availableSlots")
        utilization = payload.get("utilization")
        return (
            payload.get("resourceId") == profile.runtime_id
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
    "DEFAULT_LOCAL_RUNTIME_NODE_ID",
    "LOCAL_RUNTIME_RESOURCE_CAPABILITIES",
    "LOCAL_RUNTIME_SHELL_CAPABILITY",
    "LocalRuntimeHealthProjector",
    "LocalRuntimeResourceConfig",
    "RegisteredLocalRuntimeResource",
    "ensure_local_runtime_resource",
    "local_runtime_node_id",
    "local_runtime_profile",
]
