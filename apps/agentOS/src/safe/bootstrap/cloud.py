"""后段进程内研究装配；此文件不创建HTTP监听，也不提供网络认证。

InProcessTransport用于验收本机编排，实际经过JSON请求/回执往返。
TODO(P1/P3)：生产工厂另行注入认证、nonce、配额、审计、deadline和TLS边界。
TODO(P6)：限制会话总量和终态回执保留；当前仅适合短程显式实验。
"""

import threading

from safe.application.continuation import ContinuationService
from safe.application.session import SessionService
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.inference import Capabilities
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.session import SessionStatus, SessionView, StepReceipt, StepRequest
from safe.infrastructure.storage.memory_sessions import MemorySessionStore
from safe.ports.activation_codec import ActivationCodec
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


__all__ = ["InProcessTransport"]
