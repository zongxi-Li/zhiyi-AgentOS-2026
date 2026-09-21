from datetime import datetime, timezone

import pytest

from adapters.local_runtime import LocalRuntimeClient
from contracts.capability import CapabilityInvocation
from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionResult,
)


class FakeTransport:
    def __init__(self, mismatch=False):
        self.request = None
        self.mismatch = mismatch

    async def execute(self, request):
        self.request = request
        now = datetime.now(timezone.utc)
        return LocalRuntimeExecutionResult(
            requestId="wrong" if self.mismatch else request.request_id,
            invocationId=request.invocation_id,
            status="completed", output={"ok": True}, startedAt=now, completedAt=now,
        )


def arguments():
    return {
        "resource_id": "local-worker-1",
        "authorization": LocalRuntimeAuthorizationRef(grantId="grant-1", workspaceId="ws-1"),
        "limits": LocalRuntimeExecutionLimits(
            timeoutSeconds=5, maxStdoutBytes=100, maxStderrBytes=100
        ),
        "idempotency_key": "attempt-1",
    }


@pytest.mark.asyncio
async def test_client_maps_capability_invocation_without_agent_run_context():
    transport = FakeTransport()
    invocation = CapabilityInvocation(
        invocationId="inv-1", capabilityId="fs.read", input={"path": "README.md"}
    )
    result = await LocalRuntimeClient(transport).execute(invocation, **arguments())
    assert result.output == {"ok": True}
    assert transport.request.invocation_id == invocation.invocation_id
    assert transport.request.capability_id.value == invocation.capability_id
    assert transport.request.authorization.grant_id == "grant-1"
    assert transport.request.input == invocation.input


@pytest.mark.asyncio
async def test_client_rejects_mismatched_result():
    with pytest.raises(ValueError, match="correlation"):
        await LocalRuntimeClient(FakeTransport(mismatch=True)).execute(
            CapabilityInvocation(invocationId="inv-1", capabilityId="fs.list"), **arguments()
        )
