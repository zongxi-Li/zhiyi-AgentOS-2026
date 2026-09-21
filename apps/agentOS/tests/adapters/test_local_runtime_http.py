from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import httpx
import pytest

from adapters.local_runtime_http import (
    HttpLocalRuntimeTransport,
    LocalRuntimeTransportError,
)
from components.resource.auth import build_resource_signature
from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeCapability,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionRequest,
)


class CredentialProvider:
    def current_signing_credential(self, resource_id: str) -> tuple[str, str]:
        assert resource_id == "zhiyi-local-runtime"
        return "credential-1", "secret-1"


def _request() -> LocalRuntimeExecutionRequest:
    return LocalRuntimeExecutionRequest(
        protocolVersion="1",
        requestId="request-1",
        invocationId="invocation-1",
        resourceId="zhiyi-local-runtime",
        capabilityId=LocalRuntimeCapability.FS_READ,
        authorization=LocalRuntimeAuthorizationRef(grantId="grant-1", workspaceId="workspace-1"),
        input={"path": "README.md"},
        limits=LocalRuntimeExecutionLimits(timeoutSeconds=5, maxStdoutBytes=1024, maxStderrBytes=1024),
        idempotencyKey="idempotency-1",
    )


def _result(request: LocalRuntimeExecutionRequest, *, request_id: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "requestId": request_id or request.request_id,
        "invocationId": request.invocation_id,
        "status": "completed",
        "output": {"content": "ok"},
        "startedAt": now,
        "completedAt": now,
    }


@pytest.mark.asyncio
async def test_http_transport_signs_request_and_validates_correlation():
    request = _request()
    captured: dict[str, object] = {}

    async def handler(incoming: httpx.Request) -> httpx.Response:
        captured["path"] = incoming.url.path
        captured["body"] = incoming.content
        captured["headers"] = dict(incoming.headers)
        headers = incoming.headers
        expected = build_resource_signature(
            "secret-1",
            method="POST",
            path=incoming.url.path,
            timestamp=int(headers["x-resource-timestamp"]),
            nonce=headers["x-resource-nonce"],
            body=incoming.content,
        )
        assert headers["x-resource-signature"] == expected
        assert headers["idempotency-key"] == request.idempotency_key
        return httpx.Response(200, json=_result(request), request=incoming)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://runtime.test",
    )
    transport = HttpLocalRuntimeTransport(
        resource_id="zhiyi-local-runtime",
        address="http://runtime.test/v1/executions",
        credential_provider=CredentialProvider(),
        client=client,
    )
    try:
        result = await transport.execute(request)
    finally:
        await client.aclose()
    assert result.request_id == request.request_id
    assert result.invocation_id == request.invocation_id
    assert captured["path"] == "/v1/executions"


@pytest.mark.asyncio
async def test_http_transport_distinguishes_auth_failure_and_unavailable():
    request = _request()

    async def unauthorized(incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "AUTHENTICATION_FAILED", "message": "authentication failed"}},
            request=incoming,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(unauthorized), base_url="http://runtime.test")
    transport = HttpLocalRuntimeTransport(
        resource_id=request.resource_id,
        address="http://runtime.test/v1/executions",
        credential_provider=CredentialProvider(),
        client=client,
    )
    with pytest.raises(LocalRuntimeTransportError) as unauthorized_error:
        await transport.execute(request)
    assert unauthorized_error.value.code == "AUTHENTICATION_FAILED"

    async def unavailable(incoming: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=incoming)

    unavailable_client = httpx.AsyncClient(
        transport=httpx.MockTransport(unavailable), base_url="http://runtime.test"
    )
    unavailable_transport = HttpLocalRuntimeTransport(
        resource_id=request.resource_id,
        address="http://runtime.test/v1/executions",
        credential_provider=CredentialProvider(),
        client=unavailable_client,
    )
    with pytest.raises(LocalRuntimeTransportError) as unavailable_error:
        await unavailable_transport.execute(request)
    assert unavailable_error.value.code == "TRANSPORT_UNAVAILABLE"
    assert unavailable_error.value.retryable is True
    await client.aclose()
    await unavailable_client.aclose()


@pytest.mark.asyncio
async def test_http_transport_rejects_malformed_response_and_correlation_mismatch():
    request = _request()

    async def malformed(incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=incoming)

    client = httpx.AsyncClient(transport=httpx.MockTransport(malformed), base_url="http://runtime.test")
    transport = HttpLocalRuntimeTransport(
        resource_id=request.resource_id,
        address="http://runtime.test/v1/executions",
        credential_provider=CredentialProvider(),
        client=client,
    )
    with pytest.raises(LocalRuntimeTransportError) as malformed_error:
        await transport.execute(request)
    assert malformed_error.value.code == "TRANSPORT_RESPONSE_INVALID"
    await client.aclose()

    async def mismatch(incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_result(request, request_id="other"), request=incoming)

    mismatch_client = httpx.AsyncClient(
        transport=httpx.MockTransport(mismatch), base_url="http://runtime.test"
    )
    mismatch_transport = HttpLocalRuntimeTransport(
        resource_id=request.resource_id,
        address="http://runtime.test/v1/executions",
        credential_provider=CredentialProvider(),
        client=mismatch_client,
    )
    with pytest.raises(LocalRuntimeTransportError) as mismatch_error:
        await mismatch_transport.execute(request)
    assert mismatch_error.value.code == "TRANSPORT_CORRELATION_MISMATCH"
    await mismatch_client.aclose()


@pytest.mark.asyncio
async def test_health_probe_is_separate_from_signed_execution():
    async def handler(incoming: httpx.Request) -> httpx.Response:
        assert incoming.method == "GET"
        assert incoming.url.path == "/health"
        return httpx.Response(
            200,
            json={"resourceId": "zhiyi-local-runtime", "protocolVersion": "1", "status": "online"},
            request=incoming,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://runtime.test")
    transport = HttpLocalRuntimeTransport(
        resource_id="zhiyi-local-runtime",
        address="http://runtime.test/v1/executions",
        credential_provider=CredentialProvider(),
        client=client,
    )
    assert (await transport.health())["status"] == "online"
    await client.aclose()
