import asyncio
from threading import Event

import pytest

from support.run_locks import RunLock


@pytest.mark.asyncio
async def test_worker_owned_run_lock_does_not_block_async_requests():
    lock = RunLock()
    started = Event()
    release = Event()

    def hold():
        with lock:
            started.set()
            release.wait(2)

    async def enter():
        async with lock:
            return "acquired"

    worker = asyncio.create_task(asyncio.to_thread(hold))
    assert await asyncio.to_thread(started.wait, 1)
    waiter = asyncio.create_task(enter())
    try:
        await asyncio.sleep(0)
        assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    finally:
        release.set()
        await worker

    assert await asyncio.wait_for(enter(), timeout=1) == "acquired"
