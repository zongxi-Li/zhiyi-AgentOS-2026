"""Versioned execution envelopes for a separately authorized local runtime.

These contracts carry a grant reference, never a caller-selected host root.
The host runtime must resolve and verify the grant before any execution.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator


LOCAL_RUNTIME_PROTOCOL_VERSION = "1"


class LocalRuntimeCapability(str, Enum):
    FS_READ = "fs.read"
    FS_LIST = "fs.list"
    FS_WRITE = "fs.write"
    FS_PATCH = "fs.patch"
    SHELL_EXEC = "shell.exec"


class _Envelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class LocalRuntimeExecutionLimits(_Envelope):
    timeout_seconds: float = Field(alias="timeoutSeconds", gt=0)
    max_stdout_bytes: int = Field(alias="maxStdoutBytes", ge=0)
    max_stderr_bytes: int = Field(alias="maxStderrBytes", ge=0)


class LocalRuntimeAuthorizationRef(_Envelope):
    """Opaque identifiers issued by the system; this is not an access policy."""

    grant_id: StrictStr = Field(alias="grantId", min_length=1)
    workspace_id: StrictStr = Field(alias="workspaceId", min_length=1)


class LocalRuntimeExecutionRequest(_Envelope):
    protocol_version: Literal["1"] = Field(alias="protocolVersion")
    request_id: StrictStr = Field(alias="requestId", min_length=1)
    invocation_id: StrictStr = Field(alias="invocationId", min_length=1)
    resource_id: StrictStr = Field(alias="resourceId", min_length=1)
    capability_id: LocalRuntimeCapability = Field(alias="capabilityId")
    authorization: LocalRuntimeAuthorizationRef
    input: dict[str, Any]
    limits: LocalRuntimeExecutionLimits
    idempotency_key: StrictStr = Field(alias="idempotencyKey", min_length=1)

    @model_validator(mode="after")
    def reject_inline_authority(self) -> "LocalRuntimeExecutionRequest":
        """Paths may identify targets; they may not redefine the granted root."""
        forbidden = {"allowedroot", "allowed_root", "allowedpaths", "allowed_paths"}

        def contains_scope(value: Any) -> bool:
            if isinstance(value, Mapping):
                return any(
                    str(key).lower() in forbidden or contains_scope(item)
                    for key, item in value.items()
                )
            if isinstance(value, (list, tuple)):
                return any(contains_scope(item) for item in value)
            return False

        if contains_scope(self.input):
            raise ValueError("input cannot declare host access scope")
        return self


class LocalRuntimeExecutionError(_Envelope):
    """Producers must use a sanitized message; never copy command output/secrets."""

    code: StrictStr = Field(min_length=1)
    retryable: bool
    message: StrictStr = Field(min_length=1)


class LocalRuntimeExecutionResult(_Envelope):
    request_id: StrictStr = Field(alias="requestId", min_length=1)
    invocation_id: StrictStr = Field(alias="invocationId", min_length=1)
    status: Literal["completed", "failed"]
    output: dict[str, Any] = Field(default_factory=dict)
    error: LocalRuntimeExecutionError | None = None
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime = Field(alias="completedAt")

    @model_validator(mode="after")
    def validate_outcome(self) -> "LocalRuntimeExecutionResult":
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("failed results require an error; completed results forbid one")
        if self.completed_at < self.started_at:
            raise ValueError("completedAt must not precede startedAt")
        return self


class LocalRuntimeExecutionEvent(_Envelope):
    protocol_version: Literal["1"] = Field(alias="protocolVersion")
    request_id: StrictStr = Field(alias="requestId", min_length=1)
    invocation_id: StrictStr = Field(alias="invocationId", min_length=1)
    event_type: Literal[
        "requested", "started", "stdout", "stderr", "file_changed", "completed", "failed"
    ] = Field(alias="eventType")
    sequence: int = Field(ge=0)
    data: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "LOCAL_RUNTIME_PROTOCOL_VERSION",
    "LocalRuntimeAuthorizationRef",
    "LocalRuntimeCapability",
    "LocalRuntimeExecutionError",
    "LocalRuntimeExecutionEvent",
    "LocalRuntimeExecutionLimits",
    "LocalRuntimeExecutionRequest",
    "LocalRuntimeExecutionResult",
]
