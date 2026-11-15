"""HTTP 云端工厂的共享执行器、限额与显式生命周期验收。"""

import asyncio
import json
import secrets
import threading
import time

import pytest

httpx = pytest.importorskip("httpx", reason="需要独立 requirements.safe.http.lock 环境")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from safe.application.activation import ActivationService
from safe.application.manifest import ManifestService
from safe.bootstrap import cloud
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.session import ActivationContext
from safe.infrastructure.codecs.fp32 import FP32Codec
from safe.infrastructure.models.sampling import GreedySampler
from safe.infrastructure.security.authentication import InMemoryNonceStore
from safe.infrastructure.security.signing import sign_request
from safe.ports.credentials import Credential
from safe.ports.model_runner import KVHandle


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def utc_timestamp(self):
        return time.time()


class Runner:
    def __init__(self, manifest):
        self.manifest = manifest
        self.handles = set()
        self.forward_handles = []
        self.closed = False
        self.released = threading.Event()
        self.fail_release = False

    def create_kv(self, session_id):
        handle = KVHandle("kv-" + session_id)
        self.handles.add(handle)
        return handle

    def release_kv(self, handle):
        if self.fail_release:
            self.released.set()
            raise RuntimeError("不应返回客户端的维护错误")
        self.handles.discard(handle)
        self.released.set()

    def prefill(self, activation, shape, *, kv_handle, session_id):
        assert kv_handle in self.handles
        self.forward_handles.append(kv_handle)
        return (0.0, 1.0, 0.0)

    def decode(self, kv_handle, session_id, activation, shape):
        assert kv_handle in self.handles
        self.forward_handles.append(kv_handle)
        return (0.0, 1.0, 0.0)

    def close(self):
        self.closed = True


class Credentials:
    def get(self, credential_id):
        if credential_id in ("credential-a", "credential-b"):
            return make_credential(credential_id)
        return None


def make_credential(credential_id="credential-a"):
    return Credential(credential_id=credential_id, owner_id="owner-" + credential_id[-1],
                      secret=b"bootstrap-test-secret-32-bytes!!!", scopes=frozenset({"safe:infer"}))


def make_app(**options):
    manifest = SplitModelManifest(model_id="synthetic/bootstrap", revision="a" * 40,
        config_digest="b" * 64, tokenizer_digest="c" * 64, template_digest="d" * 64,
        prefix_digest="e" * 64, suffix_digest="f" * 64, total_layers=4,
        cut_layer=2, hidden_size=4, license_id="Apache-2.0")
    digest = ManifestService.digest(manifest)
    runner, codec = Runner(manifest), FP32Codec()
    app = cloud.create_http_cloud_app(runner=runner, codec=codec, sampler=GreedySampler(vocab_size=3),
        manifest=manifest, approved_digest=digest, credentials=Credentials(), **options)
    return app, runner, ActivationService(codec=codec, manifest=manifest, approved_digest=digest), digest


def request(client, method, path, *, body=b"", credential_id="credential-a"):
    headers = sign_request(credential=make_credential(credential_id), method=method, path=path,
        timestamp=int(time.time()), nonce=secrets.token_hex(16), body=body)
    if method == "POST":
        headers["Content-Type"] = "application/json"
    return client.request(method, path, content=body, headers=headers)


def create(client, digest, *, credential_id="credential-a"):
    return request(client, "POST", "/safe/v1/sessions", body=json.dumps({"manifest_digest": digest}).encode(),
                   credential_id=credential_id)


def test_factory_owns_sessions_and_maintenance_but_preserves_shared_runner():
    app, runner, activation, digest = make_app()
    with TestClient(app, base_url="https://testserver") as client:
        assert request(client, "GET", "/safe/v1/capabilities").json()["available"]
        created = create(client, digest)
        assert created.status_code == 200
        sid = created.json()["session_id"]
        for step in range(2):
            context = ActivationContext(session_id=sid, manifest_digest=digest, next_step=step,
                phase="prefill" if step == 0 else "decode", position_offset=step)
            value = activation.encode((1.0,) * 4, (1, 1, 4), context=context, request_id=f"request-{step}")
            response = request(client, "POST", f"/safe/v1/sessions/{sid}/steps", body=value.model_dump_json().encode())
            assert response.status_code == 200, response.text
        assert runner.forward_handles == [KVHandle("kv-" + sid)] * 2
        assert runner.handles
        assert create(client, digest).status_code == 503
    assert not runner.handles
    assert not runner.closed
    with TestClient(app, base_url="https://testserver") as client:
        assert create(client, digest).status_code == 200
    assert not runner.handles
    assert not runner.closed


def test_factory_enforces_total_session_limit_across_owners():
    app, runner, _, digest = make_app(max_sessions=1)
    with TestClient(app, base_url="https://testserver") as client:
        assert create(client, digest).status_code == 200
        assert create(client, digest, credential_id="credential-b").status_code == 503
        assert len(runner.handles) == 1
    assert not runner.handles


def test_periodic_purge_releases_expired_sessions_and_reclaims_capacity():
    clock = Clock()
    app, runner, _, digest = make_app(clock=clock, idle_ttl=1.0, absolute_ttl=2.0,
                                      purge_interval=0.01, max_sessions=1)
    with TestClient(app, base_url="https://testserver") as client:
        assert create(client, digest).status_code == 200
        clock.now = 2.0
        assert runner.released.wait(timeout=2), "后台 TTL 清理未运行"
        # 事件在释放函数内置位，排队执行新请求时本轮 purge 已可完成记录删除。
        assert create(client, digest).status_code == 200
    assert not runner.handles


def test_maintenance_failure_makes_all_subsequent_requests_unavailable():
    clock = Clock()
    app, runner, _, digest = make_app(clock=clock, idle_ttl=1.0, absolute_ttl=2.0, purge_interval=0.01)
    with TestClient(app, base_url="https://testserver") as client:
        assert create(client, digest).status_code == 200
        runner.fail_release = True
        clock.now = 2.0
        assert runner.released.wait(timeout=2)
        response = request(client, "GET", "/safe/v1/capabilities")
        assert response.status_code == 503
        assert response.json() == {"code": "TRANSPORT_UNAVAILABLE"}
        assert create(client, digest, credential_id="credential-b").status_code == 503
        runner.fail_release = False
    assert not runner.handles
    assert not runner.closed


def test_factory_accepts_injected_nonce_store():
    class Nonces:
        def __init__(self):
            self.inner = InMemoryNonceStore()
            self.consumed = []

        def consume(self, credential_id, nonce, expires_at):
            self.consumed.append(credential_id)
            return self.inner.consume(credential_id, nonce, expires_at)
    store = Nonces()
    app, _, _, _ = make_app(nonce_store=store)
    with TestClient(app, base_url="https://testserver") as client:
        assert request(client, "GET", "/safe/v1/capabilities").status_code == 200
    assert store.consumed == ["credential-a"]


def test_factory_remains_unavailable_outside_its_lifespan():
    app, _, _, _ = make_app()
    inactive = TestClient(app, base_url="https://testserver")
    assert request(inactive, "GET", "/safe/v1/capabilities").status_code == 503
    with TestClient(app, base_url="https://testserver") as client:
        assert request(client, "GET", "/safe/v1/capabilities").status_code == 200
    assert request(inactive, "GET", "/safe/v1/capabilities").status_code == 503
    inactive.close()


def test_startup_purge_failure_never_marks_application_ready(monkeypatch):
    def fail_purge(self):
        raise RuntimeError("启动维护内部细节")
    monkeypatch.setattr(cloud.MemorySessionStore, "purge_expired", fail_purge)
    app, runner, _, digest = make_app()
    with TestClient(app, base_url="https://testserver") as client:
        assert request(client, "GET", "/safe/v1/capabilities").json() == {"code": "TRANSPORT_UNAVAILABLE"}
        assert create(client, digest).status_code == 503
    assert not runner.handles
    assert not runner.closed


def test_shutdown_waits_for_inflight_purge_before_finishing(monkeypatch):
    purge_started, allow_purge, leave_lifespan, stopped = (threading.Event() for _ in range(4))
    original = cloud.MemorySessionStore.purge_expired
    calls = []
    failures = []
    def blocking_purge(store):
        calls.append(True)
        if len(calls) > 1:
            purge_started.set()
            assert allow_purge.wait(timeout=2)
        return original(store)
    monkeypatch.setattr(cloud.MemorySessionStore, "purge_expired", blocking_purge)
    app, runner, _, digest = make_app(purge_interval=0.01)
    def serve():
        try:
            with TestClient(app, base_url="https://testserver") as client:
                assert create(client, digest).status_code == 200
                assert leave_lifespan.wait(timeout=2)
        except BaseException as exc:
            failures.append(exc)
        finally:
            stopped.set()
    worker = threading.Thread(target=serve)
    worker.start()
    try:
        assert purge_started.wait(timeout=2)
        leave_lifespan.set()
        assert not stopped.wait(timeout=0.05)
        assert runner.handles
    finally:
        allow_purge.set()
        leave_lifespan.set()
        worker.join(timeout=2)
    assert stopped.is_set()
    assert not failures
    assert not runner.handles
    assert not runner.closed


@pytest.mark.parametrize("action", ["create", "step"])
@pytest.mark.parametrize("cancel_request", [False, True])
def test_shutdown_drains_admitted_dispatch_before_closing_sessions(monkeypatch, action, cancel_request):
    entered, release, completed, close_called = (threading.Event() for _ in range(4))
    original = getattr(cloud.ContinuationService, action)
    original_close = cloud.MemorySessionStore.close_all
    def blocked(service, *args, **kwargs):
        entered.set()
        try:
            assert release.wait(timeout=3)
            return original(service, *args, **kwargs)
        finally:
            completed.set()
    def observed_close(store):
        close_called.set()
        return original_close(store)
    monkeypatch.setattr(cloud.ContinuationService, action, blocked)
    monkeypatch.setattr(cloud.MemorySessionStore, "close_all", observed_close)

    async def scenario():
        app, runner, activation, digest = make_app()
        life = app.router.lifespan_context(app)
        await life.__aenter__()
        shutdown = pending = None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://testserver") as client:
            try:
                if action == "create":
                    pending = asyncio.create_task(create(client, digest))
                else:
                    session = await create(client, digest)
                    sid = session.json()["session_id"]
                    context = ActivationContext(session_id=sid, manifest_digest=digest, next_step=0,
                        phase="prefill", position_offset=0)
                    value = activation.encode((1.0,) * 4, (1, 1, 4), context=context, request_id="request-0")
                    pending = asyncio.create_task(request(client, "POST", f"/safe/v1/sessions/{sid}/steps",
                                                          body=value.model_dump_json().encode()))
                assert await asyncio.to_thread(entered.wait, 2)
                if cancel_request:
                    pending.cancel()
                    await asyncio.sleep(0)
                shutdown = asyncio.create_task(life.__aexit__(None, None, None))
                await asyncio.sleep(0)
                unavailable = await request(client, "GET", "/safe/v1/capabilities")
                assert unavailable.status_code == 503
                assert not await asyncio.to_thread(close_called.wait, 0.05), "尚有已准入请求时不能 close_all"
                assert not shutdown.done()
                if cancel_request:
                    pending.cancel()
                    await asyncio.sleep(0)
                    assert not close_called.is_set()
            finally:
                release.set()
                if pending is not None:
                    if cancel_request:
                        with pytest.raises(asyncio.CancelledError):
                            await pending
                    else:
                        assert (await pending).status_code == 200
                    assert await asyncio.to_thread(completed.wait, 2)
                if shutdown is None:
                    await life.__aexit__(None, None, None)
                else:
                    await shutdown
        assert close_called.is_set()
        assert not runner.handles
        assert not runner.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("end_body", ["cancel", "timeout"])
def test_shutdown_drains_partial_body_requests_without_leaking_admission(monkeypatch, end_body):
    close_called = threading.Event()
    original_close = cloud.MemorySessionStore.close_all
    def observed_close(store):
        close_called.set()
        return original_close(store)
    monkeypatch.setattr(cloud.MemorySessionStore, "close_all", observed_close)
    async def scenario():
        app, runner, _, digest = make_app(body_timeout=0.2)
        life = app.router.lifespan_context(app)
        await life.__aenter__()
        reading, release_body = asyncio.Event(), asyncio.Event()
        body = json.dumps({"manifest_digest": digest}).encode()
        async def chunks():
            yield body[:1]
            reading.set()
            await release_body.wait()
            yield body[1:]
        headers = sign_request(credential=make_credential(), method="POST", path="/safe/v1/sessions",
            timestamp=int(time.time()), nonce=secrets.token_hex(16), body=body)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://testserver") as client:
            pending = asyncio.create_task(client.post("/safe/v1/sessions", content=chunks(),
                headers={**headers, "Content-Type": "application/json"}))
            await asyncio.wait_for(reading.wait(), 2)
            shutdown = asyncio.create_task(life.__aexit__(None, None, None))
            await asyncio.sleep(0)
            try:
                assert not await asyncio.to_thread(close_called.wait, 0.05)
                assert not shutdown.done()
            finally:
                if end_body == "cancel":
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                else:
                    assert (await pending).status_code == 503
                await asyncio.wait_for(shutdown, 2)
        assert not runner.handles
        assert not runner.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["create", "step"])
def test_cancelled_shutdown_waits_for_dispatch_and_releases_kv(monkeypatch, action):
    entered, release = threading.Event(), threading.Event()
    original = getattr(cloud.ContinuationService, action)
    def blocked(service, *args, **kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return original(service, *args, **kwargs)
    monkeypatch.setattr(cloud.ContinuationService, action, blocked)

    async def scenario():
        app, runner, activation, digest = make_app()
        life = app.router.lifespan_context(app)
        await life.__aenter__()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://testserver") as client:
            if action == "create":
                pending = asyncio.create_task(create(client, digest))
            else:
                created = await create(client, digest)
                sid = created.json()["session_id"]
                context = ActivationContext(session_id=sid, manifest_digest=digest, next_step=0,
                    phase="prefill", position_offset=0)
                value = activation.encode((1.0,) * 4, (1, 1, 4), context=context, request_id="request-0")
                pending = asyncio.create_task(request(client, "POST", f"/safe/v1/sessions/{sid}/steps",
                                                      body=value.model_dump_json().encode()))
            assert await asyncio.to_thread(entered.wait, 2)
            shutdown = asyncio.create_task(life.__aexit__(None, None, None))
            try:
                await asyncio.sleep(0)
                shutdown.cancel()
                await asyncio.sleep(0)
                shutdown.cancel()
                await asyncio.sleep(0)
                assert not shutdown.done(), "停机取消不能跳过请求排空和 KV 回收"
                assert (await request(client, "GET", "/safe/v1/capabilities")).status_code == 503
            finally:
                release.set()
                assert (await pending).status_code == 200
                with pytest.raises(asyncio.CancelledError):
                    await shutdown
        assert not runner.handles
        assert not runner.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf"), True, 61, 10 ** 400])
def test_factory_rejects_unbounded_or_invalid_maintenance_interval(interval):
    with pytest.raises(ValueError):
        make_app(purge_interval=interval)
