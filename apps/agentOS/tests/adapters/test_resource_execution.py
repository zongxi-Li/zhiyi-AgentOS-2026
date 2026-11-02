from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from adapters.resource_execution import (
    HttpResourceExecutionAdapter,
    ResourceExecutionError,
    build_resource_execution_adapter,
    normalize_execution_endpoint,
)
from adapters.resource_execution import ResourceCredentialProvider
from contracts.resource import ResourceEndpoint, RuntimeKind, RuntimeProfile
from contracts.resource_signing import build_resource_signature
from service.agents.base import AgentOutput


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        task=SimpleNamespace(mission_id="mission-1"),
        run=SimpleNamespace(run_id="run-1"),
        step=SimpleNamespace(step_id="step-1", agent_name="edge-vision", capability="vision.infer", goal="classify"),
        context_pack=SimpleNamespace(
            data={"imageRef": "artifact://image-1"},
            evidence_refs=["evidence-1"],
            attempt_id="attempt-1",
        ),
        commit_id="commit-1",
    )


@pytest.mark.asyncio
async def test_http_adapter_sends_controlled_context_and_returns_agent_output() -> None:
    received: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        received["headers"] = dict(request.headers)
        received["json"] = json.loads(request.content)
        return httpx.Response(200, json={"output": {"label": "cat"}, "summary": "classified"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://edge")
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=_Credentials(),
        client=client,
    )

    result = await adapter.run(_context())

    assert isinstance(result, AgentOutput)
    assert result.output == {"label": "cat"}
    assert received["headers"]["idempotency-key"] == "commit-1"
    assert received["json"] == {
        "runId": "run-1",
        "missionId": "mission-1",
        "stepId": "step-1",
        "attemptId": "attempt-1",
        "commitId": "commit-1",
        "agentName": "edge-vision",
        "capability": "vision.infer",
        "goal": "classify",
        "input": {"imageRef": "artifact://image-1"},
        "evidenceRefs": ["evidence-1"],
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_http_adapter_reports_remote_failure_without_returning_fake_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "edge unavailable"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://edge")
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=_Credentials(),
        client=client,
    )

    with pytest.raises(ResourceExecutionError, match="REMOTE_EXECUTION_OUTCOME_UNKNOWN") as error:
        await adapter.run(_context())

    assert error.value.outcome_unknown is True
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 302, 408, 409, 425, 429, 500, 503])
async def test_http_adapter_marks_non_terminal_or_ambiguous_status_unknown(status: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"output": {"ok": True}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=_Credentials(),
        client=client,
    )
    try:
        with pytest.raises(ResourceExecutionError) as error:
            await adapter.run(_context())
        assert error.value.outcome_unknown is True
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_http_adapter_treats_explicit_client_rejection_as_not_admitted(status: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "request rejected"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=_Credentials(),
        client=client,
    )
    try:
        with pytest.raises(ResourceExecutionError) as error:
            await adapter.run(_context())
        assert error.value.outcome_unknown is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["SUCCEEDED", "SUCCESS", "COMPLETED", "DONE", "FINISHED"])
async def test_http_adapter_accepts_explicit_terminal_success_state(state: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": state, "output": {"ok": True}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=_Credentials(),
        client=client,
    )
    try:
        result = await adapter.run(_context())
        assert result.output == {"ok": True}
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"state": "RUNNING", "output": {"ok": True}},
        {"status": "queued", "summary": "not terminal"},
        {"state": "FAILED", "output": {"partial": True}},
        {"state": "COMPLETED", "status": "RUNNING", "output": {"partial": True}},
    ],
)
async def test_http_adapter_rejects_non_terminal_or_empty_http_200_body(body: dict) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=_Credentials(),
        client=client,
    )
    try:
        with pytest.raises(ResourceExecutionError) as error:
            await adapter.run(_context())
        assert error.value.outcome_unknown is True
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception_type", "outcome_unknown"),
    [
        (httpx.ConnectTimeout, False),
        (httpx.ConnectError, False),
        (httpx.ReadTimeout, True),
        (httpx.WriteTimeout, True),
    ],
)
async def test_http_adapter_classifies_transport_failures_before_replay(
    exception_type: type[httpx.HTTPError],
    outcome_unknown: bool,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("injected transport failure", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=_Credentials(),
        client=client,
    )
    try:
        with pytest.raises(ResourceExecutionError) as error:
            await adapter.run(_context())
        assert error.value.outcome_unknown is outcome_unknown
    finally:
        await client.aclose()


class _Credentials:
    def __init__(self, credential_id: str = "credential-1", secret: str = "secret-1") -> None:
        self.credential_id = credential_id
        self.secret = secret

    def current_signing_credential(self, resource_id: str) -> tuple[str, str]:
        assert resource_id == "edge-01"
        return self.credential_id, self.secret


def test_normalize_execution_endpoint_does_not_duplicate_execute_path() -> None:
    assert normalize_execution_endpoint("https://edge.example.test") == "https://edge.example.test/execute"
    assert normalize_execution_endpoint("https://edge.example.test/execute") == "https://edge.example.test/execute"
    assert normalize_execution_endpoint("https://edge.example.test/api/execute/") == "https://edge.example.test/api/execute"


@pytest.mark.asyncio
async def test_http_adapter_signs_exact_json_body_with_current_resource_credential() -> None:
    received: dict[str, object] = {}
    credentials = _Credentials()

    async def handler(request: httpx.Request) -> httpx.Response:
        received["request"] = request
        return httpx.Response(200, json={"output": {"ok": True}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://edge")
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge/execute",
        credential_provider=credentials,
        client=client,
    )

    await adapter.run(_context())

    request = received["request"]
    assert isinstance(request, httpx.Request)
    timestamp = int(request.headers["x-resource-timestamp"])
    nonce = request.headers["x-resource-nonce"]
    expected = build_resource_signature(
        credentials.secret,
        method="POST",
        path="/execute",
        timestamp=timestamp,
        nonce=nonce,
        body=request.content,
    )
    assert request.headers["x-resource-credential"] == "credential-1"
    assert request.headers["x-resource-signature"] == expected
    assert request.url.path == "/execute"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_adapter_reads_rotated_credential_for_next_request() -> None:
    credentials = _Credentials()
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["x-resource-credential"])
        return httpx.Response(200, json={"output": {"ok": True}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://edge")
    adapter = HttpResourceExecutionAdapter(
        resource_id="edge-01",
        address="http://edge",
        credential_provider=credentials,
        client=client,
    )
    await adapter.run(_context())
    credentials.credential_id = "credential-2"
    credentials.secret = "secret-2"
    await adapter.run(_context())

    assert seen == ["credential-1", "credential-2"]
    await client.aclose()


def test_build_resource_execution_adapter_uses_remote_profile_endpoint() -> None:
    profile = RuntimeProfile(
        runtimeId="edge-01",
        kind=RuntimeKind.EXECUTION_BACKEND,
        nodeId="node:edge-1",
        capabilities=["analysis"],
        endpoint=ResourceEndpoint(protocol="https", address="https://edge.example.test/execute"),
    )
    adapter = build_resource_execution_adapter(
        profile,
        credential_provider=_Credentials(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )
    assert isinstance(adapter, HttpResourceExecutionAdapter)
    assert adapter.address == "https://edge.example.test/execute"
