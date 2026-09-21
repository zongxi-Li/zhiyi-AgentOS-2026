from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from urllib.request import urlopen

from contracts.local_runtime import LocalRuntimeCapability
from contracts.resource_signing import build_resource_signature
from runtime import LocalRuntimeHttpApplication, LocalRuntimeIdentity
from runtime.credentials import RuntimeCredentialStore
from runtime.http_server import create_runtime_http_server

from helpers import make_request


RESOURCE_ID = "zhiyi-local-runtime"
CREDENTIAL_ID = "credential-local-runtime"
SECRET = "test-only-runtime-secret"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _body(request) -> bytes:
    return json.dumps(
        request.model_dump(by_alias=True, mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _headers(body: bytes, *, nonce: str, timestamp: int = int(NOW.timestamp()), secret: str = SECRET):
    payload = json.loads(body.decode("utf-8"))
    return {
        "Idempotency-Key": payload["idempotencyKey"],
        "X-Resource-Credential": CREDENTIAL_ID,
        "X-Resource-Timestamp": str(timestamp),
        "X-Resource-Nonce": nonce,
        "X-Resource-Signature": build_resource_signature(
            secret,
            method="POST",
            path="/v1/executions",
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        ),
    }


def _app(tmp_path, runtime_factory, *, clock=lambda: NOW):
    service, _store, _resolver = runtime_factory(tmp_path)
    return LocalRuntimeHttpApplication(
        service=service,
        identity=LocalRuntimeIdentity(runtime_id="runtime-test", resource_id=RESOURCE_ID),
        credentials=RuntimeCredentialStore(CREDENTIAL_ID, SECRET),
        clock=clock,
    )


def test_health_is_non_sensitive_and_does_not_advertise_shell(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)

    response = app.handle(method="GET", path="/health")

    payload = json.loads(response.body)
    assert response.status == 200
    assert payload["resourceId"] == RESOURCE_ID
    assert payload["status"] == "online"
    assert "shell.exec" not in payload["capabilities"]
    assert str(tmp_path) not in response.body.decode("utf-8")
    assert SECRET not in response.body.decode("utf-8")


def test_valid_signed_request_reaches_filesystem_capability(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    request = make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": "signed.txt", "content": "ok", "overwrite": False},
    )
    body = _body(request)

    response = app.handle(
        method="POST", path="/v1/executions", headers=_headers(body, nonce="nonce-valid"), body=body
    )

    payload = json.loads(response.body)
    assert response.status == 200
    assert payload["status"] == "completed"
    assert (tmp_path / "signed.txt").read_text(encoding="utf-8") == "ok"


def test_invalid_signature_stale_timestamp_and_unknown_credential_are_rejected_before_grant(
    tmp_path, runtime_factory
):
    app = _app(tmp_path, runtime_factory)
    target = tmp_path / "blocked.txt"
    request = make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": "blocked.txt", "content": "blocked", "overwrite": False},
    )
    body = _body(request)

    invalid = _headers(body, nonce="nonce-invalid")
    invalid["X-Resource-Signature"] = "00"
    assert app.handle(method="POST", path="/v1/executions", headers=invalid, body=body).status == 401

    stale = _headers(body, nonce="nonce-stale", timestamp=int((NOW - timedelta(hours=1)).timestamp()))
    assert app.handle(method="POST", path="/v1/executions", headers=stale, body=body).status == 401

    unknown = _headers(body, nonce="nonce-unknown")
    unknown["X-Resource-Credential"] = "missing"
    assert app.handle(method="POST", path="/v1/executions", headers=unknown, body=body).status == 401
    assert not target.exists()


def test_nonce_replay_is_rejected(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    request = make_request(LocalRuntimeCapability.FS_LIST, {"path": "."})
    body = _body(request)
    headers = _headers(body, nonce="nonce-replay")

    assert app.handle(method="POST", path="/v1/executions", headers=headers, body=body).status == 200
    replay = app.handle(method="POST", path="/v1/executions", headers=headers, body=body)

    assert replay.status == 409
    assert json.loads(replay.body)["error"]["code"] == "REPLAY_REJECTED"


def test_same_idempotency_body_does_not_repeat_mutation_and_mismatch_fails_closed(
    tmp_path, runtime_factory
):
    app = _app(tmp_path, runtime_factory)
    request = make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": "once.txt", "content": "one", "overwrite": False},
    )
    body = _body(request)
    first = app.handle(
        method="POST", path="/v1/executions", headers=_headers(body, nonce="nonce-once-1"), body=body
    )
    second = app.handle(
        method="POST", path="/v1/executions", headers=_headers(body, nonce="nonce-once-2"), body=body
    )

    assert json.loads(first.body)["status"] == "completed"
    assert json.loads(second.body)["status"] == "completed"
    assert (tmp_path / "once.txt").read_text(encoding="utf-8") == "one"

    changed = request.model_copy(update={"input": {"path": "once.txt", "content": "two", "overwrite": True}})
    changed_body = _body(changed)
    conflict = app.handle(
        method="POST",
        path="/v1/executions",
        headers=_headers(changed_body, nonce="nonce-once-3"),
        body=changed_body,
    )
    conflict_payload = json.loads(conflict.body)
    assert conflict_payload["status"] == "failed"
    assert conflict_payload["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert (tmp_path / "once.txt").read_text(encoding="utf-8") == "one"


def test_concurrent_same_idempotency_key_has_one_execution_result(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    request = make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": "concurrent.txt", "content": "one", "overwrite": False},
    )
    body = _body(request)

    def invoke(nonce: str):
        return json.loads(app.handle(
            method="POST",
            path="/v1/executions",
            headers=_headers(body, nonce=nonce),
            body=body,
        ).body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, ["nonce-concurrent-1", "nonce-concurrent-2"]))

    assert [item["status"] for item in results] == ["completed", "completed"]
    assert (tmp_path / "concurrent.txt").read_text(encoding="utf-8") == "one"


def test_shell_is_domain_error_and_never_starts_a_process(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    request = make_request(LocalRuntimeCapability.SHELL_EXEC, {"command": "echo should-not-run"})
    body = _body(request)

    response = app.handle(
        method="POST", path="/v1/executions", headers=_headers(body, nonce="nonce-shell"), body=body
    )

    payload = json.loads(response.body)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "CAPABILITY_NOT_IMPLEMENTED"


def test_http_server_binds_only_when_explicitly_created(tmp_path, runtime_factory):
    app = _app(tmp_path, runtime_factory)
    server = create_runtime_http_server(app, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["resourceId"] == RESOURCE_ID
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
