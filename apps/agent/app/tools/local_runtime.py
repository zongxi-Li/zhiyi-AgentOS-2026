"""Chat-facing adapter for the AgentOS-owned Local Runtime boundary.

This module deliberately contains no filesystem implementation and no transport
construction.  The composition root injects the existing ResourceService,
LocalRuntimeClient, health projector, and a server-issued authorization
reference.  Model arguments remain business arguments only.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from adapters.local_runtime import LocalRuntimeClient
from components.resource.local_runtime import LocalRuntimeHealthTransport, LocalRuntimeHealthProjector
from components.resource.service import ResourceService
from contracts.capability import CapabilityInvocation
from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeCapability,
    LocalRuntimeExecutionLimits,
)
from contracts.resource import DeploymentTier, ResourceType

from app.tools.contracts import ToolPayload


TOOL_CAPABILITIES: dict[str, LocalRuntimeCapability] = {
    "read_file": LocalRuntimeCapability.FS_READ,
    "list_files": LocalRuntimeCapability.FS_LIST,
    "write_file": LocalRuntimeCapability.FS_WRITE,
    "patch_file": LocalRuntimeCapability.FS_PATCH,
}

_SAFE_RELATIVE_PATH = re.compile(r"^(?![\\/])(?!(?:[A-Za-z]:)).{1,4096}$")


class LocalRuntimeToolError(RuntimeError):
    """Safe error returned to Chat when the Local Runtime cannot execute."""

    def __init__(self, code: str, message: str, *, activity: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.activity = activity


class LocalRuntimeToolExecutor:
    """Translate Chat tool calls into existing AgentOS capability invocations."""

    def __init__(
        self,
        *,
        resource_service: ResourceService,
        client: LocalRuntimeClient,
        health_projector: LocalRuntimeHealthProjector,
        health_transport: LocalRuntimeHealthTransport,
        resource_id: str,
        authorization: LocalRuntimeAuthorizationRef,
        limits: LocalRuntimeExecutionLimits | None = None,
    ) -> None:
        self.resource_service = resource_service
        self.client = client
        self.health_projector = health_projector
        self.health_transport = health_transport
        self.resource_id = str(resource_id).strip()
        self.authorization = authorization
        self.limits = limits or LocalRuntimeExecutionLimits(
            timeoutSeconds=30.0,
            maxStdoutBytes=0,
            maxStderrBytes=0,
        )
        if not self.resource_id:
            raise ValueError("resource_id must not be empty")

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        call_id: str,
    ) -> ToolPayload:
        capability = TOOL_CAPABILITIES.get(tool_name)
        if capability is None:
            raise LocalRuntimeToolError("CAPABILITY_NOT_ALLOWED", "Chat file capability is not allowed")
        if not str(call_id or "").strip():
            raise LocalRuntimeToolError("INVOCATION_INVALID", "tool invocation is invalid")

        input_payload = self._business_input(tool_name, arguments)
        relative_path = self._safe_relative_path(input_payload.get("path"))
        activity = self._activity(tool_name, capability.value, relative_path, status="running")
        try:
            await self._ensure_healthy_candidate(capability.value)
            invocation = CapabilityInvocation(
                invocationId=str(call_id),
                capabilityId=capability.value,
                input=input_payload,
            )
            result = await self.client.execute(
                invocation,
                resource_id=self.resource_id,
                authorization=self.authorization,
                limits=self.limits,
                idempotency_key=f"chat:{call_id}",
            )
        except LocalRuntimeToolError as exc:
            if exc.activity is None:
                exc.activity = self._activity(
                    tool_name,
                    capability.value,
                    relative_path,
                    status="failed",
                    error_code=exc.code,
                )
            raise
        except Exception as exc:
            raise LocalRuntimeToolError(
                "LOCAL_RUNTIME_UNAVAILABLE",
                "Local Runtime is unavailable.",
                activity=self._activity(
                    tool_name,
                    capability.value,
                    relative_path,
                    status="failed",
                    error_code="LOCAL_RUNTIME_UNAVAILABLE",
                ),
            ) from exc

        if result.status == "failed":
            error = result.error
            code = str(error.code if error else "LOCAL_RUNTIME_FAILED")
            message = str(error.message if error else "Local Runtime execution failed.")
            raise LocalRuntimeToolError(
                code,
                message,
                activity=self._activity(
                    tool_name,
                    capability.value,
                    relative_path,
                    status="failed",
                    error_code=code,
                ),
            )

        output = result.output if isinstance(result.output, dict) else {}
        output_path = self._safe_relative_path(output.get("path")) or relative_path
        completed_activity = self._activity(
            tool_name,
            capability.value,
            output_path,
            status="completed",
            output=output,
            arguments=input_payload,
        )
        return ToolPayload(
            summary=self._summary(tool_name, output_path, output),
            data={"result": output, "activity": completed_activity},
        )

    async def _ensure_healthy_candidate(self, capability_id: str) -> None:
        try:
            healthy = await self.health_projector.refresh(self.health_transport)
        except Exception as exc:
            raise LocalRuntimeToolError(
                "LOCAL_RUNTIME_UNAVAILABLE", "Local Runtime is unavailable."
            ) from exc
        if not healthy:
            raise LocalRuntimeToolError("LOCAL_RUNTIME_UNAVAILABLE", "Local Runtime is unavailable.")
        try:
            candidates = self.resource_service.candidates([capability_id])
        except Exception as exc:
            raise LocalRuntimeToolError("LOCAL_RUNTIME_UNAVAILABLE", "Local Runtime is unavailable.") from exc
        selected = [
            candidate
            for candidate in candidates
            if candidate.profile.resource_id == self.resource_id
            and candidate.profile.resource_type is ResourceType.WORKER
            and candidate.profile.deployment_tier is DeploymentTier.TERMINAL
            and capability_id in candidate.profile.capabilities
        ]
        if not selected:
            raise LocalRuntimeToolError("LOCAL_RUNTIME_UNAVAILABLE", "Local Runtime is unavailable.")

    @staticmethod
    def _business_input(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        allowed: dict[str, tuple[str, ...]] = {
            "read_file": ("path", "encoding", "binary"),
            "list_files": ("path", "maxEntries"),
            "write_file": ("path", "content", "overwrite", "createParents", "encoding", "binary"),
            "patch_file": ("path", "patch", "encoding", "expectedSha256"),
        }[tool_name]
        return {key: arguments[key] for key in allowed if key in arguments}

    @staticmethod
    def _safe_relative_path(value: Any) -> str | None:
        path = str(value or "").strip().replace("\\", "/")
        if not path or not _SAFE_RELATIVE_PATH.match(path) or ".." in path.split("/"):
            return None
        return path

    @staticmethod
    def _activity(
        tool_name: str,
        capability_id: str,
        relative_path: str | None,
        *,
        status: str,
        error_code: str | None = None,
        output: dict[str, Any] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kind = {
            "read_file": "file_read",
            "list_files": "file_list",
            "write_file": "file_write",
            "patch_file": "file_patch",
        }[tool_name]
        activity: dict[str, Any] = {
            "kind": kind,
            "capabilityId": capability_id,
            "status": status,
        }
        if relative_path:
            activity["relativePath"] = relative_path
        if output and tool_name == "list_files" and isinstance(output.get("count"), int):
            activity["entryCount"] = output["count"]
        if output and tool_name == "write_file":
            activity["summary"] = "Updated file" if output.get("overwritten") else "Created file"
        elif tool_name == "patch_file":
            activity["summary"] = "Edited file"
            patch = str((arguments or {}).get("patch") or "")
            activity["addedLines"] = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
            activity["removedLines"] = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
        elif tool_name == "read_file":
            activity["summary"] = "Read file"
        elif tool_name == "list_files":
            activity["summary"] = "Listed directory"
        if error_code:
            activity["errorCode"] = error_code
        return activity

    @staticmethod
    def _summary(tool_name: str, path: str | None, output: dict[str, Any]) -> str:
        label = {
            "read_file": "Read",
            "list_files": "Listed",
            "write_file": "Created" if not output.get("overwritten") else "Updated",
            "patch_file": "Edited",
        }[tool_name]
        return f"{label} {path or 'workspace file'}"


__all__ = ["LocalRuntimeToolError", "LocalRuntimeToolExecutor", "TOOL_CAPABILITIES"]
