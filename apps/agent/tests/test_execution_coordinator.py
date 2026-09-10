"""Coordinator startup lifecycle ordering tests."""

from __future__ import annotations

import asyncio
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
