"""Bounded handles around the existing approved Local Runtime command path."""
import asyncio
import math
import time
from dataclasses import dataclass, field

from app.tools.contracts import ToolPayload


@dataclass
class CommandJob:
    owner: tuple
    request_id: str
    call_id: str
    task: asyncio.Task | None = None
    execution_id: str = ''
    cursor: int = 0
    status: str = 'running'
    terminal: dict = field(default_factory=dict)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    finished_at: float = 0
    sink: object = None


class CommandJobs:
    def __init__(self):
        self.jobs: dict[tuple, CommandJob] = {}

    async def start(self, execute, *, owner, request_id, call_id, sink, yield_ms=1000):
        wait_seconds = self._wait(yield_ms)
        self._prune()
        key = (*owner, request_id, call_id)
        if key in self.jobs:
            job = self.jobs[key]
            while not job.execution_id and not job.task.done():
                job.changed.clear()
                await job.changed.wait()
            if job.task.done():
                return job.task.result()
            return self._payload(job, 0)
        if len(self.jobs) >= 64:
            raise ValueError('COMMAND_JOB_LIMIT: too many retained commands')
        job = CommandJob(owner=owner, request_id=request_id, call_id=call_id, sink=sink)

        async def event(name, data):
            job.execution_id = data.get('executionId') or job.execution_id
            job.terminal = data.get('terminal') or job.terminal
            job.cursor += 1
            if name in ('execution_completed', 'execution_failed', 'execution_cancelled'):
                job.status = name.removeprefix('execution_')
            job.changed.set()
            if job.sink:
                await job.sink(name, data)

        async def run():
            try:
                return await execute(event)
            finally:
                job.finished_at = time.monotonic()
                job.changed.set()

        # Retain before starting so admission and execution cannot race.
        self.jobs[key] = job
        job.task = asyncio.create_task(run())
        # Retrieving the error here prevents unobserved task exceptions after detaching.
        job.task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        try:
            done, _ = await asyncio.wait({job.task}, timeout=wait_seconds)
            if done:
                return job.task.result()
            # A handle is public only after the approved runtime accepted it.
            while not job.execution_id and not job.task.done():
                job.changed.clear()
                await job.changed.wait()
            if job.task.done():
                return job.task.result()
            return self._payload(job, 0)
        except BaseException:
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            raise

    async def output(self, execution_id, *, owner, after=0, wait_ms=0):
        job = self.owned(execution_id, owner)
        if isinstance(after, bool) or not isinstance(after, int) or after < 0 or after > job.cursor:
            raise ValueError('COMMAND_CURSOR_INVALID')
        if job.cursor == after and not job.task.done():
            job.changed.clear()
            try:
                await asyncio.wait_for(job.changed.wait(), timeout=self._wait(wait_ms))
            except TimeoutError:
                pass
        return self._payload(job, after)

    def owned(self, execution_id, owner):
        self._prune()
        job = next((job for job in self.jobs.values() if job.execution_id == execution_id and job.owner == owner), None)
        if job is None:
            raise ValueError('COMMAND_JOB_UNKNOWN: command is absent, expired, or belongs to another scope')
        return job

    def detach(self, request_id):
        for job in self.jobs.values():
            if job.request_id == request_id:
                job.sink = None

    def _prune(self):
        now = time.monotonic()
        self.jobs = {key: job for key, job in self.jobs.items() if not job.finished_at or now - job.finished_at < 600}

    @staticmethod
    def _wait(value):
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError('COMMAND_WAIT_INVALID')
        return min(value, 10_000) / 1000

    @staticmethod
    def _payload(job, after):
        status = job.status
        error = None
        if job.task.done():
            try:
                job.task.result()
            except asyncio.CancelledError:
                status, error = 'cancelled', 'COMMAND_CANCELLED'
            except Exception as exc:
                status, error = 'failed', getattr(exc, 'code', type(exc).__name__)
                if error == 'EXECUTION_CANCELLED':
                    status = 'cancelled'
                elif error in {'LOCAL_RUNTIME_UNAVAILABLE', 'EXECUTION_INCOMPLETE'}:
                    status = 'unknown'
        return ToolPayload(summary=f'Command {status}', data={
            'executionId': job.execution_id, 'outputCursor': job.cursor,
            'changed': job.cursor > after, 'status': status, 'errorCode': error,
            'terminal': dict(job.terminal),
            'activity': {'kind': 'terminal', 'status': status, 'executionId': job.execution_id},
        })
