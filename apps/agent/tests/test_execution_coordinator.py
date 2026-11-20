"""Coordinator startup lifecycle ordering tests."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
import sqlite3
from threading import get_ident
from types import SimpleNamespace

import pytest

from app.execution.coordinator import RunExecutionCoordinator


class _StartupRuntime:
    def __init__(self) -> None:
        self.flush_count = 0

    async def close_orphaned_runs(self, *, limit: int) -> list[str]:
        assert limit == 200
        return ["run-interrupted-after-restart"]

    def _flush_identity_outbox(self, *, raise_on_failure: bool = True) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
@pytest.mark.parametrize('permitted', [False, True])
@pytest.mark.parametrize('started', [False, True])
async def test_explicit_cancel_releases_owned_task_without_waiting_for_shutdown(permitted, started):
    calls = []
    run = SimpleNamespace(status=SimpleNamespace(value='pending'), started_at=None)
    async def execute(run_id):
        calls.append(run_id)
    runtime = SimpleNamespace(workflow_store=SimpleNamespace(get_run=lambda _: run),
                              execute_prepared_run=execute)
    coordinator = RunExecutionCoordinator(runtime)
    if permitted:
        coordinator._create_permitted_task(SimpleNamespace(run_id='cancelled-run', dispatch_id='accepted'))
    else:
        assert await coordinator.submit('cancelled-run')
    task = coordinator._tasks['cancelled-run']
    if started:
        await asyncio.sleep(0)
    run.status.value = 'cancelled'
    assert await coordinator.cancel('cancelled-run')
    await asyncio.gather(task, return_exceptions=True)
    assert task.done()
    assert task.cancelled() is (not started)
    assert not calls
    assert not coordinator.is_active('cancelled-run')
    assert 'cancelled-run' not in coordinator._tasks
    assert not await coordinator.cancel('cancelled-run')
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_cancelled_task_completion_cannot_remove_a_newer_owner():
    calls = []
    release = asyncio.Event()
    async def execute(run_id):
        calls.append(run_id)
        await release.wait()
    coordinator = RunExecutionCoordinator(SimpleNamespace(execute_prepared_run=execute))
    command = SimpleNamespace(run_id='same-run', dispatch_id='accepted')
    coordinator._create_permitted_task(command)
    previous = coordinator._tasks['same-run']
    assert await coordinator.cancel('same-run')
    coordinator._create_permitted_task(command)
    replacement = coordinator._tasks['same-run']
    await asyncio.gather(previous, return_exceptions=True)
    assert coordinator._tasks.get('same-run') is replacement
    assert coordinator.is_active('same-run')
    release.set()
    await asyncio.gather(replacement)
    assert calls == ['same-run']
    assert not coordinator._tasks
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_removes_task_cancelled_before_coroutine_first_runs():
    calls = []
    async def execute(run_id):
        calls.append(run_id)
    coordinator = RunExecutionCoordinator(SimpleNamespace(execute_prepared_run=execute))
    coordinator._create_permitted_task(SimpleNamespace(run_id='not-started', dispatch_id='accepted-command'))
    await coordinator.shutdown()  # No yield: cancellation precedes the coroutine's try/finally.
    assert not calls
    assert not coordinator._tasks


@pytest.mark.asyncio
async def test_startup_flushes_identity_outbox_after_closing_orphans() -> None:
    runtime = _StartupRuntime()

    closed = await RunExecutionCoordinator(runtime).startup()

    assert closed == ["run-interrupted-after-restart"]
    assert runtime.flush_count == 1


@pytest.mark.asyncio
async def test_startup_survives_identity_projection_dead_letters() -> None:
    """一条投影死信不得阻断服务启动（2026-09-10 崩溃循环事故回归）。"""

    class _CrashingFlushRuntime(_StartupRuntime):
        def _flush_identity_outbox(self, *, raise_on_failure: bool = True) -> None:
            super()._flush_identity_outbox(raise_on_failure=raise_on_failure)
            raise RuntimeError("identity inbox consumption failed: simulated dead letter")

    runtime = _CrashingFlushRuntime()

    closed = await RunExecutionCoordinator(runtime).startup()

    assert closed == ["run-interrupted-after-restart"]
    assert runtime.flush_count == 1


@pytest.mark.asyncio
async def test_submit_accepts_in_place_retry_with_original_started_at() -> None:
    executed = asyncio.Event()
    run = SimpleNamespace(
        status=SimpleNamespace(value="retrying"),
        started_at=object(),
    )
    runtime = SimpleNamespace(
        workflow_store=SimpleNamespace(get_run=lambda _run_id: run),
    )

    async def execute_prepared_run(run_id: str) -> None:
        assert run_id == "run-retrying"
        executed.set()

    runtime.execute_prepared_run = execute_prepared_run
    coordinator = RunExecutionCoordinator(runtime)

    assert await coordinator.submit("run-retrying") is True
    await asyncio.wait_for(executed.wait(), timeout=1)
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_durable_wake_redelivery_and_event_burst_share_one_managed_task() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    run = SimpleNamespace(status=SimpleNamespace(value="retrying"), started_at=object())
    calls = []
    runtime = SimpleNamespace(workflow_store=SimpleNamespace(get_run=lambda run_id: run))
    async def prepare():
        return ["waiting-run"] if run.status.value == "retrying" else []
    async def execute(run_id):
        calls.append(run_id)
        started.set()
        await release.wait()
        run.status.value = "completed"
    runtime.prepare_planning_wakeups = prepare
    runtime.execute_prepared_run = execute
    coordinator = RunExecutionCoordinator(runtime)
    try:
        await coordinator.reconcile_waits()
        await asyncio.wait_for(started.wait(), timeout=1)
        for _ in range(10):
            coordinator.notify_state_changed()
        await asyncio.gather(*(coordinator.reconcile_waits() for _ in range(10)))
        assert calls == ["waiting-run"]
        release.set()
        while coordinator.is_active("waiting-run"):
            await asyncio.sleep(0)
        await coordinator.reconcile_waits()
        assert calls == ["waiting-run"]
    finally:
        release.set()
        await coordinator.shutdown()
    assert coordinator._wake_task.done()


def _review_dispatch(graph_version=1):
    return SimpleNamespace(run_id="review-run", mission_id="mission", dispatch_id=f"accepted-v{graph_version}",
                           actor_id="accepted-owner", tenant_id="accepted-tenant", graph_version=graph_version)


def _review_run(status="waiting_review", *, graph_version=1, blocked=False):
    return SimpleNamespace(run_id="review-run", mission_id="mission", started_at=object(),
        record_state=SimpleNamespace(value="active"), status=SimpleNamespace(value=status),
        execution_state={"graphActivation": {}, "graphVersion": graph_version,
                         "workspaceReviewContinuation": {"sourceGraphVersion": 1, "blocked": blocked}})


def _review_coordinator(monkeypatch, tmp_path, run, command, resume):
    monkeypatch.setattr("support.run_execution_fence.acquire_run_fence", lambda *_: nullcontext())
    state = {"run": run, "command": command}
    calls = []

    async def close_orphans(*, limit):
        return []

    async def fail(run_id, **kwargs):
        calls.append(("fail", run_id))
        return state["run"]

    runtime = SimpleNamespace(
        workflow_store=SimpleNamespace(db_path=tmp_path / "workflow.sqlite",
            get_run=lambda _: state["run"], list_non_terminal_runs=lambda **_: (state["run"],)),
        execution_dispatch_store=SimpleNamespace(get=lambda _: state["command"], commands=lambda: [state["command"]]),
        workspace_review_continuation=SimpleNamespace(resume=resume), close_orphaned_runs=close_orphans,
        run_lock_manager=SimpleNamespace(lock_for=lambda _: nullcontext()), fail_run_safely=fail,
        reconcile_execution_checkpoint=lambda run_id: calls.append(("reconcile", run_id)),
    )
    coordinator = RunExecutionCoordinator(runtime)
    monkeypatch.setattr(coordinator, "_create_permitted_task", lambda accepted: calls.append(("schedule", accepted.dispatch_id)))
    return coordinator, runtime, state, calls


@pytest.mark.asyncio
async def test_startup_restores_native_execution_for_decided_but_unapplied_review(monkeypatch, tmp_path):
    run, command = _review_run("running"), _review_dispatch()

    def premature_continuation(_):
        pytest.fail("A queued decision must settle through native checkpoint recovery first")

    coordinator, _, _, calls = _review_coordinator(monkeypatch, tmp_path, run, command, premature_continuation)
    monkeypatch.setattr(coordinator, "_validate_permitted", lambda current, accepted: calls.append(("validate", accepted.dispatch_id)))
    assert await coordinator.startup() == []
    assert calls == [("reconcile", run.run_id), ("validate", command.dispatch_id), ("schedule", command.dispatch_id)]
    assert run.status.value == "running"
    assert run.execution_state["workspaceReviewContinuation"]["sourceGraphVersion"] == 1
    await coordinator.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_startup_review_wait_never_dispatches_before_continuation_confirms(monkeypatch, tmp_path, blocked):
    from app.security.internal_auth import _trusted_user_context

    run, command = _review_run(blocked=blocked), _review_dispatch()
    server_thread = get_ident()
    resumed = []

    def waiting(current):
        principal = _trusted_user_context.get()
        resumed.append((current.run_id, principal.user_id, principal.tenant_id, get_ident()))
        return None

    coordinator, _, _, calls = _review_coordinator(monkeypatch, tmp_path, run, command, waiting)
    before = _trusted_user_context.get()
    assert await coordinator.startup() == []
    if blocked:
        assert not resumed
    else:
        assert resumed[0][:3] == (run.run_id, command.actor_id, command.tenant_id)
        assert resumed[0][3] != server_thread
    assert not calls and _trusted_user_context.get() is before
    assert run.status.value == "waiting_review"
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_activated_review_uses_new_durable_dispatch_after_lost_ack(monkeypatch, tmp_path):
    from app.security.internal_auth import _trusted_user_context

    run, parent = _review_run("retrying", graph_version=2), _review_dispatch()
    next_command = _review_dispatch(2)
    resumed = _review_run("retrying", graph_version=2)
    resumed.execution_state.pop("workspaceReviewContinuation")
    state = {}

    def continue_review(_):
        assert _trusted_user_context.get().user_id == parent.actor_id
        state.update(run=resumed, command=next_command)
        return resumed

    coordinator, _, holder, calls = _review_coordinator(monkeypatch, tmp_path, run, parent, continue_review)
    state = holder

    def validate(current, accepted):
        assert current is resumed and accepted is next_command
        assert _trusted_user_context.get().user_id == next_command.actor_id
        calls.append(("validate", accepted.dispatch_id))

    monkeypatch.setattr(coordinator, "_validate_permitted", validate)
    assert await coordinator.submit(run.run_id)
    assert calls == [("reconcile", run.run_id), ("validate", next_command.dispatch_id), ("schedule", next_command.dispatch_id)]
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_cancel_during_review_reconciliation_cannot_schedule_stale_resume(monkeypatch, tmp_path):
    run, command = _review_run("retrying", graph_version=2), _review_dispatch(2)
    resumed = _review_run("retrying", graph_version=2)
    resumed.execution_state.pop("workspaceReviewContinuation")
    coordinator, runtime, state, calls = _review_coordinator(monkeypatch, tmp_path, run, command, lambda _: resumed)

    def cancel_before_validation(run_id):
        cancelled = _review_run("cancelled", graph_version=2)
        state["run"] = cancelled
        calls.append(("cancel", run_id))

    runtime.reconcile_execution_checkpoint = cancel_before_validation
    assert not await coordinator.submit(run.run_id)
    assert calls == [("cancel", run.run_id), ("fail", run.run_id)]
    assert state["run"].status.value == "cancelled" and not coordinator.is_active(run.run_id)
    await coordinator.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["read", "checkpoint", "permit", "fence"])
async def test_dispatch_transient_failures_use_existing_wakeup_without_terminalizing_or_hot_retry(monkeypatch, tmp_path, boundary):
    from support.run_execution_fence import RunFenceBusy

    now = [100.0]
    monkeypatch.setattr("app.execution.coordinator.monotonic", lambda: now[0])
    run, command = _review_run("retrying"), _review_dispatch()
    run.execution_state.pop("workspaceReviewContinuation")
    coordinator, runtime, state, calls = _review_coordinator(monkeypatch, tmp_path, run, command, lambda _: None)
    failures = []

    def fail_once():
        failures.append(boundary)
        if len(failures) == 1:
            raise RunFenceBusy("occupied") if boundary == "fence" else sqlite3.OperationalError("unavailable")

    if boundary == "read":
        def read(_):
            fail_once()
            return state["run"]
        runtime.workflow_store.get_run = read
    elif boundary == "checkpoint":
        runtime.reconcile_execution_checkpoint = lambda _: fail_once()
    elif boundary == "fence":
        def fence(*_):
            fail_once()
            return nullcontext()
        monkeypatch.setattr("support.run_execution_fence.acquire_run_fence", fence)

    def validate(current, accepted):
        if boundary == "permit":
            fail_once()
        assert current is run and accepted is command
    monkeypatch.setattr(coordinator, "_validate_permitted", validate)
    try:
        async with coordinator._lock:
            assert not await coordinator._schedule_permitted(command, recover=True)
        assert run.status.value == "retrying" and not any(item[0] in {"schedule", "fail"} for item in calls)
        assert coordinator._wake_task is not None
        assert coordinator._deferred_dispatches[run.run_id] == (101.0, 1.0)
        for _ in range(20):
            coordinator.notify_state_changed()
            await coordinator.reconcile_waits()
        assert len(failures) == 1
        now[0] = 101.0
        await coordinator.reconcile_waits()
        assert calls[-1] == ("schedule", command.dispatch_id)
        assert not any(item[0] == "fail" for item in calls)
        assert not coordinator._deferred_dispatches
    finally:
        await coordinator.shutdown()


@pytest.mark.asyncio
async def test_deferred_dispatch_reloads_authority_after_repeated_storage_failures(monkeypatch, tmp_path):
    now = [10.0]
    monkeypatch.setattr("app.execution.coordinator.monotonic", lambda: now[0])
    run, command = _review_run("retrying"), _review_dispatch()
    run.execution_state.pop("workspaceReviewContinuation")
    coordinator, runtime, state, calls = _review_coordinator(monkeypatch, tmp_path, run, command, lambda _: None)
    attempts = []

    def checkpoint(run_id):
        attempts.append(run_id)
        if len(attempts) <= 40:
            raise sqlite3.OperationalError("temporarily unavailable")
    runtime.reconcile_execution_checkpoint = checkpoint
    monkeypatch.setattr(coordinator, "_validate_permitted", lambda current, accepted:
        calls.append(("validate", accepted.dispatch_id)))
    try:
        async with coordinator._lock:
            assert not await coordinator._schedule_permitted(command, recover=True)
        for _ in range(39):
            at, delay = coordinator._deferred_dispatches[run.run_id]
            assert 1 <= delay <= 60
            now[0] = at
            await coordinator.reconcile_waits()
        assert len(attempts) == 40 and not calls
        next_command = _review_dispatch(2)
        state["command"] = next_command
        run.execution_state["graphVersion"] = 2
        now[0] = coordinator._deferred_dispatches[run.run_id][0]
        await coordinator.reconcile_waits()
        assert len(attempts) == 41
        assert calls == [("validate", next_command.dispatch_id), ("schedule", next_command.dispatch_id)]
        assert not coordinator._deferred_dispatches
    finally:
        await coordinator.shutdown()


@pytest.mark.asyncio
async def test_cancel_during_dispatch_backoff_discards_wakeup_without_execution(monkeypatch, tmp_path):
    now = [10.0]
    monkeypatch.setattr("app.execution.coordinator.monotonic", lambda: now[0])
    run, command = _review_run("retrying"), _review_dispatch()
    run.execution_state.pop("workspaceReviewContinuation")
    coordinator, runtime, _, calls = _review_coordinator(monkeypatch, tmp_path, run, command, lambda _: None)
    runtime.reconcile_execution_checkpoint = lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("busy"))
    try:
        async with coordinator._lock:
            assert not await coordinator._schedule_permitted(command, recover=True)
        run.status.value = "cancelled"
        now[0] = coordinator._deferred_dispatches[run.run_id][0]
        await coordinator.reconcile_waits()
        assert not calls and not coordinator._deferred_dispatches
        assert run.status.value == "cancelled"
    finally:
        await coordinator.shutdown()


@pytest.mark.asyncio
async def test_permission_denial_is_permanent_and_never_enters_dispatch_backoff(monkeypatch, tmp_path):
    run, command = _review_run("retrying"), _review_dispatch()
    run.execution_state.pop("workspaceReviewContinuation")
    coordinator, _, _, calls = _review_coordinator(monkeypatch, tmp_path, run, command, lambda _: None)
    monkeypatch.setattr(coordinator, "_validate_permitted", lambda *_:
        (_ for _ in ()).throw(PermissionError("revoked")))
    assert not await coordinator.submit(run.run_id)
    assert calls == [("reconcile", run.run_id), ("fail", run.run_id)]
    assert not coordinator._deferred_dispatches and coordinator._wake_task is None
    await coordinator.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", [False, True])
async def test_deferred_dispatch_journal_read_distinguishes_storage_from_integrity_failure(monkeypatch, tmp_path, corrupt):
    now = [10.0]
    monkeypatch.setattr("app.execution.coordinator.monotonic", lambda: now[0])
    run, command = _review_run("retrying"), _review_dispatch()
    run.execution_state.pop("workspaceReviewContinuation")
    coordinator, runtime, state, calls = _review_coordinator(monkeypatch, tmp_path, run, command, lambda _: None)
    runtime.reconcile_execution_checkpoint = lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("busy"))
    reads = []

    def read(run_id):
        reads.append(run_id)
        if len(reads) == 1:
            raise ValueError("checksum") if corrupt else sqlite3.OperationalError("busy")
        return state["command"]

    try:
        async with coordinator._lock:
            assert not await coordinator._schedule_permitted(command, recover=True)
        runtime.execution_dispatch_store.get = read
        now[0] = coordinator._deferred_dispatches[run.run_id][0]
        await coordinator.reconcile_waits()
        for _ in range(10):
            await coordinator.reconcile_waits()
        assert reads == [run.run_id]
        if corrupt:
            assert calls == [("fail", run.run_id)] and not coordinator._deferred_dispatches
        else:
            assert not calls and coordinator._deferred_dispatches[run.run_id] == (13.0, 2.0)
    finally:
        await coordinator.shutdown()


@pytest.mark.asyncio
async def test_existing_monitor_recovers_dispatch_without_a_planner_wait(monkeypatch, tmp_path):
    now = [10.0]
    monkeypatch.setattr("app.execution.coordinator.monotonic", lambda: now[0])
    run, command = _review_run("retrying"), _review_dispatch()
    run.execution_state.pop("workspaceReviewContinuation")
    coordinator, runtime, _, calls = _review_coordinator(monkeypatch, tmp_path, run, command, lambda _: None)
    scheduled = asyncio.Event()
    attempts = []

    def checkpoint(run_id):
        attempts.append(run_id)
        if len(attempts) == 1:
            raise sqlite3.OperationalError("busy")

    def schedule(accepted):
        calls.append(("schedule", accepted.dispatch_id))
        scheduled.set()

    runtime.reconcile_execution_checkpoint = checkpoint
    monkeypatch.setattr(coordinator, "_validate_permitted", lambda *_: None)
    monkeypatch.setattr(coordinator, "_create_permitted_task", schedule)
    try:
        async with coordinator._lock:
            assert not await coordinator._schedule_permitted(command, recover=True)
        monitor = coordinator._wake_task
        now[0] = coordinator._deferred_dispatches[run.run_id][0]
        coordinator.notify_state_changed()
        await asyncio.wait_for(scheduled.wait(), timeout=1)
        assert attempts == [run.run_id, run.run_id]
        assert calls == [("schedule", command.dispatch_id)] and not coordinator._deferred_dispatches
        assert coordinator._wake_task is monitor and monitor.done()
    finally:
        await coordinator.shutdown()
