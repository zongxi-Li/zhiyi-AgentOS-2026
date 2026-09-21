import asyncio

import pytest

from contracts.local_runtime import LocalRuntimeCapability, LocalRuntimeExecutionLimits
from helpers import make_request


class SlowDispatcher:
    async def execute(self, capability, *, root, arguments):
        await asyncio.sleep(0.05)
        return {"unexpected": True}


@pytest.mark.asyncio
async def test_execution_timeout_is_returned_as_stable_error(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    service.executor.dispatcher = SlowDispatcher()
    request = make_request(LocalRuntimeCapability.FS_LIST, {"path": "."}).model_copy(
        update={
            "limits": LocalRuntimeExecutionLimits(
                timeoutSeconds=0.001, maxStdoutBytes=1024, maxStderrBytes=1024
            )
        }
    )
    result = await service.execute(request)
    assert result.error.code == "EXECUTION_TIMEOUT"
    assert result.error.retryable is True


@pytest.mark.asyncio
async def test_request_cancellation_propagates_without_returning_execution_result(
    tmp_path, runtime_factory
):
    service, _store, _resolver = runtime_factory(tmp_path)
    service.executor.dispatcher = SlowDispatcher()
    task = asyncio.create_task(
        service.execute(make_request(LocalRuntimeCapability.FS_LIST, {"path": "."}))
    )
    await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
