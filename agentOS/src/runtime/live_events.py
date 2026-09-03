"""Run-scoped in-process fan-out for transient RuntimeEvents."""
from __future__ import annotations

import asyncio
from threading import Lock
from collections import defaultdict
from typing import AsyncIterator

from contracts.runtime_events import RuntimeEvent


class RuntimeEventBroker:
    def __init__(self, max_queue_size: int = 256) -> None:
        self._queues: dict[str, set[asyncio.Queue[RuntimeEvent]]] = defaultdict(set)
        self._max_queue_size = max_queue_size
        self._sequences: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    async def publish(self, run_id: str, event: RuntimeEvent) -> None:
        self._publish(run_id, event)

    def publish_from_thread(self, run_id: str, event: RuntimeEvent) -> None:
        """Publish from the synchronous planner worker without creating an event loop.

        Planning is intentionally kept synchronous at the semantic layer and is
        executed in a worker thread.  Calling ``asyncio.run`` for every planner
        heartbeat creates a different loop from the SSE subscriber and can lose
        events.  Queue callbacks are scheduled back onto their owning loop.
        """
        self._publish(run_id, event)

    def _publish(self, run_id: str, event: RuntimeEvent) -> None:
        with self._lock:
            self._sequences[run_id] += 1
            event = event.model_copy(update={"sequence": self._sequences[run_id]})
            queues = tuple(self._queues.get(run_id, ()))
        # The final structured body is an internal hand-off, never a live event payload.
        if event.event_type in {"model.completed", "planner.model.completed"} and "data" in event.payload:
            event = event.model_copy(update={"payload": {k: v for k, v in event.payload.items() if k != "data"}})

        for queue in queues:
            loop = getattr(queue, "_loop", None)
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if loop is not None and loop.is_running() and loop is not current_loop:
                loop.call_soon_threadsafe(self._put_nowait, queue, event)
            else:
                self._put_nowait(queue, event)

    @staticmethod
    def _put_nowait(queue: asyncio.Queue[RuntimeEvent], event: RuntimeEvent) -> None:
        if queue.full():
            # Transient deltas may be coalesced; lifecycle events are retained.
            if not event.event_type.endswith(("completed", "failed")):
                return
            try:
                _ = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
        queue.put_nowait(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[RuntimeEvent]:
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(self._max_queue_size)
        with self._lock:
            self._queues[run_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                queues = self._queues.get(run_id)
                if queues is not None:
                    queues.discard(queue)
                    if not queues:
                        self._queues.pop(run_id, None)
                        self._sequences.pop(run_id, None)


runtime_event_broker = RuntimeEventBroker()
