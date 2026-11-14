"""进程内短时会话存储。

实现边界：这是 P3 的单进程基线，不持久化、不恢复 KV，也不提供网络认证。
每个会话使用独立的可重入锁；执行回调在锁内运行，保证同一 request_id 只会
执行一次。生产装配仍需把 runner、认证、资源上限和生命周期清理器注入更高层。

TODO(P3-1)：增加会话总数、回执数、并发执行数和激活内存的有界配额。
TODO(P3-2)：接入不透明 KV 句柄，并在关闭/失败/过期时等待或隔离后幂等释放。
TODO(P3-3)：将长时间 runner 从锁内执行改为“占位-执行-提交”条件变量事务，
           保持重复请求等待而不是占用线程；提交失败必须进入 FAILED。
TODO(P3-4)：增加显式后台清理生命周期和重启隔离域；当前进程重启即全部失效。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
import secrets
import threading
import time

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.session import SessionStatus, SessionView, StepReceipt, StepRequest
from safe.domain.session_state import require_next_step, transition
from safe.ports.clock import Clock
from safe.ports.session_store import StepRunner

class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utc_timestamp(self) -> float:
        return time.time()


@dataclass(frozen=True)
class _StoredReceipt:
    fingerprint: str
    receipt: StepReceipt


@dataclass
class _SessionRecord:
    owner_id: str
    session_id: str
    manifest_digest: str
    status: SessionStatus
    next_step: int
    created_at: float
    last_activity: float
    absolute_deadline: float
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    receipts: dict[str, _StoredReceipt] = field(default_factory=dict, repr=False)


class MemorySessionStore:
    """带 owner 隔离、TTL、严格 step 和回执幂等的进程内会话实现。"""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        idle_ttl: float = 60.0,
        absolute_ttl: float = 300.0,
    ) -> None:
        if type(idle_ttl) is not float or idle_ttl <= 0:
            raise ValueError("idle_ttl必须是正浮点数")
        if type(absolute_ttl) is not float or absolute_ttl <= 0:
            raise ValueError("absolute_ttl必须是正浮点数")
        if idle_ttl > absolute_ttl:
            raise ValueError("idle_ttl不能大于absolute_ttl")
        self._clock = clock or _SystemClock()
        self._idle_ttl = idle_ttl
        self._absolute_ttl = absolute_ttl
        self._sessions: dict[str, _SessionRecord] = {}
        self._sessions_lock = threading.RLock()

    def create(self, owner_id: str, manifest_digest: str, *, session_id: str | None = None) -> SessionView:
        self._require_identity(owner_id)
        self._require_digest(manifest_digest)
        identifier = session_id or f"session-{secrets.token_urlsafe(18)}"
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identifier):
            raise SafeError(ErrorCode.SESSION_INVALID)
        now = self._clock.monotonic()
        record = _SessionRecord(
            owner_id=owner_id,
            session_id=identifier,
            manifest_digest=manifest_digest,
            status=SessionStatus.CREATED,
            next_step=0,
            created_at=now,
            last_activity=now,
            absolute_deadline=now + self._absolute_ttl,
        )
        with self._sessions_lock:
            if identifier in self._sessions:
                raise SafeError(ErrorCode.SESSION_INVALID)
            self._sessions[identifier] = record
        return self._view(record)

    def view(self, owner_id: str, session_id: str) -> SessionView:
        record = self._owned(owner_id, session_id)
        with record.lock:
            self._expire_locked(record)
            return self._view(record)

    def receipt(self, owner_id: str, session_id: str, request_id: str) -> StepReceipt | None:
        record = self._owned(owner_id, session_id)
        with record.lock:
            self._expire_locked(record)
            stored = record.receipts.get(request_id)
            return stored.receipt if stored else None

    def execute(self, owner_id: str, request: StepRequest, runner: StepRunner) -> StepReceipt:
        """原子执行一步；runner返回``(token_id, finished)``，异常使会话永久失败。"""
        record = self._owned(owner_id, request.session_id)
        fingerprint = self._fingerprint(request)
        with record.lock:
            self._expire_locked(record)
            previous = record.receipts.get(request.request_id)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise SafeError(ErrorCode.IDEMPOTENCY_CONFLICT)
                return previous.receipt
            if record.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                raise SafeError(ErrorCode.SESSION_INVALID)
            if request.manifest_digest != record.manifest_digest:
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            require_next_step(expected=record.next_step, received=request.step)
            expected_phase = "prefill" if request.step == 0 else "decode"
            if request.phase != expected_phase:
                raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
            if record.status is SessionStatus.CREATED:
                record.status = transition(record.status, SessionStatus.ACTIVE)
            try:
                outcome = runner(request)
                token_id, finished = outcome
                if type(token_id) is not int or token_id < 0 or type(finished) is not bool:
                    raise ValueError("runner回执格式非法")
                receipt = StepReceipt(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    step=request.step,
                    token_id=token_id,
                    finished=finished,
                )
            except Exception:
                record.status = SessionStatus.FAILED
                raise
            record.receipts[request.request_id] = _StoredReceipt(fingerprint, receipt)
            record.next_step += 1
            record.last_activity = self._clock.monotonic()
            if finished:
                record.status = transition(record.status, SessionStatus.CLOSED)
            return receipt

    def close(self, owner_id: str, session_id: str) -> SessionView:
        record = self._owned(owner_id, session_id)
        with record.lock:
            self._expire_locked(record)
            if record.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                raise SafeError(ErrorCode.SESSION_INVALID)
            record.status = transition(record.status, SessionStatus.CLOSED)
            return self._view(record)

    def fail(self, owner_id: str, session_id: str) -> SessionView:
        record = self._owned(owner_id, session_id)
        with record.lock:
            self._expire_locked(record)
            if record.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                raise SafeError(ErrorCode.SESSION_INVALID)
            record.status = transition(record.status, SessionStatus.FAILED)
            return self._view(record)

    def cleanup_expired(self) -> int:
        count = 0
        with self._sessions_lock:
            records = tuple(self._sessions.values())
        for record in records:
            with record.lock:
                before = record.status
                self._expire_locked(record)
                count += int(before is not SessionStatus.EXPIRED and record.status is SessionStatus.EXPIRED)
        return count

    def _owned(self, owner_id: str, session_id: str) -> _SessionRecord:
        self._require_identity(owner_id)
        if not isinstance(session_id, str) or not session_id:
            raise SafeError(ErrorCode.SESSION_INVALID)
        with self._sessions_lock:
            record = self._sessions.get(session_id)
        if record is None or record.owner_id != owner_id:
            raise SafeError(ErrorCode.SESSION_INVALID)
        return record

    def _expire_locked(self, record: _SessionRecord) -> None:
        if record.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
            return
        now = self._clock.monotonic()
        if now >= record.absolute_deadline or now - record.last_activity >= self._idle_ttl:
            record.status = transition(record.status, SessionStatus.EXPIRED)

    @staticmethod
    def _view(record: _SessionRecord) -> SessionView:
        return SessionView(
            session_id=record.session_id,
            manifest_digest=record.manifest_digest,
            status=record.status,
            next_step=record.next_step,
        )

    @staticmethod
    def _fingerprint(request: StepRequest) -> str:
        payload = request.model_dump_json().encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _require_identity(value: str) -> None:
        if not isinstance(value, str) or not value or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
            raise SafeError(ErrorCode.SESSION_INVALID)

    @staticmethod
    def _require_digest(value: str) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)


__all__ = ["MemorySessionStore", "StepRunner"]
