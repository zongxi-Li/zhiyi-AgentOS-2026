"""Bound active execution time independently from bounded human approval waits."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class _WorkTimeoutScope:
    timer: asyncio.Timeout
    active: bool = True
    pause_count: int = 0
    remaining: float | None = None


_timeouts = ContextVar("active_work_timeouts", default=())


@asynccontextmanager
async def work_timeout(seconds):
    async with asyncio.timeout(seconds) as timer:
        scope = _WorkTimeoutScope(timer)
        token = _timeouts.set((*_timeouts.get(), scope))
        try:
            yield timer
        finally:
            # Child tasks inherit the same scope, even after its owner exits.
            scope.active = False
            _timeouts.reset(token)


@contextmanager
def human_approval_wait():
    """Pause only registered work deadlines; approval TTL and cancellation stay live."""
    loop = asyncio.get_running_loop()
    paused = []
    for scope in _timeouts.get():
        if not scope.active or scope.timer.expired():
            continue
        if not scope.pause_count:
            deadline = scope.timer.when()
            if deadline is None:
                continue
            scope.remaining = max(0, deadline - loop.time())
            scope.timer.reschedule(None)
        # ContextVar values are shared with child tasks. Keep the deadline
        # paused until every overlapping approval wait has left its scope.
        scope.pause_count += 1
        paused.append(scope)
    try:
        yield
    finally:
        for scope in paused:
            scope.pause_count -= 1
            if scope.pause_count:
                continue
            seconds = scope.remaining
            scope.remaining = None
            if scope.active and seconds is not None and not scope.timer.expired():
                scope.timer.reschedule(loop.time() + seconds)
