"""Application-owned background scheduling for prepared AgentOS runs."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any

from components.planner import ACGPlanningError, TaskDecompositionError

if TYPE_CHECKING:
    from runtime import ExecutionRuntime


logger = logging.getLogger(__name__)


class RunExecutionCoordinator:
    """Own asyncio tasks without becoming a second workflow state machine."""

    def __init__(self, runtime: "ExecutionRuntime") -> None:
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

    async def cancel(self, run_id: str) -> bool:
        """Cancel only the managed workflow task for an explicit Run cancel."""
        async with self._lock:
            task = self._tasks.get(run_id)
        if task is None or task.done() or task is asyncio.current_task():
            return False
        task.cancel()
        return True

    async def startup(self, *, orphan_limit: int = 200) -> list[str]:
        self._accepting = True
        closed = await self.runtime.close_orphaned_runs(limit=orphan_limit)
        # close_orphaned_runs persists terminal Runtime state and its
        # run.finished lifecycle event.  Runtime construction performs the
        # initial identity reconciliation before this startup hook, so flush
        # once more here or the identity projection can remain stale at
        # running while the authoritative Runtime is already failed.
        flush_identity_outbox = getattr(self.runtime, "_flush_identity_outbox", None)
        if callable(flush_identity_outbox):
            flush_identity_outbox()
        return closed

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
            # An operator cancel already persisted CANCELLED before this task
            # is interrupted. Do not misclassify it as worker shutdown.
            try:
                if self.runtime.workflow_store.get_run(run_id).status.value == "cancelled":
                    return
            except Exception:
                pass
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
                    error_code=self._error_code(exc),
                    error_message=self.runtime._safe_error_message(exc),
                    error_metadata=self._error_metadata(exc),
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

    @staticmethod
    def _error_code(exc: Exception) -> str:
        cause_code = RunExecutionCoordinator._cause_code(exc)
        if cause_code == "MODEL_CONNECTION_INTERRUPTED":
            return "model_connection_interrupted"
        if cause_code == "MODEL_TIMEOUT":
            return "model_timeout"
        if isinstance(exc, TaskDecompositionError):
            return "task_decomposition_failed"
        if isinstance(exc, ACGPlanningError):
            return "acg_planning_failed"
        return "workflow_execution_failed"

    @staticmethod
    def _cause_code(exc: BaseException) -> str | None:
        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            code = str(getattr(current, "cause_code", None) or getattr(current, "code", None) or "").upper()
            if code in {"MODEL_CONNECTION_INTERRUPTED", "MODEL_TIMEOUT"}:
                return code
            current = current.__cause__ or current.__context__
        return None

    @staticmethod
    def _error_metadata(exc: BaseException) -> dict[str, Any]:
        current: BaseException | None = exc
        while current is not None:
            metadata = getattr(current, "metadata", None)
            if isinstance(metadata, dict):
                return {key: metadata[key] for key in (
                    "stage", "attemptCount", "retryCount", "streamUsed",
                    "timeoutSeconds", "elapsedMs", "transportErrorClass",
                ) if key in metadata}
            current = current.__cause__ or current.__context__
        return {}


__all__ = ["RunExecutionCoordinator"]
