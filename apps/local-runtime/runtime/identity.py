"""Public identity advertised by the independent Local Runtime process."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.local_runtime import LOCAL_RUNTIME_PROTOCOL_VERSION, LocalRuntimeCapability


@dataclass(frozen=True)
class LocalRuntimeIdentity:
    runtime_id: str
    resource_id: str
    version: str = "0.1.0"
    protocol_version: str = LOCAL_RUNTIME_PROTOCOL_VERSION
    capabilities: tuple[str, ...] = (
        LocalRuntimeCapability.FS_READ.value,
        LocalRuntimeCapability.FS_LIST.value,
        LocalRuntimeCapability.FS_WRITE.value,
        LocalRuntimeCapability.FS_PATCH.value,
    )

    def __post_init__(self) -> None:
        if not self.runtime_id.strip() or not self.resource_id.strip():
            raise ValueError("runtime_id and resource_id are required")
        if self.protocol_version != LOCAL_RUNTIME_PROTOCOL_VERSION:
            raise ValueError("unsupported local runtime protocol version")
        if any(capability == LocalRuntimeCapability.SHELL_EXEC.value for capability in self.capabilities):
            raise ValueError("shell.exec must not be advertised by the MVP runtime")

    def health_payload(self, *, running: bool) -> dict[str, object]:
        """Return non-sensitive health data; never include grants or credentials."""
        return {
            "runtimeId": self.runtime_id,
            "resourceId": self.resource_id,
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "status": "online" if running else "offline",
            "capabilities": list(self.capabilities),
            "availableSlots": 1 if running else 0,
            "utilization": 0.0,
        }


__all__ = ["LocalRuntimeIdentity"]
