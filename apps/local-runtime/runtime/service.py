"""Lifecycle wrapper for the independent Local Runtime process."""

from __future__ import annotations

from contracts.local_runtime import LocalRuntimeExecutionRequest, LocalRuntimeExecutionResult

from runtime.errors import RuntimeLifecycleError
from .executor import LocalRuntimeExecutor


class LocalRuntimeService:
    def __init__(self, executor: LocalRuntimeExecutor) -> None:
        self.executor = executor
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self.executor.process_service is not None:
            self.executor.process_service.shutdown()

    async def execute(self, request: LocalRuntimeExecutionRequest) -> LocalRuntimeExecutionResult:
        if not self._running:
            raise RuntimeLifecycleError()
        return await self.executor.execute(request)


__all__ = ["LocalRuntimeService"]
