"""进程内短时会话存储。

实现边界：这是 P3 的单进程基线，不持久化、不恢复 KV，也不提供网络认证。
每个会话使用独立的可重入锁；执行回调在锁内运行，保证同一 request_id 只会
执行一次。生产装配仍需把 runner、认证、资源上限和生命周期清理器注入更高层。

已实现：会话总记录/owner活跃会话限额；绝对TTL后显式purge回收记录容量。
TODO(P3-1)：按模型实测增加激活内存配额；HTTP装配限制并发，每会话32步/160位置。
已实现：回执发布失败或同步执行取消进入FAILED；绝对TTL在前向返回后复核；
执行中同线程查询不释放KV；释放失败可重试且不阻断其他会话的清理。
已实现：execute_with_context在会话锁内提供存储推进的位置和KV，供ContinuationService续算。
已实现：认证HTTP工厂在会话存储与续算用例中装配同一个suffix runner。
TODO(P3-2)：GPU任务须由runner等待或隔离，不能将HTTP取消视为强制停止计算。
TODO(P3-3)：按容量测量决定是否将长时间runner改为占位/执行/提交事务；保留同一请求只推进一次。
已实现：HTTP工厂周期清理/停机close_all；重启即全部会话失效，不恢复KV。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import re
import secrets
import threading
import time

from pydantic import ValidationError

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.session import ActivationContext, SessionStatus, SessionView, StepReceipt, StepRequest
from safe.domain.activation_policy import checked_raw_bytes
from safe.domain.session_state import require_next_step, transition
from safe.ports.clock import Clock
from safe.ports.model_runner import KVHandle, ModelRunner
from safe.ports.session_store import ContextStepRunner, StepRunner

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
    position_offset: int = 0
    kv_handle: KVHandle | None = field(default=None, repr=False)
    kv_released: bool = False
    executing: bool = False
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
        runner: ModelRunner | None = None,
        max_sessions: int = 1024,
        max_active_per_owner: int = 128,
    ) -> None:
        if type(idle_ttl) is not float or not math.isfinite(idle_ttl) or idle_ttl <= 0:
            raise ValueError("idle_ttl必须是正浮点数")
        if type(absolute_ttl) is not float or not math.isfinite(absolute_ttl) or absolute_ttl <= 0:
            raise ValueError("absolute_ttl必须是正浮点数")
        if idle_ttl > absolute_ttl:
            raise ValueError("idle_ttl不能大于absolute_ttl")
        if any(type(value) is not int or value < 1 for value in (max_sessions, max_active_per_owner)):
            raise ValueError("会话容量必须为正整数")
        self._clock = clock or _SystemClock()
        self._idle_ttl = idle_ttl
        self._absolute_ttl = absolute_ttl
        self._runner = runner
        self._max_sessions = max_sessions
        self._max_active_per_owner = max_active_per_owner
        self._sessions: dict[str, _SessionRecord] = {}
        self._sessions_lock = threading.RLock()

    def create(self, owner_id: str, manifest_digest: str, *, session_id: str | None = None) -> SessionView:
        self._require_identity(owner_id)
        self._require_digest(manifest_digest)
        identifier = session_id or f"session-{secrets.token_urlsafe(18)}"
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identifier):
            raise SafeError(ErrorCode.SESSION_INVALID)
        with self._sessions_lock:
            if identifier in self._sessions:
                raise SafeError(ErrorCode.SESSION_INVALID)
            # 终态也占用总记录容量，以保留幂等回执；超过保留期后显式 purge。
            active = sum(record.owner_id == owner_id and record.status in (SessionStatus.CREATED, SessionStatus.ACTIVE)
                         for record in self._sessions.values())
            if len(self._sessions) >= self._max_sessions or active >= self._max_active_per_owner:
                raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
            # 先创建KV，再发布可见会话；创建失败不会留下半初始化状态。
            handle = self._runner.create_kv(identifier) if self._runner else None
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
                kv_handle=handle,
            )
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
        return self.execute_with_context(owner_id, request, lambda value, context, handle: runner(value))

    def execute_with_context(self, owner_id: str, request: StepRequest, runner: ContextStepRunner) -> StepReceipt:
        """把受信位置和KV交给进程内回调；不会向请求方暴露句柄。"""
        try:
            request = StepRequest.model_validate(request.model_dump())
        except (AttributeError, ValidationError):
            raise SafeError(ErrorCode.ACTIVATION_INVALID) from None
        record = self._owned(owner_id, request.session_id)
        fingerprint = self._fingerprint(request)
        with record.lock:
            if record.executing:
                raise SafeError(ErrorCode.SESSION_INVALID)
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
            if request.position_offset != record.position_offset or record.next_step >= 32:
                raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
            checked_raw_bytes(request.activation.shape)
            if request.phase == "decode" and request.activation.shape[1] != 1:
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            next_position = record.position_offset + request.activation.shape[1]
            if next_position > 160:
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            context = ActivationContext(
                session_id=record.session_id, manifest_digest=record.manifest_digest,
                next_step=record.next_step, phase=expected_phase, position_offset=record.position_offset,
            )
            if record.status is SessionStatus.CREATED:
                record.status = transition(record.status, SessionStatus.ACTIVE)
            record.executing = True
            try:
                outcome = runner(request, context, record.kv_handle)
                token_id, finished = outcome
                if type(token_id) is not int or token_id < 0 or type(finished) is not bool:
                    raise ValueError("runner回执格式非法")
                finished = finished or record.next_step == 31 or next_position == 160
                receipt = StepReceipt(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    step=request.step,
                    token_id=token_id,
                    finished=finished,
                )
                completed_at = self._clock.monotonic()
                if completed_at >= record.absolute_deadline:
                    # 计算已结束才允许释放；绝对寿命不能被一次长前向延长。
                    record.status = SessionStatus.EXPIRED
                    raise SafeError(ErrorCode.SESSION_INVALID)
                # 回执发布也属于模型事务；写入失败后绝不能再次推进同一KV。
                record.receipts[request.request_id] = _StoredReceipt(fingerprint, receipt)
            except BaseException:
                # CancelledError/KeyboardInterrupt同样可能发生在KV已推进之后。
                # 同步回调返回或抛错意味着执行权已交还；不能将此视为强制停止GPU。
                if record.status is not SessionStatus.EXPIRED:
                    record.status = SessionStatus.FAILED
                record.receipts.pop(request.request_id, None)
                try:
                    self._release_locked(record)
                except Exception:
                    # 保留原始计算/提交异常；未释放的句柄留给显式清理重试。
                    pass
                raise
            finally:
                record.executing = False
            record.next_step += 1
            record.position_offset = next_position
            record.last_activity = completed_at
            if finished:
                record.status = transition(record.status, SessionStatus.CLOSED)
                self._release_locked(record)
            return receipt

    def close(self, owner_id: str, session_id: str) -> SessionView:
        record = self._owned(owner_id, session_id)
        with record.lock:
            if record.executing:
                raise SafeError(ErrorCode.SESSION_INVALID)
            self._expire_locked(record)
            if record.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                raise SafeError(ErrorCode.SESSION_INVALID)
            record.status = transition(record.status, SessionStatus.CLOSED)
            self._release_locked(record)
            return self._view(record)

    def fail(self, owner_id: str, session_id: str) -> SessionView:
        record = self._owned(owner_id, session_id)
        with record.lock:
            if record.executing:
                raise SafeError(ErrorCode.SESSION_INVALID)
            self._expire_locked(record)
            if record.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                raise SafeError(ErrorCode.SESSION_INVALID)
            record.status = transition(record.status, SessionStatus.FAILED)
            self._release_locked(record)
            return self._view(record)

    def cleanup_expired(self) -> int:
        count = 0
        first_error: Exception | None = None
        with self._sessions_lock:
            records = tuple(self._sessions.values())
        for record in records:
            with record.lock:
                try:
                    before = record.status
                    self._expire_locked(record)
                    count += int(before is not SessionStatus.EXPIRED and record.status is SessionStatus.EXPIRED)
                    if record.status in (SessionStatus.CLOSED, SessionStatus.FAILED, SessionStatus.EXPIRED):
                        self._release_locked(record)
                except Exception as exc:
                    # 一个角色的释放失败不能阻止本轮清理其他会话。
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error
        return count

    def purge_expired(self) -> int:
        """释放到期 KV 后清理超过绝对寿命的终态记录；保留期内不驱逐回执。"""
        self.cleanup_expired()
        removed = 0
        with self._sessions_lock:
            for key, record in tuple(self._sessions.items()):
                # 非阻塞取得记录锁，避免全局锁与正在执行的回调形成锁顺序环。
                if not record.lock.acquire(blocking=False):
                    continue
                try:
                    if (not record.executing and self._clock.monotonic() >= record.absolute_deadline
                            and record.status in (SessionStatus.CLOSED, SessionStatus.FAILED, SessionStatus.EXPIRED)
                            and (record.kv_handle is None or record.kv_released)):
                        del self._sessions[key]
                        removed += 1
                finally:
                    record.lock.release()
        return removed

    def close_all(self) -> None:
        """停止接单后调用；等待同步执行结束，再尽力回收每个会话的 KV。"""
        with self._sessions_lock:
            records = tuple(self._sessions.values())
        first_error = None
        for record in records:
            with record.lock:
                try:
                    # RLock 允许同线程 runner 回调重入；不得将重入视为执行已结束。
                    if record.executing:
                        raise SafeError(ErrorCode.SESSION_INVALID)
                    if record.status in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                        record.status = transition(record.status, SessionStatus.CLOSED)
                    self._release_locked(record)
                except Exception as exc:
                    first_error = first_error or exc
        if first_error is not None:
            raise first_error

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
        if record.executing:
            return  # 同线程回调查询不允许释放在用KV；绝对TTL在前向返回后核验。
        if record.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
            return
        now = self._clock.monotonic()
        if now >= record.absolute_deadline or now - record.last_activity >= self._idle_ttl:
            record.status = transition(record.status, SessionStatus.EXPIRED)
            self._release_locked(record)

    def _release_locked(self, record: _SessionRecord) -> None:
        if record.kv_handle is None or record.kv_released or self._runner is None:
            return
        # ModelRunner.release_kv 合同要求失败后可安全重试，不得复用句柄。
        self._runner.release_kv(record.kv_handle)
        record.kv_released = True

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
