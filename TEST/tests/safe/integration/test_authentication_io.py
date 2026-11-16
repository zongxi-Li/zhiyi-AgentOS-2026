"""认证存储IO不能阻塞ASGI事件循环，取消也必须等线程交还执行权。"""

import asyncio
import secrets
import threading
import time

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")


def headers(body=b""):
    from components.safe.infrastructure.security.signing import sign_request
    from TEST.tests.safe.integration.test_http_bootstrap import make_credential
    return sign_request(credential=make_credential(), method="GET", path="/safe/v1/capabilities",
        timestamp=int(time.time()), nonce=secrets.token_hex(16), body=body)


def test_authentication_io_runs_outside_event_loop(monkeypatch):
    from components.safe.infrastructure.security.authentication import HmacAuthenticator
    from TEST.tests.safe.integration.test_http_bootstrap import make_app
    original = HmacAuthenticator.authenticate

    def assert_worker(self, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return original(self, **kwargs)
        raise RuntimeError("认证存储不能在事件循环线程执行")

    monkeypatch.setattr(HmacAuthenticator, "authenticate", assert_worker)

    async def scenario():
        app, _, _, _ = make_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://testserver") as client:
                response = await client.get("/safe/v1/capabilities", headers=headers())
                assert response.status_code == 200
    asyncio.run(scenario())


def test_cancelled_authentication_retains_admission_until_store_finishes():
    from TEST.tests.safe.integration.test_http_bootstrap import make_app
    entered, release, finished = (threading.Event() for _ in range(3))

    class BlockingStore:
        def consume(self, credential_id, nonce, expires_at):
            entered.set()
            try:
                if not release.wait(timeout=10):
                    raise TimeoutError()
                return True
            finally:
                finished.set()

    async def scenario():
        app, runner, _, _ = make_app(nonce_store=BlockingStore(), max_inflight=1)
        life = app.router.lifespan_context(app)
        await life.__aenter__()
        pending = shutdown = None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://testserver") as client:
            try:
                pending = asyncio.create_task(client.get("/safe/v1/capabilities", headers=headers()))
                assert await asyncio.to_thread(entered.wait, 5)
                # 正文/认证/执行共享在途限额，但主循环仍应及时处理拒绝请求。
                second = await client.get("/safe/v1/capabilities", headers=headers())
                assert second.status_code == 503
                pending.cancel()
                await asyncio.sleep(0)
                pending.cancel()
                shutdown = asyncio.create_task(life.__aexit__(None, None, None))
                await asyncio.sleep(0)
                assert not shutdown.done()
                assert not finished.is_set()
            finally:
                release.set()
                if pending is not None:
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                if shutdown is None:
                    await life.__aexit__(None, None, None)
                else:
                    await shutdown
        assert finished.is_set() and not runner.handles and not runner.closed
    asyncio.run(scenario())
