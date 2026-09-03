import asyncio


from contracts.runtime_events import RuntimeEvent
from runtime.live_events import RuntimeEventBroker


def ev(seq: int, kind: str = "model.output.delta") -> RuntimeEvent:
    return RuntimeEvent(eventType=kind, runId="run-1", nodeId="node-a", attemptId="attempt-1", sequence=seq, payload={"delta": str(seq)})


def test_broker_fans_out_events_and_cleans_subscriber():
  async def run():
    broker = RuntimeEventBroker(max_queue_size=4)
    first = asyncio.Queue(4); second = asyncio.Queue(4)
    broker._queues["run-1"].update({first, second})
    await broker.publish("run-1", ev(1))
    assert first.get_nowait().payload["delta"] == "1"
    assert second.get_nowait().payload["delta"] == "1"
    broker._queues.pop("run-1", None)
  asyncio.run(run())


def test_slow_consumer_drops_delta_but_preserves_completion():
  async def run():
    broker = RuntimeEventBroker(max_queue_size=2)
    queue = asyncio.Queue(2)
    broker._queues["run-1"].add(queue)
    for index in range(10):
        await broker.publish("run-1", ev(index))
    await broker.publish("run-1", ev(11, "model.completed"))
    received = [queue.get_nowait(), queue.get_nowait()]
    assert any(item.event_type == "model.completed" for item in received)
    broker._queues["run-1"].discard(queue)
  asyncio.run(run())


def test_broker_redacts_structured_data_from_planner_completion():
  async def run():
    broker = RuntimeEventBroker()
    queue = asyncio.Queue(2)
    broker._queues["run-1"].add(queue)
    await broker.publish("run-1", RuntimeEvent(
        eventType="planner.model.completed",
        runId="run-1",
        sequence=0,
        payload={"data": {"secret": "must-not-leak"}, "receivedLength": 12},
    ))
    event = queue.get_nowait()
    assert "data" not in event.payload
    assert event.payload["receivedLength"] == 12
    broker._queues["run-1"].discard(queue)
  asyncio.run(run())


def test_disconnect_does_not_cancel_publisher():
  async def run():
    broker = RuntimeEventBroker(max_queue_size=2)
    await broker.publish("run-1", ev(1))
    assert not broker._queues
  asyncio.run(run())


def test_worker_thread_publish_reaches_async_sse_subscriber():
  async def run():
    broker = RuntimeEventBroker()
    stream = broker.subscribe("run-thread")
    pending = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    await asyncio.to_thread(
        broker.publish_from_thread,
        "run-thread",
        RuntimeEvent(
            eventType="planner.model.activity",
            runId="run-thread",
            nodeId=None,
            attemptId=None,
            sequence=0,
            payload={"stage": "outline", "callKey": "outline", "elapsedMs": 42},
        ),
    )
    event = await asyncio.wait_for(pending, timeout=1)
    assert event.event_type == "planner.model.activity"
    assert event.node_id is None and event.attempt_id is None
    await stream.aclose()

  asyncio.run(run())
