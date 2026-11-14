"""P3 会话事务验收：先固定行为，再实现进程内短时存储。"""

from __future__ import annotations

import threading

import pytest

from safe.application.session import SessionService
from safe.contracts.activation import ActivationEnvelope
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.session import SessionStatus, StepRequest
from safe.infrastructure.storage.memory_sessions import MemorySessionStore


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


def service(clock: ManualClock | None = None) -> SessionService:
    clock = clock or ManualClock()
    store = MemorySessionStore(clock=clock, idle_ttl=60.0, absolute_ttl=300.0)
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

