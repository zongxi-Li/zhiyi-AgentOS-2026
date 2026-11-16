"""Transport-neutral boundary from AgentOS invocations to a local runtime."""

from __future__ import annotations

from typing import AsyncIterator, Protocol
from uuid import uuid4

from contracts.capability import CapabilityInvocation
from contracts.local_runtime import (
    LOCAL_RUNTIME_PROTOCOL_VERSION,
    LocalRuntimeAuthorizationRef,
    LocalRuntimeCapability,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionRequest,
    LocalRuntimeExecutionEvent,
    LocalRuntimeExecutionResult,
)


class LocalRuntimeTransport(Protocol):
    async def execute(
        self, request: LocalRuntimeExecutionRequest
    ) -> LocalRuntimeExecutionResult: ...

    def stream_events(
        self,
        *,
        execution_id: str,
        request_id: str,
        invocation_id: str,
    ) -> AsyncIterator[LocalRuntimeExecutionEvent]: ...

    async def cancel(
        self,
        *,
        execution_id: str,
        request_id: str,
        invocation_id: str,
    ) -> str: ...

    async def workspace_root(self, authorization: LocalRuntimeAuthorizationRef) -> str: ...


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
        if (
            result.protocol_version != LOCAL_RUNTIME_PROTOCOL_VERSION
            or result.request_id != request.request_id
            or result.invocation_id != request.invocation_id
        ):
            raise ValueError("local runtime response correlation mismatch")
        return result

    async def stream_events(
        self,
        *,
        execution_id: str,
        request_id: str,
        invocation_id: str,
    ) -> AsyncIterator[LocalRuntimeExecutionEvent]:
        stream = getattr(self._transport, "stream_events", None)
        if stream is None:
            raise RuntimeError("local runtime transport does not support execution events")
        async for event in stream(
            execution_id=execution_id,
            request_id=request_id,
            invocation_id=invocation_id,
        ):
            if (
                event.protocol_version != LOCAL_RUNTIME_PROTOCOL_VERSION
                or event.request_id != request_id
                or event.invocation_id != invocation_id
                or event.execution_id != execution_id
            ):
                raise ValueError("local runtime event correlation mismatch")
            yield event

    async def cancel(
        self,
        *,
        execution_id: str,
        request_id: str,
        invocation_id: str,
    ) -> str:
        cancel = getattr(self._transport, "cancel", None)
        if cancel is None:
            raise RuntimeError("local runtime transport does not support cancellation")
        return await cancel(
            execution_id=execution_id,
            request_id=request_id,
            invocation_id=invocation_id,
        )

    async def workspace_root(self, authorization: LocalRuntimeAuthorizationRef) -> str:
        get_root = getattr(self._transport, "workspace_root", None)
        if get_root is None:
            raise RuntimeError("local runtime transport does not support workspace discovery")
        return await get_root(authorization)


__all__ = ["LocalRuntimeClient", "LocalRuntimeTransport"]
