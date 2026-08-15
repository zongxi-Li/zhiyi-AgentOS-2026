"""Application-owned background scheduling for prepared AgentOS runs."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime import WorkflowRuntime


logger = logging.getLogger(__name__)


class RunExecutionCoordinator:
    """Own asyncio tasks without becoming a second workflow state machine."""

    def __init__(self, runtime: "WorkflowRuntime") -> None:
        self.runtime = runtime
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._accepting = True

    async def submit(self, run_id: str) -> bool:
        """Submit one pending run once in this process."""
        async with self._lock:
            existing = self._tasks.get(run_id)
            if existing is not None and not existing.done():
                return False
            if not self._accepting:
                raise RuntimeError("workflow execution coordinator is shutting down")
            run = self.runtime.workflow_store.get_run(run_id)
            if run.status.value != "pending" or run.started_at is not None:
                return False
            task = asyncio.create_task(self._run_managed(run_id), name=f"workflow-run:{run_id}")
            self._tasks[run_id] = task
        logger.info("run_submitted", extra={"runId": run_id})
        return True

    def is_active(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    async def startup(self, *, orphan_limit: int = 200) -> list[str]:
        self._accepting = True
        return await self.runtime.close_orphaned_runs(limit=orphan_limit)

    async def shutdown(self) -> None:
        async with self._lock:
            self._accepting = False
            tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_managed(self, run_id: str) -> None:
        started = monotonic()
        try:
            await self.runtime.execute_prepared_run(run_id)
        except asyncio.CancelledError:
            try:
                await self.runtime.fail_run_safely(
                    run_id,
                    error_code="worker_shutdown",
                    error_message="workflow execution interrupted by service shutdown",
                )
            except Exception:
                logger.exception("failed to persist worker shutdown", extra={"runId": run_id})
            raise
        except Exception as exc:
            try:
                await self.runtime.fail_run_safely(
                    run_id,
                    error_code="workflow_execution_failed",
                    error_message=self.runtime._safe_error_message(exc),
                )
            except Exception:
                logger.exception("failed to persist managed run failure", extra={"runId": run_id})
            logger.exception(
                "managed workflow execution failed",
                extra={
                    "runId": run_id,
                    "elapsedMs": int((monotonic() - started) * 1000),
                    "errorType": type(exc).__name__,
                },
            )
        finally:
            current = asyncio.current_task()
            async with self._lock:
                if self._tasks.get(run_id) is current:
                    self._tasks.pop(run_id, None)


__all__ = ["RunExecutionCoordinator"]
