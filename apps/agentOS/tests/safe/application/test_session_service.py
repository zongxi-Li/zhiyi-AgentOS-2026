"""P3 会话事务验收：先固定行为，再实现进程内短时存储。"""

from __future__ import annotations

import threading

import pytest

from safe.application.session import SessionService
from safe.contracts.activation import ActivationEnvelope
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.session import SessionStatus, StepRequest
from safe.infrastructure.storage.memory_sessions import MemorySessionStore
from safe.ports.model_runner import KVHandle


class ManualClock:
    def __init__(self) -> None:
        self.value = 100.0

    def monotonic(self) -> float:
        return self.value

    def utc_timestamp(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def request(request_id: str = "request-0", *, step: int = 0, phase: str = "prefill") -> StepRequest:
    return StepRequest(
        request_id=request_id,
        session_id="session-1",
        manifest_digest="a" * 64,
        step=step,
        phase=phase,
        activation=ActivationEnvelope(
            shape=(1, 1, 1),
            raw_bytes=4,
            sha256="b" * 64,
            data="AAAAAA==",
        ),
    )


class FakeRunner:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.released: list[KVHandle] = []
        self.fail_create = False
        self.fail_release = False

    def create_kv(self, session_id: str) -> KVHandle:
        if self.fail_create:
            raise RuntimeError("KV allocation failed")
        self.created.append(session_id)
        return KVHandle(f"kv-{session_id}")

    def release_kv(self, handle: KVHandle) -> None:
        if self.fail_release:
            raise RuntimeError("KV release failed")
        self.released.append(handle)

    def close(self) -> None:
        pass


def service(clock: ManualClock | None = None, runner: FakeRunner | None = None) -> SessionService:
    clock = clock or ManualClock()
    store = MemorySessionStore(clock=clock, idle_ttl=60.0, absolute_ttl=300.0, runner=runner)
    return SessionService(store)


def test_create_binds_owner_and_manifest_without_raw_prompt() -> None:
    safe = service()
    view = safe.create("owner-1", "a" * 64, session_id="session-1")
    assert view.status is SessionStatus.CREATED
    assert view.next_step == 0
    assert safe.view("owner-1", "session-1") == view
    with pytest.raises(SafeError) as error:
        safe.view("owner-2", "session-1")
    assert error.value.code is ErrorCode.SESSION_INVALID


def test_step_is_idempotent_and_same_request_id_cannot_change_payload() -> None:
    safe = service()
    safe.create("owner-1", "a" * 64, session_id="session-1")
    calls: list[str] = []

    def runner(value: StepRequest) -> tuple[int, bool]:
        calls.append(value.request_id)
        return 42, False

    first = safe.execute("owner-1", request(), runner)
    repeated = safe.execute("owner-1", request(), runner)
    assert repeated == first
    assert calls == ["request-0"]
    with pytest.raises(SafeError) as error:
        safe.execute("owner-1", request(step=0, request_id="request-0").model_copy(
            update={"position_offset": 1}
        ), runner)
    assert error.value.code is ErrorCode.IDEMPOTENCY_CONFLICT


def test_step_order_terminal_state_and_failure_are_irreversible() -> None:
    safe = service()
    safe.create("owner-1", "a" * 64, session_id="session-1")
    receipt = safe.execute("owner-1", request(), lambda _: (7, True))
    assert receipt.finished is True
    assert safe.view("owner-1", "session-1").status is SessionStatus.CLOSED
    with pytest.raises(SafeError) as error:
        safe.execute("owner-1", request("request-1", step=1, phase="decode"), lambda _: (8, False))
    assert error.value.code is ErrorCode.SESSION_INVALID

    failed = service()
    failed.create("owner-1", "a" * 64, session_id="session-1")
    with pytest.raises(RuntimeError):
        failed.execute("owner-1", request(), lambda _: (_ for _ in ()).throw(RuntimeError("runner failed")))
    assert failed.view("owner-1", "session-1").status is SessionStatus.FAILED
    with pytest.raises(SafeError) as error:
        failed.close("owner-1", "session-1")
    assert error.value.code is ErrorCode.SESSION_INVALID


def test_idle_and_absolute_ttl_expire_without_query_renewal() -> None:
    clock = ManualClock()
    safe = service(clock)
    safe.create("owner-1", "a" * 64, session_id="session-1")
    clock.advance(59.0)
    safe.view("owner-1", "session-1")
    clock.advance(2.0)
    assert safe.view("owner-1", "session-1").status is SessionStatus.EXPIRED
    with pytest.raises(SafeError) as error:
        safe.execute("owner-1", request(), lambda _: (1, False))
    assert error.value.code is ErrorCode.SESSION_INVALID

    absolute_clock = ManualClock()
    absolute = service(absolute_clock)
    absolute.create("owner-1", "a" * 64, session_id="session-1")
    for step in range(5):
        absolute_clock.advance(50.0)
        absolute.execute(
            "owner-1",
            request(f"request-{step}", step=step, phase="prefill" if step == 0 else "decode"),
            lambda _: (1, False),
        )
    absolute_clock.advance(51.0)
    absolute_clock.advance(2.0)
    assert absolute.view("owner-1", "session-1").status is SessionStatus.EXPIRED


def test_same_step_is_executed_once_under_competing_threads() -> None:
    safe = service()
    safe.create("owner-1", "a" * 64, session_id="session-1")
    calls = 0
    lock = threading.Lock()

    def runner(_: StepRequest) -> tuple[int, bool]:
        nonlocal calls
        with lock:
            calls += 1
        return 9, False

    results: list[object] = []

    def invoke() -> None:
        try:
            results.append(safe.execute("owner-1", request(), runner))
        except Exception as error:  # pragma: no cover - 失败时由断言报告
            results.append(error)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == 1
    assert len(results) == 2
    assert results[0] == results[1]


def test_kv_is_allocated_once_and_released_on_terminal_paths() -> None:
    runner = FakeRunner()
    safe = service(runner=runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")
    assert runner.created == ["session-1"]
    safe.close("owner-1", "session-1")
    assert runner.released == [KVHandle("kv-session-1")]
    assert safe.cleanup_expired() == 0
    assert runner.released == [KVHandle("kv-session-1")]

    failed_runner = FakeRunner()
    failed = service(runner=failed_runner)
    failed.create("owner-1", "a" * 64, session_id="session-1")
    with pytest.raises(RuntimeError):
        failed.execute("owner-1", request(), lambda _: (_ for _ in ()).throw(RuntimeError("runner failed")))
    assert failed_runner.released == [KVHandle("kv-session-1")]


def test_kv_is_released_on_expiry_and_failed_creation_is_rolled_back() -> None:
    clock = ManualClock()
    runner = FakeRunner()
    safe = service(clock, runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")
    clock.advance(60.0)
    assert safe.cleanup_expired() == 1
    assert runner.released == [KVHandle("kv-session-1")]

    create_failure = FakeRunner()
    create_failure.fail_create = True
    failed = service(runner=create_failure)
    with pytest.raises(RuntimeError):
        failed.create("owner-1", "a" * 64, session_id="session-2")
    with pytest.raises(SafeError) as error:
        failed.view("owner-1", "session-2")
    assert error.value.code is ErrorCode.SESSION_INVALID


def test_failed_kv_release_remains_retryable_without_reopening_session() -> None:
    runner = FakeRunner()
    runner.fail_release = True
    safe = service(runner=runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")
    with pytest.raises(RuntimeError, match="KV release failed"):
        safe.close("owner-1", "session-1")
    assert safe.view("owner-1", "session-1").status is SessionStatus.CLOSED

    runner.fail_release = False
    assert safe.cleanup_expired() == 0
    assert runner.released == [KVHandle("kv-session-1")]


@pytest.mark.parametrize("write_then_fail", [False, True])
def test_receipt_commit_failure_invalidates_advanced_kv(write_then_fail) -> None:
    """模拟内存回执写入前/后抛错，不能继续使用已推进的模型状态。"""
    class BrokenReceipts(dict):
        def __setitem__(self, key, value):
            if write_then_fail:
                super().__setitem__(key, value)
            raise MemoryError("synthetic receipt commit failure")

    runner = FakeRunner()
    store = MemorySessionStore(runner=runner)
    safe = SessionService(store)
    safe.create("owner-1", "a" * 64, session_id="session-1")
    # 只为模拟容器分配失败注入内部存储；不增加生产环境故障注入接口。
    store._sessions["session-1"].receipts = BrokenReceipts()
    calls = []

    def forward(value):
        calls.append(value.step)
        return 9, False

    with pytest.raises(MemoryError, match="receipt commit failure"):
        safe.execute("owner-1", request(), forward)
    assert safe.view("owner-1", "session-1").status is SessionStatus.FAILED
    assert safe.view("owner-1", "session-1").next_step == 0
    assert safe.receipt("owner-1", "session-1", "request-0") is None
    assert runner.released == [KVHandle("kv-session-1")]
    with pytest.raises(SafeError):
        safe.execute("owner-1", request(), forward)
    assert calls == [0]


def test_absolute_deadline_during_forward_does_not_publish_late_receipt() -> None:
    clock = ManualClock()
    runner = FakeRunner()
    safe = service(clock, runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")

    def slow_forward(_):
        clock.advance(300.0)
        return 9, False

    with pytest.raises(SafeError) as error:
        safe.execute("owner-1", request(), slow_forward)
    assert error.value.code is ErrorCode.SESSION_INVALID
    assert safe.view("owner-1", "session-1").status is SessionStatus.EXPIRED
    assert safe.receipt("owner-1", "session-1", "request-0") is None
    assert runner.released == [KVHandle("kv-session-1")]


def test_execution_error_survives_release_error_and_cleanup_can_retry() -> None:
    runner = FakeRunner()
    runner.fail_release = True
    safe = service(runner=runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")

    def broken_forward(_):
        raise ValueError("synthetic forward failure")

    with pytest.raises(ValueError, match="forward failure"):
        safe.execute("owner-1", request(), broken_forward)
    assert safe.view("owner-1", "session-1").status is SessionStatus.FAILED
    runner.fail_release = False
    safe.cleanup_expired()
    assert runner.released == [KVHandle("kv-session-1")]


def test_cancelled_forward_invalidates_kv() -> None:
    from asyncio import CancelledError

    runner = FakeRunner()
    safe = service(runner=runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")

    def cancelled(_):
        raise CancelledError()

    with pytest.raises(CancelledError):
        safe.execute("owner-1", request(), cancelled)
    assert safe.view("owner-1", "session-1").status is SessionStatus.FAILED
    assert runner.released == [KVHandle("kv-session-1")]


@pytest.mark.parametrize("setting", ["idle_ttl", "absolute_ttl"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_ttl_must_be_finite(setting, value) -> None:
    with pytest.raises(ValueError):
        MemorySessionStore(**{setting: value})


def test_callback_query_cannot_expire_or_close_its_running_kv() -> None:
    clock = ManualClock()
    runner = FakeRunner()
    safe = service(clock, runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")

    def forward(_):
        clock.advance(61.0)
        assert safe.view("owner-1", "session-1").status is SessionStatus.ACTIVE
        assert runner.released == []
        with pytest.raises(SafeError):
            safe.close("owner-1", "session-1")
        with pytest.raises(SafeError):
            safe.execute("owner-1", request(), lambda _: (99, False))
        return 9, False

    assert safe.execute("owner-1", request(), forward).token_id == 9
    assert safe.view("owner-1", "session-1").status is SessionStatus.ACTIVE
    assert runner.released == []


def test_cleanup_attempts_other_sessions_after_one_release_failure() -> None:
    class PartialFailureRunner(FakeRunner):
        def release_kv(self, handle):
            if handle == "kv-session-1":
                raise RuntimeError("synthetic isolated release failure")
            super().release_kv(handle)

    clock = ManualClock()
    runner = PartialFailureRunner()
    safe = service(clock, runner)
    safe.create("owner-1", "a" * 64, session_id="session-1")
    safe.create("owner-1", "a" * 64, session_id="session-2")
    clock.advance(60.0)
    with pytest.raises(RuntimeError, match="isolated release failure"):
        safe.cleanup_expired()
    assert runner.released == [KVHandle("kv-session-2")]
    assert safe.view("owner-1", "session-1").status is SessionStatus.EXPIRED
    assert safe.view("owner-1", "session-2").status is SessionStatus.EXPIRED


def test_completed_receipt_can_be_recovered_after_later_step_failure() -> None:
    """响应丢失后仍可查询成功回执，即使后续步骤已失败也不重新计算。"""
    safe = service()
    safe.create("owner-1", "a" * 64, session_id="session-1")
    first = safe.execute("owner-1", request(), lambda _: (9, False))

    def broken(_):
        raise RuntimeError("synthetic later failure")

    with pytest.raises(RuntimeError):
        safe.execute("owner-1", request("request-1", step=1, phase="decode"), broken)
    assert safe.receipt("owner-1", "session-1", "request-0") == first
    assert safe.execute("owner-1", request(), lambda _: pytest.fail("不得重复执行")) == first

