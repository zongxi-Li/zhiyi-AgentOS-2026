"""后段进程内及认证 HTTP 装配；调用者始终持有 runner 所有权。"""

import asyncio
from contextlib import asynccontextmanager
import math
import threading

from safe.application.continuation import ContinuationService
from safe.application.session import SessionService
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.inference import Capabilities
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.session import SessionStatus, SessionView, StepReceipt, StepRequest
from safe.infrastructure.storage.memory_sessions import MemorySessionStore
from safe.infrastructure.security.authentication import HmacAuthenticator, InMemoryNonceStore
from safe.ports.activation_codec import ActivationCodec
from safe.ports.clock import Clock
from safe.ports.credentials import CredentialSource, NonceStore
from safe.ports.model_runner import SuffixRunner, TokenSampler


class InProcessTransport:
    """绑定一个受信研究身份；调用者持有runner所有权，close仅结束会话。"""

    def __init__(self, *, runner: SuffixRunner, codec: ActivationCodec, sampler: TokenSampler,
                 manifest: SplitModelManifest, approved_digest: str, owner_id: str):
        self._sessions = SessionService(MemorySessionStore(runner=runner))
        self._cloud = ContinuationService(sessions=self._sessions, runner=runner, codec=codec,
            sampler=sampler, manifest=manifest, approved_digest=approved_digest)
        self._digest, self._owner = approved_digest, owner_id
        self._ids: set[str] = set()
        self._closed = False
        self._lock = threading.RLock()

    def _require_open(self):
        if self._closed:
            raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)

    def _require_session(self, session_id):
        self._require_open()
        if session_id not in self._ids:
            raise SafeError(ErrorCode.SESSION_INVALID)

    def capabilities(self) -> Capabilities:
        with self._lock:
            self._require_open()
            return Capabilities(available=True)

    def create_session(self, manifest_digest: str) -> SessionView:
        with self._lock:
            self._require_open()
            if manifest_digest != self._digest:
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            view = self._cloud.create(self._owner)
            self._ids.add(view.session_id)
            return SessionView.model_validate_json(view.model_dump_json().encode("utf-8"))

    def step(self, request: StepRequest) -> StepReceipt:
        with self._lock:
            self._require_session(request.session_id)
            parsed = StepRequest.model_validate_json(request.model_dump_json().encode("utf-8"))
            receipt = self._cloud.step(self._owner, parsed)
            return StepReceipt.model_validate_json(receipt.model_dump_json().encode("utf-8"))

    def query(self, session_id: str, request_id: str) -> StepReceipt | None:
        with self._lock:
            self._require_session(session_id)
            receipt = self._sessions.receipt(self._owner, session_id, request_id)
            return None if receipt is None else StepReceipt.model_validate_json(receipt.model_dump_json().encode("utf-8"))

    def close_session(self, session_id: str) -> SessionView:
        with self._lock:
            self._require_session(session_id)
            view = self._sessions.view(self._owner, session_id)
            if view.status in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                view = self._sessions.close(self._owner, session_id)
            return SessionView.model_validate_json(view.model_dump_json().encode("utf-8"))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            error = None
            for session_id in tuple(self._ids):
                try:
                    self.close_session(session_id)
                except Exception as exc:
                    error = error or exc
            if error is not None:
                raise error
            self._closed = True


def create_http_cloud_app(
    *, runner: SuffixRunner, codec: ActivationCodec, sampler: TokenSampler,
    manifest: SplitModelManifest, approved_digest: str, credentials: CredentialSource,
    nonce_store: NonceStore | None = None, clock: Clock | None = None,
    idle_ttl: float = 60.0, absolute_ttl: float = 300.0,
    max_sessions: int = 128, max_active_per_owner: int = 1,
    purge_interval: float = 5.0, max_new_tokens: int = 32,
    max_body_bytes: int = 12 * 1024 * 1024, max_metadata_bytes: int = 16 * 1024,
    body_timeout: float = 10.0, max_inflight: int = 8,
):
    """显式创建单进程研究 HTTP 应用，不创建监听或关闭调用者 runner。

    clock 仅控制会话 TTL；认证始终使用真实 UTC。默认 nonce 存储仅在本进程共享，
    多进程部署须显式注入共享原子实现。终态记录由 store 的绝对 TTL 策略回收。
    lifespan 外不接单；启动及周期清理失败后保持不可用，直到重新启动生命周期。
    停机先关闭准入并取消维护调度，排空已准入请求及同步清理后再回收会话 KV。
    停机任务自身被取消也须等待完整清理结束，支持重复取消后再传播取消。
    """
    # 可选 HTTP 依赖仅在调用工厂时导入；普通 bootstrap 导入不加载 FastAPI。
    from fastapi import FastAPI
    from starlette.concurrency import run_in_threadpool

    from safe.interfaces.cloud_api import create_cloud_app

    if type(purge_interval) not in (int, float) or not 0 < purge_interval <= 60 or not math.isfinite(purge_interval):
        raise ValueError("会话维护间隔必须位于 0–60 秒之间")
    store = MemorySessionStore(runner=runner, clock=clock, idle_ttl=idle_ttl,
        absolute_ttl=absolute_ttl, max_sessions=max_sessions, max_active_per_owner=max_active_per_owner)
    sessions = SessionService(store)
    continuation = ContinuationService(sessions=sessions, runner=runner, codec=codec,
        sampler=sampler, manifest=manifest, approved_digest=approved_digest, max_new_tokens=max_new_tokens)
    authenticator = HmacAuthenticator(credentials=credentials,
        nonces=InMemoryNonceStore() if nonce_store is None else nonce_store)
    ready = threading.Event()

    async def purge():
        # 取消调度不能中断同步 runner；保留任务并等待已启动的清理线程退出。
        operation = asyncio.create_task(run_in_threadpool(store.purge_expired))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def maintain():
        try:
            while True:
                await asyncio.sleep(purge_interval)
                await purge()
        except asyncio.CancelledError:
            raise
        except Exception:
            # 不把含执行器细节的异常写入响应或默认为服务仍然健康。
            ready.clear()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        maintenance = None
        ready.clear()
        try:
            try:
                await purge()
            except Exception:
                pass
            else:
                app.state.safe_open_admission()
                ready.set()
                maintenance = asyncio.create_task(maintain())
            yield
        finally:
            ready.clear()
            app.state.safe_close_admission()
            async def cleanup():
                if maintenance is not None:
                    maintenance.cancel()
                    await asyncio.gather(maintenance, return_exceptions=True)
                await app.state.safe_drain()
                await run_in_threadpool(store.close_all)

            # 停机取消只影响调用者，不能取消尚持有线程或 KV 的清理事务。
            operation = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                while not operation.done():
                    try:
                        await asyncio.shield(operation)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not operation.cancelled():
                    operation.exception()
                raise

    app = create_cloud_app(continuation=continuation, sessions=sessions,
        authenticate=authenticator.authenticate, approved_digest=approved_digest, readiness=ready.is_set,
        max_body_bytes=max_body_bytes, max_metadata_bytes=max_metadata_bytes,
        body_timeout=body_timeout, max_inflight=max_inflight)
    app.router.lifespan_context = lifespan
    return app


__all__ = ["InProcessTransport", "create_http_cloud_app"]
