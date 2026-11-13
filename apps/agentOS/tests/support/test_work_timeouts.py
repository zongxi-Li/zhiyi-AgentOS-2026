import asyncio

import pytest

from support.work_timeouts import human_approval_wait, work_timeout


@pytest.mark.asyncio
async def test_human_wait_pauses_nested_work_deadlines():
    async with work_timeout(.08) as outer:
        async with work_timeout(.04):
            with human_approval_wait():
                await asyncio.sleep(.12)
            await asyncio.sleep(.005)
        assert outer.when() > asyncio.get_running_loop().time()


@pytest.mark.asyncio
async def test_work_itself_is_still_bounded():
    with pytest.raises(TimeoutError):
        async with work_timeout(.02):
            await asyncio.sleep(.2)


@pytest.mark.asyncio
async def test_approval_expiry_and_external_cancellation_are_not_paused():
    with pytest.raises(TimeoutError):
        async with work_timeout(.05):
            with human_approval_wait():
                async with asyncio.timeout(.02):
                    await asyncio.sleep(.2)
    entered = asyncio.Event()
    async def waiting():
        async with work_timeout(.05):
            with human_approval_wait():
                entered.set()
                await asyncio.Event().wait()
    task = asyncio.create_task(waiting())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_concurrent_approval_waits_resume_only_after_last_waiter():
    entered = [asyncio.Event(), asyncio.Event()]
    released = [asyncio.Event(), asyncio.Event()]

    async def waiting(index):
        with human_approval_wait():
            entered[index].set()
            await released[index].wait()

    tasks = []
    try:
        async with work_timeout(.05) as budget:
            tasks = [asyncio.create_task(waiting(index)) for index in range(2)]
            await asyncio.gather(*(event.wait() for event in entered))
            released[0].set()
            await tasks[0]
            assert budget.when() is None
            await asyncio.sleep(.08)
            released[1].set()
            await tasks[1]
            assert budget.when() > asyncio.get_running_loop().time()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_waiters_preserve_shared_pause_and_finished_scope():
    entered = [asyncio.Event(), asyncio.Event()]

    async def waiting(index):
        with human_approval_wait():
            entered[index].set()
            await asyncio.Event().wait()

    tasks = []
    try:
        async with work_timeout(.05) as budget:
            tasks = [asyncio.create_task(waiting(index)) for index in range(2)]
            await asyncio.gather(*(event.wait() for event in entered))
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            assert budget.when() is None
        # The surviving child retains its inherited scope after its owner
        # exits. Its cleanup must not reschedule the finished timer or mask
        # the external cancellation with RuntimeError.
        tasks[1].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[1]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
