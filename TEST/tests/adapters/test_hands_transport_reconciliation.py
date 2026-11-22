"""An interrupted result query must not re-execute an admitted tool action."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest

from adapters.tool.hands_http import HandsAdmissionRejected, HandsExecutionCancelled, HandsHttpTransport, HandsOutcomeUnknown, receipt_checksum
from contracts.local_runtime import LocalRuntimeExecutionRequest


def request(capability="fs.read"):
    return LocalRuntimeExecutionRequest(
        protocolVersion="1", requestId="request", invocationId="invocation", resourceId="hands",
        capabilityId=capability, authorization={"workspaceId": "workspace", "grantId": "grant"},
        input={"path": "source.txt", **({"content": "changed"} if capability == "fs.write" else {})},
        idempotencyKey="operation",
        limits={"timeoutSeconds": 5, "maxStdoutBytes": 100, "maxStderrBytes": 100},
    )


def completed(wire, *, status="completed", corrupt=None):
    receipt = {key: wire[key] for key in ("requestId", "invocationId", "capabilityId", "idempotencyKey")}
    receipt.update(
        identity=wire.get("identity", {}), grantId="grant", status=status,
        startedAt="2026-11-19T00:00:00Z", completedAt="2026-11-19T00:00:01Z",
        output={"path": "source.txt", "text": "verified text"},
    )
    if status == "cancelled":
        receipt["error"] = {"code": "HANDS_CANCELLED", "message": "cancelled", "retryable": False}
    if corrupt == "identity":
        receipt["identity"] = {"runId": "another-run"}
    receipt["checksum"] = "invalid" if corrupt == "checksum" else receipt_checksum(receipt)
    return {"executionId": "execution", "state": status.upper(), "receipt": receipt}


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["fs.read", "fs.write"])
@pytest.mark.parametrize("failed_query", ["status", "events"])
async def test_admitted_result_is_requeried_without_repeating_execution(capability, failed_query):
    requests, wire, failures = [], {}, []
    identity = {"runId": "run", "stepId": "step", "attemptId": "attempt", "commitId": "commit"}

    async def service(incoming):
        requests.append((incoming.method, incoming.url.path))
        if incoming.method == "POST":
            wire.update(json.loads(incoming.content))
            return httpx.Response(202, json={"executionId": "execution", "state": "STARTED"})
        is_event = incoming.url.path.endswith("/events")
        if (is_event == (failed_query == "events")) and not failures:
            failures.append(incoming.url.path)
            raise httpx.RemoteProtocolError("Server disconnected without sending a response", request=incoming)
        return httpx.Response(200, json={"events": []} if is_event else completed(wire))

    provider = SimpleNamespace(current_signing_credential=lambda _: ("credential", "secret"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
        transport = HandsHttpTransport(resource_id="hands", address="http://hands.test/v1/executions",
            credential_provider=provider, client=client)
        result = await transport.execute_with_identity(request(capability), identity, event_sink=lambda _: asyncio.sleep(0))

    assert result.status == "completed" and result.output["text"] == "verified text"
    assert result.output["handsReceipt"]["identity"] == identity
    assert wire["requestId"] == str(uuid5(NAMESPACE_URL, "operation"))
    assert requests.count(("POST", "/v1/executions")) == 1
    assert len(failures) == 1
    assert requests.count(("GET", failures[0])) >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [429, 503])
async def test_temporary_query_response_is_reconciled_but_admission_is_not_replayed(code):
    methods, wire = [], {}
    outages = 0

    async def service(incoming):
        nonlocal outages
        methods.append(incoming.method)
        if incoming.method == "POST":
            wire.update(json.loads(incoming.content))
            return httpx.Response(202, json={"executionId": "execution", "state": "STARTED"})
        if outages < 2:
            outages += 1
            return httpx.Response(code, json={"error": {"code": "temporarily_unavailable"}})
        return httpx.Response(200, json=completed(wire))

    provider = SimpleNamespace(current_signing_credential=lambda _: ("credential", "secret"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
        transport = HandsHttpTransport(resource_id="hands", address="http://hands.test/v1/executions",
            credential_provider=provider, client=client)
        assert (await transport.execute_with_identity(request(), {})).status == "completed"
    assert methods == ["POST", "GET", "GET", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted_terminal", [False, True])
@pytest.mark.parametrize("event_outage", ["transport", "http"])
async def test_progress_outage_cannot_invalidate_a_verified_terminal_result(admitted_terminal, event_outage):
    calls, wire = [], {}

    async def service(incoming):
        calls.append((incoming.method, incoming.url.path))
        if incoming.method == "POST":
            wire.update(json.loads(incoming.content))
            record = completed(wire) if admitted_terminal else {"executionId": "execution", "state": "STARTED"}
            return httpx.Response(200 if admitted_terminal else 202, json=record)
        if incoming.url.path.endswith("/events"):
            if event_outage == "transport":
                raise httpx.RemoteProtocolError("event connection unavailable", request=incoming)
            return httpx.Response(503, json={"error": {"code": "temporarily_unavailable"}})
        return httpx.Response(200, json=completed(wire))

    provider = SimpleNamespace(current_signing_credential=lambda _: ("credential", "secret"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
        transport = HandsHttpTransport(resource_id="hands", address="http://hands.test/v1/executions",
            credential_provider=provider, client=client)
        result = await asyncio.wait_for(transport.execute_with_identity(
            request(), {}, event_sink=lambda _: asyncio.sleep(0)), 2)

    assert result.status == "completed" and result.output["content"] == "verified text"
    assert calls.count(("POST", "/v1/executions")) == 1
    assert calls.count(("GET", "/v1/executions/execution")) == (0 if admitted_terminal else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_type", [RuntimeError, TimeoutError, httpx.ReadError])
async def test_progress_consumer_failure_is_not_treated_as_a_query_outage(monkeypatch, failure_type):
    transport = HandsHttpTransport.__new__(HandsHttpTransport)
    wire = {}
    persistence_error = failure_type("admission WAL unavailable")

    async def call(method, suffix="", payload=None, key=None):
        if method == "POST":
            wire.update(payload)
            return completed(wire)
        return {"events": [{"seq": 1, "type": "execution.completed"}]}

    async def persist_event(_):
        raise persistence_error

    monkeypatch.setattr(transport, "_call", call)
    with pytest.raises(HandsOutcomeUnknown) as failure:
        await transport.execute_with_identity(request(), {}, event_sink=persist_event)
    assert failure.value.__cause__ is persistence_error
    assert failure.value.quarantine_scope == "runtime"
    assert failure.value.reconciliation_reason == "execution_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ["checksum", "identity"])
async def test_reconnection_does_not_accept_an_uncorrelated_or_corrupt_receipt(monkeypatch, corrupt):
    transport = HandsHttpTransport.__new__(HandsHttpTransport)
    wire, calls = {}, []

    async def call(method, suffix="", payload=None, key=None):
        calls.append((method, suffix))
        if method == "POST":
            wire.update(payload)
            return {"executionId": "execution", "state": "STARTED"}
        if len(calls) == 2:
            raise httpx.ReadError("connection interrupted")
        return completed(wire, corrupt=corrupt)

    monkeypatch.setattr(transport, "_call", call)
    with pytest.raises(HandsOutcomeUnknown, match="receipt") as failure:
        await transport.execute_with_identity(request(), {})
    assert failure.value.reconciliation_reason == "protocol_integrity"
    assert failure.value.quarantine_scope == "runtime"
    assert calls == [("POST", ""), ("GET", "/execution"), ("GET", "/execution")]


@pytest.mark.asyncio
async def test_query_outage_uses_the_execution_deadline_without_a_retry_count(monkeypatch):
    transport = HandsHttpTransport.__new__(HandsHttpTransport)
    attempts = []

    async def call(method, suffix="", payload=None, key=None):
        attempts.append((method, suffix))
        raise httpx.ReadError("connection interrupted")

    monkeypatch.setattr(transport, "_call", call)
    with pytest.raises(HandsOutcomeUnknown, match="reconciliation deadline") as failure:
        await transport._query("/execution", deadline=asyncio.get_running_loop().time() + .02)
    assert isinstance(failure.value.__cause__, httpx.ReadError)
    assert failure.value.reconciliation_reason == "transport_unavailable"
    assert failure.value.quarantine_scope == "operation"
    assert attempts and all(method == "GET" for method, _ in attempts)


@pytest.mark.asyncio
async def test_definite_query_authority_rejection_is_not_retried(monkeypatch):
    transport = HandsHttpTransport.__new__(HandsHttpTransport)
    calls = []

    async def call(method, suffix="", payload=None, key=None):
        calls.append((method, suffix))
        raise HandsAdmissionRejected(403, "GRANT_REVOKED")

    monkeypatch.setattr(transport, "_call", call)
    with pytest.raises(HandsAdmissionRejected, match="GRANT_REVOKED"):
        await transport.query_execution("execution")
    assert calls == [("GET", "/execution")]


@pytest.mark.asyncio
async def test_lost_admission_response_does_not_submit_a_new_execution(monkeypatch):
    transport = HandsHttpTransport.__new__(HandsHttpTransport)
    calls = []

    async def call(method, suffix="", payload=None, key=None):
        calls.append((method, suffix, key))
        raise httpx.RemoteProtocolError("admission response lost")

    monkeypatch.setattr(transport, "_call", call)
    with pytest.raises(HandsOutcomeUnknown) as failure:
        await transport.execute_with_identity(request(), {})
    assert failure.value.reconciliation_reason == "transport_unavailable"
    assert failure.value.quarantine_scope == "operation"
    assert calls == [("POST", "", "operation")]


@pytest.mark.asyncio
async def test_cancel_during_result_reconciliation_still_joins_a_terminal_receipt(monkeypatch):
    transport = HandsHttpTransport.__new__(HandsHttpTransport)
    querying, cancelled = asyncio.Event(), asyncio.Event()
    wire, calls = {}, []

    async def call(method, suffix="", payload=None, key=None):
        calls.append((method, suffix))
        if method == "POST" and not suffix:
            wire.update(payload)
            return {"executionId": "execution", "state": "STARTED"}
        if suffix.endswith("/cancel"):
            cancelled.set()
            return {"state": "CANCELLING"}
        querying.set()
        if not cancelled.is_set():
            raise httpx.RemoteProtocolError("connection interrupted")
        return completed(wire, status="cancelled")

    monkeypatch.setattr(transport, "_call", call)
    task = asyncio.create_task(transport.execute_with_identity(request(), {}))
    await querying.wait()
    task.cancel("worker_shutdown")
    with pytest.raises(HandsExecutionCancelled) as failure:
        await asyncio.wait_for(task, 2)
    assert failure.value.result.output["handsReceipt"]["status"] == "cancelled"
    assert str(failure.value) == "worker_shutdown"
    assert calls.count(("POST", "")) == calls.count(("POST", "/execution/cancel")) == 1
