"""Run-scoped in-process fan-out for transient RuntimeEvents."""
from __future__ import annotations

import asyncio
import logging
from threading import RLock, Timer
from collections import defaultdict
from copy import deepcopy
from typing import AsyncIterator

from contracts.runtime_events import RuntimeEvent, TRANSIENT_RUNTIME_EVENT_TYPES
from runtime.projections.runtime_display import RuntimeDisplayProjection
from support.async_tasks import run_blocking


COALESCIBLE_EVENT_TYPES = TRANSIENT_RUNTIME_EVENT_TYPES

class RuntimeEventOverflow(RuntimeError):
    """A subscriber was too slow to retain the critical RuntimeEvent contract."""


class _SubscriberOverflow:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


class RuntimeEventBroker:
    def __init__(self, max_queue_size: int = 256, *, store=None) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        self._queues: dict[str, set[asyncio.Queue[RuntimeEvent | _SubscriberOverflow]]] = defaultdict(set)
        self._max_queue_size = max_queue_size
        self._sequences: dict[str, int] = defaultdict(int)
        self._lock = RLock()
        self._store = store
        self._stores: dict[str, object] = {}
        self._displays: dict[str, RuntimeDisplayProjection] = {}
        self._flushes: dict[str, Timer] = {}
        self._dirty: set[str] = set()
        self._queue_loops = {}

    def bind_run(self, run_id: str, store) -> None:
        """Runtime and read endpoint share the same existing Run persistence port."""
        if not callable(getattr(store, "get_runtime_display", None)):
            return
        with self._lock:
            owner = self._stores.get(run_id, self._store)
            if owner is not None and owner is not store and getattr(owner, "db_path", None) != getattr(store, "db_path", None):
                raise ValueError("runtime event Run store identity mismatch")
            self._stores[run_id] = store
            self._reconcile_display(run_id)
            # Closed Run projections are reloadable; don't retain every Run for
            # the service lifetime. Never evict an observed or dirty projection.
            for old in list(self._stores):
                if len(self._stores) <= 128:
                    break
                display = self._displays.get(old)
                if old != run_id and not self._queues.get(old) and old not in self._dirty and old not in self._flushes and (display is None or display.terminal):
                    self._stores.pop(old, None)
                    self._displays.pop(old, None)
                    self._sequences.pop(old, None)

    def _display(self, run_id: str) -> RuntimeDisplayProjection | None:
        store = self._stores.get(run_id, self._store)
        if store is None:
            return None
        if run_id not in self._displays:
            self._displays[run_id] = RuntimeDisplayProjection(store.get_runtime_display(run_id))
            self._sequences[run_id] = self._displays[run_id].sequence
        return self._displays[run_id]

    def _reconcile_display(self, run_id: str) -> None:
        display = self._display(run_id)
        store = self._stores.get(run_id, self._store)
        if display is None or not display.terminal or not callable(getattr(store, "get_run", None)):
            return
        try:
            run = store.get_run(run_id)
        except KeyError:
            return
        if run.status not in {"pending", "planning", "running", "retrying", "waiting_review"}:
            return
        state = run.execution_state
        bindings = state.get("executionBindings", {})
        current = {step.step_id: bindings[step.step_id]["attemptId"] for step in run.steps
            if step.status in {"running", "completed"} and isinstance(bindings.get(step.step_id), dict)
            and isinstance(bindings[step.step_id].get("attemptId"), str)}
        known: dict[str, set[str]] = defaultdict(set)
        for key, identity in state.get("attemptIds", {}).items():
            if isinstance(key, str) and isinstance(identity, str) and len(parts := key.rsplit(":", 2)) == 3:
                known[parts[0]].add(identity)
        for item in display.events:
            if item.get("nodeId") and item.get("attemptId"):
                known[item["nodeId"]].add(item["attemptId"])
        display.reopen(current, known)
        self._sequences[run_id] = max(self._sequences[run_id], display.sequence)
        self._dirty.add(run_id)
        if run_id not in self._flushes:
            timer = Timer(0.25, self._flush, args=(run_id,))
            timer.daemon = True
            self._flushes[run_id] = timer
            timer.start()

    def _flush(self, run_id: str) -> None:
        with self._lock:
            self._drain_pending(run_id)
            timer = self._flushes.pop(run_id, None)
            if timer is not None:
                timer.cancel()
            display = self._displays.get(run_id)
            snapshot = deepcopy(display.durable()) if display is not None else None
            store = self._stores.get(run_id, self._store)
        if snapshot is not None:
            try:
                # SQLite I/O must never hold the global fan-out lock. Store CAS
                # orders concurrent flushes without stalling other Runs.
                store.save_runtime_display(run_id, snapshot)
                with self._lock:
                    if display.sequence == snapshot["sequence"]:
                        self._dirty.discard(run_id)
            except Exception:
                # Display persistence cannot invalidate an executed command.
                # Do not log model text or database exception messages.
                logging.getLogger(__name__).warning("runtime_display_checkpoint_failed run_id=%s", run_id)

    def _drain_pending(self, run_id: str) -> None:
        display = self._displays.get(run_id)
        if display is not None:
            for event in display.drain_pending():
                self._publish(run_id, event)

    def flush(self) -> None:
        """Drain pending public checkpoints on an orderly service shutdown."""
        with self._lock:
            dirty = tuple(self._dirty)
        for run_id in dirty:
            self._flush(run_id)

    def snapshot(self, run_id: str) -> RuntimeEvent | None:
        with self._lock:
            self._reconcile_display(run_id)
            display = self._display(run_id)
            self._drain_pending(run_id)
            return RuntimeEvent(eventType="runtime.display.snapshot", runId=run_id,
                sequence=display.sequence, payload=display.snapshot()) if display is not None else None

    async def publish(self, run_id: str, event: RuntimeEvent) -> None:
        with self._lock:
            flush_now = self._publish(run_id, event)
        if flush_now:
            await run_blocking(self._flush, run_id)

    def publish_from_thread(self, run_id: str, event: RuntimeEvent) -> None:
        """Publish from the synchronous planner worker without creating an event loop.

        Planning is intentionally kept synchronous at the semantic layer and is
        executed in a worker thread.  Calling ``asyncio.run`` for every planner
        heartbeat creates a different loop from the SSE subscriber and can lose
        events.  Queue callbacks are scheduled back onto their owning loop.
        """
        # Keep sequence assignment and queue scheduling in publication order,
        # including concurrent planner worker and execution-loop publishers.
        with self._lock:
            flush_now = self._publish(run_id, event)
        if flush_now:
            self._flush(run_id)

    def _publish(self, run_id: str, event: RuntimeEvent) -> bool:
        if event.run_id != run_id:
            raise ValueError("runtime event Run identity mismatch")
        with self._lock:
            flush_now = False
            display = self._display(run_id)
            if display is not None and event.attempt_id in display.retired.get(event.node_id, set()):
                return False
            if event.event_type in {"run.completed", "run.failed", "run.cancelled", "run.superseded"}:
                store = self._stores.get(run_id, self._store)
                if callable(getattr(store, "get_run", None)):
                    try:
                        if store.get_run(run_id).status != event.event_type.removeprefix("run."):
                            return False  # An old publisher cannot close a formally resumed Run.
                    except KeyError:
                        return False
            if event.event_type not in {"model.output.delta", "planner.model.output.delta"}:
                self._drain_pending(run_id)
            self._sequences[run_id] += 1
            event = event.model_copy(update={"sequence": self._sequences[run_id]})
            if display is not None:
                public = display.apply(event)
                self._dirty.add(run_id)
                if event.event_type in {"model.output.delta", "planner.model.output.delta"}:
                    if public is not None:
                        event = public
                if event.event_type not in COALESCIBLE_EVENT_TYPES:
                    flush_now = True
                elif run_id not in self._flushes:
                    timer = Timer(0.25, self._flush, args=(run_id,))
                    timer.daemon = True
                    self._flushes[run_id] = timer
                    timer.start()
                if public is None and event.event_type in {"model.output.delta", "planner.model.output.delta"}:
                    return False
            queues = tuple(self._queues.get(run_id, ()))
        # The final structured body is an internal hand-off, never a live event payload.
        if event.event_type in {"model.completed", "planner.model.completed"} and "data" in event.payload:
            event = event.model_copy(update={"payload": {k: v for k, v in event.payload.items() if k != "data"}})

        for queue in queues:
            loop = self._queue_loops.get(queue) or getattr(queue, "_loop", None)
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if loop is not None and loop.is_running() and loop is not current_loop:
                try:
                    loop.call_soon_threadsafe(self._put_nowait, run_id, queue, event)
                except RuntimeError:
                    self._queues[run_id].discard(queue)
            else:
                self._put_nowait(run_id, queue, event)
        return flush_now

    def _put_nowait(
        self,
        run_id: str,
        queue: asyncio.Queue[RuntimeEvent | _SubscriberOverflow],
        event: RuntimeEvent,
    ) -> None:
        if queue not in self._queues.get(run_id, ()):
            return
        if queue.full():
            recoverable = run_id in self._displays
            if event.event_type in COALESCIBLE_EVENT_TYPES and not recoverable:
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
            if not removed or recoverable:
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
        # Capture a baseline and register the queue under the publisher's lock.
        # An event is either in the baseline or after it, with no fetch/SSE gap.
        with self._lock:
            self._display(run_id)
            self._drain_pending(run_id)
            self._queues[run_id].add(queue)
            self._queue_loops[queue] = asyncio.get_running_loop()
            baseline = self.snapshot(run_id)
        try:
            if baseline is not None:
                yield baseline
            while True:
                item = await queue.get()
                if isinstance(item, _SubscriberOverflow):
                    raise RuntimeEventOverflow(
                        f"runtime event subscriber overflow for run {item.run_id}"
                    )
                yield item
        finally:
            with self._lock:
                self._queue_loops.pop(queue, None)
                queues = self._queues.get(run_id)
                if queues is not None:
                    queues.discard(queue)
                    if not queues:
                        self._queues.pop(run_id, None)
                        if run_id not in self._displays:
                            self._sequences.pop(run_id, None)


runtime_event_broker = RuntimeEventBroker()


__all__ = [
    "COALESCIBLE_EVENT_TYPES",
    "RuntimeEventBroker",
    "RuntimeEventOverflow",
    "runtime_event_broker",
]
