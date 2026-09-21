"""Transport-neutral boundary from AgentOS invocations to a local runtime."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from contracts.capability import CapabilityInvocation
from contracts.local_runtime import (
    LOCAL_RUNTIME_PROTOCOL_VERSION,
    LocalRuntimeAuthorizationRef,
    LocalRuntimeCapability,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionRequest,
    LocalRuntimeExecutionResult,
)


class LocalRuntimeTransport(Protocol):
    async def execute(
        self, request: LocalRuntimeExecutionRequest
    ) -> LocalRuntimeExecutionResult: ...


class LocalRuntimeClient:
    """Validate and delegate; grant resolution belongs to the host runtime.

    Callers must supply a system-issued authorization reference. Neither this
    client nor its request body grants access to a host directory.
    """

    def __init__(self, transport: LocalRuntimeTransport) -> None:
        self._transport = transport

    async def execute(
        self,
        invocation: CapabilityInvocation,
        *,
        resource_id: str,
        authorization: LocalRuntimeAuthorizationRef,
        limits: LocalRuntimeExecutionLimits,
        idempotency_key: str,
    ) -> LocalRuntimeExecutionResult:
        request = LocalRuntimeExecutionRequest(
            protocolVersion=LOCAL_RUNTIME_PROTOCOL_VERSION,
            requestId=str(uuid4()),
            invocationId=invocation.invocation_id,
            resourceId=resource_id,
            capabilityId=LocalRuntimeCapability(invocation.capability_id),
            authorization=authorization,
            input=invocation.input,
            limits=limits,
            idempotencyKey=idempotency_key,
        )
        result = await self._transport.execute(request)
        if result.request_id != request.request_id or result.invocation_id != request.invocation_id:
            raise ValueError("local runtime response correlation mismatch")
        return result


__all__ = ["LocalRuntimeClient", "LocalRuntimeTransport"]
