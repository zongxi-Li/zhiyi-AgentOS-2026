"""Authorized execution pipeline for the independent Local Runtime."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from contracts.local_runtime import (
    LOCAL_RUNTIME_PROTOCOL_VERSION,
    LocalRuntimeExecutionRequest,
    LocalRuntimeExecutionResult,
    LocalRuntimeCapability,
)

from capabilities import CapabilityDispatcher
from runtime.errors import LocalRuntimeError
from grants import GrantAuthorizationService
from process import ProcessExecutionRequest, ProcessExecutionService


class LocalRuntimeExecutor:
    def __init__(
        self,
        *,
        resource_id: str,
        authorizer: GrantAuthorizationService,
        dispatcher: CapabilityDispatcher,
        process_service: ProcessExecutionService | None = None,
    ) -> None:
        self.resource_id = str(resource_id).strip()
        if not self.resource_id:
            raise ValueError("resource_id must not be empty")
        self.authorizer = authorizer
        self.dispatcher = dispatcher
        self.process_service = process_service

    async def execute(self, request: LocalRuntimeExecutionRequest) -> LocalRuntimeExecutionResult:
        started_at = datetime.now(timezone.utc)
        try:
            if request.protocol_version != LOCAL_RUNTIME_PROTOCOL_VERSION:
                raise LocalRuntimeError("PROTOCOL_VERSION_UNSUPPORTED", "protocol version is unsupported")
            if request.resource_id != self.resource_id:
                raise LocalRuntimeError("RESOURCE_MISMATCH", "request resource does not match runtime")
            authorized = self.authorizer.authorize(
                request.authorization,
                request.capability_id,
            )
            if request.capability_id is LocalRuntimeCapability.SHELL_EXEC:
                if self.process_service is None:
                    raise LocalRuntimeError(
                        "CAPABILITY_NOT_IMPLEMENTED",
                        "requested local runtime capability is not implemented",
                    )
                try:
                    process_request = ProcessExecutionRequest.model_validate(request.input)
                except Exception as exc:
                    raise LocalRuntimeError(
                        "PROCESS_REQUEST_INVALID",
                        "process execution request is invalid",
                    ) from exc
                execution_id = self.process_service.start(
                    process_request,
                    root=authorized.canonical_root,
                    request_id=request.request_id,
                    invocation_id=request.invocation_id,
                    resource_id=request.resource_id,
                    limits=request.limits,
                )
                return LocalRuntimeExecutionResult(
                    protocolVersion=LOCAL_RUNTIME_PROTOCOL_VERSION,
                    requestId=request.request_id,
                    invocationId=request.invocation_id,
                    status="accepted",
                    output={"executionId": execution_id, "state": "running"},
                    startedAt=started_at,
                    completedAt=datetime.now(timezone.utc),
                )
            try:
                output = await asyncio.wait_for(
                    self.dispatcher.execute(
                        request.capability_id,
                        root=authorized.canonical_root,
                        arguments=request.input,
                    ),
                    timeout=request.limits.timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise LocalRuntimeError(
                    "EXECUTION_TIMEOUT",
                    "local runtime execution timed out",
                    retryable=True,
                ) from exc
            return LocalRuntimeExecutionResult(
                requestId=request.request_id,
                invocationId=request.invocation_id,
                status="completed",
                output=output,
                startedAt=started_at,
                completedAt=datetime.now(timezone.utc),
            )
        except LocalRuntimeError as exc:
            return self._failed(request, started_at, exc)
        except Exception:
            # Never expose raw exceptions, command text, paths, or environment data.
            return self._failed(
                request,
                started_at,
                LocalRuntimeError("INTERNAL_ERROR", "local runtime execution failed"),
            )

    @staticmethod
    def _failed(
        request: LocalRuntimeExecutionRequest,
        started_at: datetime,
        error: LocalRuntimeError,
    ) -> LocalRuntimeExecutionResult:
        return LocalRuntimeExecutionResult(
            requestId=request.request_id,
            invocationId=request.invocation_id,
            status="failed",
            error=error.to_contract(),
            startedAt=started_at,
            completedAt=datetime.now(timezone.utc),
        )


__all__ = ["LocalRuntimeExecutor"]
