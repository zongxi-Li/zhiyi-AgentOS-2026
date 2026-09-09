"""Coordinator startup lifecycle ordering tests."""

from __future__ import annotations

import pytest

from app.execution.coordinator import RunExecutionCoordinator


class _StartupRuntime:
    def __init__(self) -> None:
        self.flush_count = 0

    async def close_orphaned_runs(self, *, limit: int) -> list[str]:
        assert limit == 200
        return ["run-interrupted-after-restart"]

    def _flush_identity_outbox(self) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
async def test_startup_flushes_identity_outbox_after_closing_orphans() -> None:
    runtime = _StartupRuntime()

    closed = await RunExecutionCoordinator(runtime).startup()

    assert closed == ["run-interrupted-after-restart"]
    assert runtime.flush_count == 1
