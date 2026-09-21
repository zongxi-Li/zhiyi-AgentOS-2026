"""In-process transport harness for contract and runtime integration tests."""

from __future__ import annotations

from contracts.local_runtime import LocalRuntimeExecutionRequest, LocalRuntimeExecutionResult

from runtime.service import LocalRuntimeService


class InProcessLocalRuntimeTransport:
    """Exercise the PR-1 transport seam without selecting a wire protocol."""

    def __init__(self, service: LocalRuntimeService) -> None:
        self.service = service

    async def execute(self, request: LocalRuntimeExecutionRequest) -> LocalRuntimeExecutionResult:
        return await self.service.execute(request)


__all__ = ["InProcessLocalRuntimeTransport"]
