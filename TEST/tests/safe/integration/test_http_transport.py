"""专用 HTTP 边界：真实认证/codec/会话，模型为明确的合成执行器。"""

import json
import secrets
import ssl
import time

import pytest

httpx = pytest.importorskip("httpx", reason="需要独立 requirements.safe.http.lock 环境")
pytest.importorskip("fastapi")

from components.safe.application.activation import ActivationService
from components.safe.application.continuation import ContinuationService
from components.safe.application.manifest import ManifestService
from components.safe.application.session import SessionService
from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.manifest import SplitModelManifest
from components.safe.contracts.session import ActivationContext, SessionStatus
from components.safe.infrastructure.codecs.fp32 import FP32Codec
from components.safe.infrastructure.models.sampling import GreedySampler
from components.safe.infrastructure.storage.memory_sessions import MemorySessionStore
from components.safe.ports.model_runner import KVHandle


def make_services():
    manifest = SplitModelManifest(model_id="synthetic/http", revision="a" * 40,
        config_digest="b" * 64, tokenizer_digest="c" * 64, template_digest="d" * 64,
        prefix_digest="e" * 64, suffix_digest="f" * 64, total_layers=4,
        cut_layer=2, hidden_size=4, license_id="Apache-2.0")
    digest = ManifestService.digest(manifest)

    class Suffix:
        def __init__(self):
            self.manifest, self.calls, self.handles = manifest, [], set()

        def create_kv(self, session_id):
            handle = KVHandle("kv-" + session_id)
            self.handles.add(handle)
            return handle

        def release_kv(self, handle):
            self.handles.remove(handle)

        def prefill(self, activation, shape, *, kv_handle, session_id):
            assert kv_handle in self.handles
            self.calls.append("prefill")
            return (0.0, 2.0, 1.0)

        def decode(self, kv_handle, session_id, activation, shape):
            assert kv_handle in self.handles
            self.calls.append("decode")
            return (0.0, 2.0, 1.0)

    runner = Suffix()
    sessions = SessionService(MemorySessionStore(runner=runner))
    continuation = ContinuationService(sessions=sessions, runner=runner, codec=FP32Codec(),
        sampler=GreedySampler(vocab_size=3), manifest=manifest, approved_digest=digest,
        max_new_tokens=2)
    activation = ActivationService(codec=FP32Codec(), manifest=manifest, approved_digest=digest)
    return continuation, sessions, runner, activation, digest


def make_credential(owner="owner-a", credential_id="credential-a"):
    from components.safe.ports.credentials import Credential
    return Credential(credential_id=credential_id, owner_id=owner, secret=b"synthetic-test-key-32-bytes-only!!",
                      scopes=frozenset({"safe:infer"}))


def signed(credential, method, path, body=b"", nonce=None):
    from components.safe.infrastructure.security.signing import sign_request
    return sign_request(credential=credential, method=method, path=path,
                        timestamp=int(time.time()), nonce=nonce or secrets.token_hex(16), body=body)


@pytest.fixture
def cloud():
    from fastapi.testclient import TestClient
    from components.safe.infrastructure.security.authentication import HmacAuthenticator, InMemoryNonceStore
    from components.safe.interfaces.cloud_api import create_cloud_app

    continuation, sessions, runner, activation, digest = make_services()
    credentials = {item.credential_id: item for item in (make_credential(), make_credential("owner-b", "credential-b"))}

    class Source:
        def get(self, credential_id):
            return credentials.get(credential_id)

    auth = HmacAuthenticator(credentials=Source(), nonces=InMemoryNonceStore())
    app = create_cloud_app(continuation=continuation, sessions=sessions,
                           authenticate=auth.authenticate, approved_digest=digest,
                           max_body_bytes=4096, max_metadata_bytes=1024)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        yield client, runner, activation, digest


def create_session(client, digest, credential=None):
    body = json.dumps({"manifest_digest": digest}, separators=(",", ":")).encode()
    path = "/safe/v1/sessions"
    response = client.post(path, content=body, headers={**signed(credential or make_credential(), "POST", path, body),
                                                       "Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def step_for(activation, digest, session_id, *, step=0):
    return activation.encode((1.0,) * (12 if step == 0 else 4), (1, 3 if step == 0 else 1, 4),
        context=ActivationContext(session_id=session_id, manifest_digest=digest, next_step=step,
            phase="prefill" if step == 0 else "decode", position_offset=0 if step == 0 else 3),
        request_id=f"request-{step}")


def test_http_prefill_decode_recovery_and_close(cloud):
    client, runner, activation, digest = cloud
    sid = create_session(client, digest)
    for step in range(2):
        request = step_for(activation, digest, sid, step=step)
        path = f"/safe/v1/sessions/{sid}/steps"
        body = request.model_dump_json().encode()
        headers = {**signed(make_credential(), "POST", path, body), "Content-Type": "application/json"}
        response = client.post(path, content=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["finished"] is (step == 1)
        # 同一认证 nonce 不可重放；新 nonce + 同一业务请求可恢复原回执。
        assert client.post(path, content=body, headers=headers).status_code == 401
        duplicate = client.post(path, content=body, headers={**signed(make_credential(), "POST", path, body),
                                                            "Content-Type": "application/json"})
        assert duplicate.json() == response.json()
        query = f"/safe/v1/sessions/{sid}/requests/{request.request_id}"
        assert client.get(query, headers=signed(make_credential(), "GET", query)).json() == response.json()
    assert runner.calls == ["prefill", "decode"]
    assert not runner.handles
    path = f"/safe/v1/sessions/{sid}"
    assert client.delete(path, headers=signed(make_credential(), "DELETE", path)).json()["status"] == "closed"


def test_http_rejects_cross_owner_without_revealing_existence(cloud):
    client, _, _, digest = cloud
    sid = create_session(client, digest)
    statuses = []
    for identifier in (sid, "does-not-exist"):
        path = f"/safe/v1/sessions/{identifier}/requests/request-0"
        response = client.get(path, headers=signed(make_credential("owner-b", "credential-b"), "GET", path))
        statuses.append((response.status_code, response.json()))
    assert statuses[0] == statuses[1]
    assert statuses[0][0] == 404


@pytest.mark.parametrize("body", [b'{"manifest_digest":"' + b"0" * 64 + b'","prompt":"SECRET"}',
    b'{"manifest_digest":"' + b"0" * 64 + b'","manifest_digest":"' + b"0" * 64 + b'"}',
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e9999}', b'\xff', b'[]'])
def test_http_strict_json_and_errors_do_not_echo_input(cloud, body):
    client, runner, _, _ = cloud
    path = "/safe/v1/sessions"
    response = client.post(path, content=body, headers={**signed(make_credential(), "POST", path, body),
                                                       "Content-Type": "application/json"})
    assert response.status_code == 400
    assert set(response.json()) == {"code"}
    assert "SECRET" not in response.text
    assert not runner.handles


def test_http_limits_streamed_body_before_creating_kv(cloud):
    client, runner, _, _ = cloud
    path, body = "/safe/v1/sessions", b" " * 4097
    headers = {**signed(make_credential(), "POST", path, body), "Content-Type": "application/json"}
    response = client.post(path, content=iter((body[:3000], body[3000:])), headers=headers)
    assert response.status_code == 413
    assert not runner.handles


def test_http_rejects_duplicate_auth_headers_and_tampered_body(cloud):
    client, runner, _, digest = cloud
    path = "/safe/v1/sessions"
    body = json.dumps({"manifest_digest": digest}).encode()
    headers = list(signed(make_credential(), "POST", path, body).items())
    headers.extend((("Content-Type", "application/json"), ("x-safe-nonce", "0" * 32)))
    assert client.post(path, content=body, headers=headers).status_code == 401
    assert client.post(path, content=body + b" ", headers={**signed(make_credential(), "POST", path, body),
                                                          "Content-Type": "application/json"}).status_code == 401
    assert not runner.handles


def test_http_rejects_step_metadata_over_limit_before_forward(cloud):
    client, runner, activation, digest = cloud
    sid = create_session(client, digest)
    body = step_for(activation, digest, sid).model_dump_json().encode() + b" " * 1100
    path = f"/safe/v1/sessions/{sid}/steps"
    response = client.post(path, content=body, headers={**signed(make_credential(), "POST", path, body),
                                                       "Content-Type": "application/json"})
    assert response.status_code == 413
    assert not runner.calls


@pytest.mark.parametrize("path", ["/safe/v1/%63apabilities", "/safe/v1/capabilities?query=1"])
def test_http_rejects_ambiguous_actual_request_target(cloud, path):
    client, _, _, _ = cloud
    headers = signed(make_credential(), "GET", "/safe/v1/capabilities")
    assert client.get(path, headers=headers).status_code == 401


def test_http_error_mapping_covers_all_codes():
    from components.safe.interfaces.http_errors import HTTP_STATUS
    assert set(HTTP_STATUS) == set(ErrorCode)


@pytest.mark.parametrize("extra", [
    {"Transfer-Encoding": "chunked"},
    {"Content-Type": "application/json; charset=utf-16"},
    {"Content-Type": "application/json; charset=utf-8; charset=utf-16"},
])
def test_http_rejects_ambiguous_framing_and_encoding_before_kv(cloud, extra):
    client, runner, _, digest = cloud
    path = "/safe/v1/sessions"
    body = json.dumps({"manifest_digest": digest}).encode()
    headers = {**signed(make_credential(), "POST", path, body), "Content-Type": "application/json", **extra}
    response = client.post(path, content=body, headers=headers)
    assert response.status_code == 400
    assert not runner.handles


@pytest.mark.parametrize("identifier", ["request:0", "request.0"])
def test_http_rejects_request_id_that_cannot_be_queried(cloud, identifier):
    client, runner, activation, digest = cloud
    sid = create_session(client, digest)
    request = step_for(activation, digest, sid).model_copy(update={"request_id": identifier})
    body = request.model_dump_json().encode()
    path = f"/safe/v1/sessions/{sid}/steps"
    response = client.post(path, content=body, headers={**signed(make_credential(), "POST", path, body),
                                                       "Content-Type": "application/json"})
    assert response.status_code == 400
    assert not runner.calls


@pytest.mark.parametrize("origin", ["http://localhost:8000", "https://a.example/path", "https://a.example?query=1",
                                    "https://user:password@a.example", "https://a.example/#fragment"])
def test_client_rejects_unapproved_origin_forms(origin):
    from components.safe.infrastructure.transport.http_client import HttpRemoteTransport
    with pytest.raises(ValueError):
        HttpRemoteTransport(origin=origin, credential=make_credential())


def test_client_refuses_disabled_tls_verification():
    from components.safe.infrastructure.transport.http_client import HttpRemoteTransport
    context = ssl._create_unverified_context()
    with pytest.raises(ValueError):
        HttpRemoteTransport(origin="https://example.test", credential=make_credential(), ssl_context=context)


def test_client_uses_final_bytes_fresh_nonces_and_measures_real_response():
    from components.safe.infrastructure.transport.http_client import HttpRemoteTransport
    requests, observations = [], []
    response_body = b'{"protocol_version":"safe-v1","available":true}'

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=response_body, headers={"Content-Type": "application/json"})

    transport = HttpRemoteTransport(origin="https://example.test", credential=make_credential(),
        http_transport=httpx.MockTransport(handle), observer=observations.append)
    try:
        assert transport.capabilities().available is True
        assert transport.capabilities().available is True
    finally:
        transport.close()
    assert requests[0].headers["x-safe-nonce"] != requests[1].headers["x-safe-nonce"]
    assert all(item.response_bytes == len(response_body) and item.request_bytes == 0 for item in observations)
    assert all(item.elapsed_ms >= 0 for item in observations)


@pytest.mark.parametrize("status,body,headers", [(302, b"", {"Location": "https://unapproved.test"}),
    (200, b"x" * 1025, {"Content-Type": "application/json"}),
    (200, b'{"available":true,"available":false}', {"Content-Type": "application/json"}),
    (200, b'{"available":true,"secret":"SECRET"}', {"Content-Type": "application/json"}),
    (500, b"SECRET", {"Content-Type": "text/plain"})])
def test_client_rejects_redirect_invalid_or_oversized_response_without_retry(status, body, headers):
    from components.safe.infrastructure.transport.http_client import HttpRemoteTransport
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, content=body, headers=headers)

    transport = HttpRemoteTransport(origin="https://example.test", credential=make_credential(),
        http_transport=httpx.MockTransport(handle), max_response_bytes=1024)
    try:
        with pytest.raises(SafeError) as error:
            transport.capabilities()
        assert error.value.code is ErrorCode.TRANSPORT_UNAVAILABLE
        assert "SECRET" not in str(error.value)
        assert len(calls) == 1
    finally:
        transport.close()


@pytest.mark.parametrize("kind", ["validation", "http-error"])
def test_client_public_error_detaches_sensitive_response_and_request_context(kind):
    from components.safe.infrastructure.transport.http_client import HttpRemoteTransport

    def handle(request):
        if kind == "http-error":
            raise httpx.ConnectError("SECRET_REQUEST", request=request)
        return httpx.Response(200, json={"available": "SECRET_RESPONSE"})

    transport = HttpRemoteTransport(origin="https://example.test", credential=make_credential(),
        http_transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(SafeError) as error:
            transport.capabilities()
        assert error.value.code is ErrorCode.TRANSPORT_UNAVAILABLE
        assert error.value.__context__ is None
        assert error.value.__cause__ is None
    finally:
        transport.close()
