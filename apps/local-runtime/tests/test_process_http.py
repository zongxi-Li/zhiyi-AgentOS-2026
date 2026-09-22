from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import time

from contracts.local_runtime import (
    LocalRuntimeCapability,
    LocalRuntimeExecutionCancelRequest,
)
from contracts.resource_signing import build_resource_signature
from runtime import LocalRuntimeHttpApplication, LocalRuntimeIdentity
from runtime.credentials import RuntimeCredentialStore

from helpers import make_request


RESOURCE_ID = "zhiyi-local-runtime"
CREDENTIAL_ID = "credential-process"
SECRET = "process-test-secret"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _body(model) -> bytes:
    return json.dumps(
        model.model_dump(by_alias=True, mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _headers(*, method: str, path: str, body: bytes, nonce: str, idempotency_key: str | None = None):
    headers = {
        "X-Resource-Credential": CREDENTIAL_ID,
        "X-Resource-Timestamp": str(int(NOW.timestamp())),
        "X-Resource-Nonce": nonce,
        "X-Resource-Signature": build_resource_signature(
            SECRET,
            method=method,
            path=path,
            timestamp=int(NOW.timestamp()),
            nonce=nonce,
            body=body,
        ),
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _app(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(
        tmp_path,
        capabilities={LocalRuntimeCapability.SHELL_EXEC.value},
    )
    return LocalRuntimeHttpApplication(
        service=service,
        identity=LocalRuntimeIdentity(runtime_id="runtime-process", resource_id=RESOURCE_ID),
        credentials=RuntimeCredentialStore(CREDENTIAL_ID, SECRET),
        clock=lambda: NOW,
    )


def _start(app, *, code: str, nonce: str):
    request = make_request(
        LocalRuntimeCapability.SHELL_EXEC,
        {
            "mode": "direct",
            "program": sys.executable,
            "args": ["-c", code],
            "cwd": ".",
        },
    )
    body = _body(request)
    response = app.handle(
        method="POST",
        path="/v1/executions",
        headers=_headers(
            method="POST",
            path="/v1/executions",
            body=body,
            nonce=nonce,
            idempotency_key=request.idempotency_key,
        ),
        body=body,
    )
    payload = json.loads(response.body)
    assert response.status == 200
    assert payload["status"] == "accepted"
    return request, payload["output"]["executionId"]


def test_authenticated_process_start_and_incremental_events(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    request, execution_id = _start(
        app,
        code="import sys; print('one', flush=True); print('two', file=sys.stderr, flush=True)",
        nonce="process-start",
    )
    cursor = -1
    event_types = []
    terminal = False
    for index in range(20):
        path = f"/v1/executions/{execution_id}/events?afterSequence={cursor}&waitSeconds=0.1"
        response = app.handle(
            method="GET",
            path=path,
            headers=_headers(method="GET", path=path, body=b"", nonce=f"process-events-{index}"),
        )
        payload = json.loads(response.body)
        assert response.status == 200
        events = payload["events"]
        event_types.extend(event["eventType"] for event in events)
        if events:
            cursor = max(event["sequence"] for event in events)
        terminal = payload["terminal"]
        if terminal:
            break
    assert terminal is True
    assert event_types[0] == "started"
    assert "stdout_delta" in event_types
    assert "stderr_delta" in event_types
    assert event_types[-1] == "completed"
    assert all(
        event["requestId"] == request.request_id and event["invocationId"] == request.invocation_id
        for event in payload["events"]
    )


def test_authenticated_cancel_is_idempotent_and_correlated(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    request, execution_id = _start(
        app,
        code="import time; time.sleep(60)",
        nonce="process-cancel-start",
    )
    cancellation = LocalRuntimeExecutionCancelRequest(
        requestId=request.request_id,
        invocationId=request.invocation_id,
        resourceId=RESOURCE_ID,
        executionId=execution_id,
    )
    body = _body(cancellation)
    path = f"/v1/executions/{execution_id}/cancel"
    response = app.handle(
        method="POST",
        path=path,
        headers=_headers(method="POST", path=path, body=body, nonce="process-cancel"),
        body=body,
    )
    assert response.status == 200
    assert json.loads(response.body)["state"] in {"cancelling", "cancelled"}

    time.sleep(0.2)
    replayed_cancel = app.handle(
        method="POST",
        path=path,
        headers=_headers(method="POST", path=path, body=body, nonce="process-cancel-2"),
        body=body,
    )
    assert replayed_cancel.status == 200
    assert json.loads(replayed_cancel.body)["state"] == "cancelled"


def test_unknown_and_wrong_resource_cancel_fail_before_process_mutation(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    unknown = LocalRuntimeExecutionCancelRequest(
        requestId="request-unknown",
        invocationId="invocation-unknown",
        resourceId=RESOURCE_ID,
        executionId="execution-missing",
    )
    unknown_body = _body(unknown)
    unknown_path = "/v1/executions/execution-missing/cancel"
    unknown_response = app.handle(
        method="POST",
        path=unknown_path,
        headers=_headers(method="POST", path=unknown_path, body=unknown_body, nonce="cancel-unknown"),
        body=unknown_body,
    )
    assert unknown_response.status == 404
    assert json.loads(unknown_response.body)["error"]["code"] == "EXECUTION_NOT_FOUND"

    request, execution_id = _start(
        app,
        code="import time; time.sleep(60)",
        nonce="process-wrong-resource-start",
    )
    wrong = LocalRuntimeExecutionCancelRequest(
        requestId=request.request_id,
        invocationId=request.invocation_id,
        resourceId="another-resource",
        executionId=execution_id,
    )
    wrong_body = _body(wrong)
    wrong_path = f"/v1/executions/{execution_id}/cancel"
    wrong_response = app.handle(
        method="POST",
        path=wrong_path,
        headers=_headers(method="POST", path=wrong_path, body=wrong_body, nonce="cancel-wrong-resource"),
        body=wrong_body,
    )
    assert wrong_response.status == 409
    assert json.loads(wrong_response.body)["error"]["code"] == "EXECUTION_IDENTITY_MISMATCH"
    app.service.executor.process_service.cancel(
        execution_id,
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        resource_id=RESOURCE_ID,
    )
