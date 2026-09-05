"""Run-scoped in-process fan-out for transient RuntimeEvents."""
from __future__ import annotations

import asyncio
from threading import Lock
from collections import defaultdict
from typing import AsyncIterator

from contracts.runtime_events import RuntimeEvent


COALESCIBLE_EVENT_TYPES = frozenset({
    "model.output.delta",
    "model.activity",
    "planner.model.activity",
    "planner.model.output.delta",
    "planner.draft.updated",
})

CRITICAL_EVENT_TYPES = frozenset({
    "node.completed",
    "node.failed",
    "model.completed",
    "planner.completed",
    "planner.failed",
})


class RuntimeEventOverflow(RuntimeError):
    """A subscriber was too slow to retain the critical RuntimeEvent contract."""


class _SubscriberOverflow:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


class RuntimeEventBroker:
    def __init__(self, max_queue_size: int = 256) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        self._queues: dict[str, set[asyncio.Queue[RuntimeEvent | _SubscriberOverflow]]] = defaultdict(set)
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
                loop.call_soon_threadsafe(self._put_nowait, run_id, queue, event)
            else:
                self._put_nowait(run_id, queue, event)

    def _put_nowait(
        self,
        run_id: str,
        queue: asyncio.Queue[RuntimeEvent | _SubscriberOverflow],
        event: RuntimeEvent,
    ) -> None:
        if queue.full():
            if event.event_type in COALESCIBLE_EVENT_TYPES:
                return
            # A critical event may evict only the oldest coalescible item. Never
            # overwrite a lifecycle event with another lifecycle event.
            buffered: list[RuntimeEvent | _SubscriberOverflow] = []
            removed = False
            while True:
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if (
                    not removed
                    and isinstance(item, RuntimeEvent)
                    and item.event_type in COALESCIBLE_EVENT_TYPES
                ):
                    removed = True
                    continue
                buffered.append(item)
            for item in buffered:
                queue.put_nowait(item)
            if not removed:
                # Explicitly terminate this slow subscriber. The sentinel is
                # consumed by subscribe() and becomes a visible SSE failure;
                # no critical lifecycle event is silently lost.
                with self._lock:
                    queues = self._queues.get(run_id)
                    if queues is not None:
                        queues.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(_SubscriberOverflow(run_id))
                return
        queue.put_nowait(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[RuntimeEvent]:
        queue: asyncio.Queue[RuntimeEvent | _SubscriberOverflow] = asyncio.Queue(self._max_queue_size)
        with self._lock:
            self._queues[run_id].add(queue)
        try:
            while True:
                item = await queue.get()
                if isinstance(item, _SubscriberOverflow):
                    raise RuntimeEventOverflow(
                        f"runtime event subscriber overflow for run {item.run_id}"
                    )
                yield item
        finally:
            with self._lock:
                queues = self._queues.get(run_id)
                if queues is not None:
                    queues.discard(queue)
                    if not queues:
                        self._queues.pop(run_id, None)
                        self._sequences.pop(run_id, None)


runtime_event_broker = RuntimeEventBroker()


__all__ = [
    "COALESCIBLE_EVENT_TYPES",
    "CRITICAL_EVENT_TYPES",
    "RuntimeEventBroker",
    "RuntimeEventOverflow",
    "runtime_event_broker",
]
