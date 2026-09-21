from __future__ import annotations

from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeCapability,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionRequest,
)


def make_request(
    capability: LocalRuntimeCapability,
    input_data: dict,
    *,
    grant_id: str = "grant_main",
    workspace_id: str = "workspace_main",
    resource_id: str = "zhiyi-local-runtime",
) -> LocalRuntimeExecutionRequest:
    return LocalRuntimeExecutionRequest(
        protocolVersion="1",
        requestId=f"request-{capability.value}",
        invocationId=f"invocation-{capability.value}",
        resourceId=resource_id,
        capabilityId=capability,
        authorization=LocalRuntimeAuthorizationRef(
            grantId=grant_id,
            workspaceId=workspace_id,
        ),
        input=input_data,
        limits=LocalRuntimeExecutionLimits(
            timeoutSeconds=10,
            maxStdoutBytes=1024,
            maxStderrBytes=1024,
        ),
        idempotencyKey=f"idempotency-{capability.value}",
    )
