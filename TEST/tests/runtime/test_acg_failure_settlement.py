"""Execution authority failure is visible before owned tool cleanup finishes."""

import asyncio

import pytest

from components.executor.graph import ACGSuperstepError
from components.resource.scheduler.leases import LeaseRenewalFailedError
from TEST.tests.runtime.test_model_binding_capacity import _prepare, _runtime


def test_lost_lease_stops_parallel_execution_before_failed_attempt_cleanup(monkeypatch):
    async def scenario():
        from runtime.events.live_events import runtime_event_broker

        runtime, _, _ = _runtime(concurrency=2)
        started = {key: asyncio.Event() for key in ("first", "second")}
        cleanup_started, release_cleanup, sibling_cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        published = []
        publish = runtime_event_broker.publish

        async def observe(run_id, event):
            published.append(event)
            await publish(run_id, event)

        monkeypatch.setattr(runtime_event_broker, "publish", observe)

        async def execute(context):
            key = context.step.step_id
            started[key].set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                if key == "first":
                    cleanup_started.set()
                    await release_cleanup.wait()
                else:
                    sibling_cancelled.set()
                raise

        class KeepAlive:
            def __init__(self, coordinator, lease, **kwargs):
                self.lease = lease

            def start(self):
                pass

            async def wait_failed(self):
                if self.lease.step_id == "first":
                    await started["first"].wait()
                    await started["second"].wait()
                    return LeaseRenewalFailedError("lease owner disappeared")
                await asyncio.Future()

            async def stop(self):
                pass

        monkeypatch.setattr("components.resource.scheduler.binder.LeaseKeepAlive", KeepAlive)
        for key in started:
            runtime.agent_registry.resolve_by_id(key).run = execute
        run = _prepare(runtime)
        task = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
        try:
            await asyncio.wait_for(cleanup_started.wait(), 1)
            await asyncio.wait_for(sibling_cancelled.wait(), 1)
            saved = runtime.workflow_store.get_run(run.run_id)
            assert saved.get_step("first").status.value == "failed"
            assert saved.lifecycle_phase.value == "recovery" and "清理" in saved.lifecycle_message
            assert saved.execution_state["superstepSettlement"]["state"] == "stopping"
            first_attempt = saved.execution_state["executionBindings"]["first"]["attemptId"]
            assert saved.execution_state.get("taskSettlement", {}).get(first_attempt, {}).get("taskState") != "ended"
            assert "first" in saved.active_step_ids and not task.done()
        finally:
            release_cleanup.set()
            with pytest.raises(ACGSuperstepError) as caught:
                await task
        assert isinstance(caught.value.cause, LeaseRenewalFailedError)
        saved = runtime.workflow_store.get_run(run.run_id)
        assert saved.status.value == "failed" and saved.active_step_ids == []
        assert saved.get_step("first").status.value == "failed"
        assert saved.get_step("second").status.value == "cancelled"
        assert saved.execution_state["superstepSettlement"]["state"] == "ended"
        assert {entry["taskState"] for entry in saved.execution_state["taskSettlement"].values()} == {"ended"}
        assert all(entry["leaseState"] == "released" for entry in saved.execution_state["taskSettlement"].values())
        assert any(item.event_type == "node.cancelled" and item.run_id == run.run_id and item.node_id == "second"
                   and item.attempt_id == saved.execution_state["executionBindings"]["second"]["attemptId"]
                   for item in published)
    asyncio.run(scenario())


def test_sibling_failure_preserves_result_committed_before_wrapper_cleanup(monkeypatch):
    from adapters.agent import AgentOutput

    async def scenario():
        runtime, _, _ = _runtime(concurrency=2)
        cleaning, release = asyncio.Event(), asyncio.Event()

        async def execute(context):
            if context.step.step_id == "first":
                await asyncio.Future()
            return AgentOutput(output={"answer": "committed"})

        class KeepAlive:
            def __init__(self, coordinator, lease, **kwargs):
                self.lease = lease

            def start(self):
                pass

            async def wait_failed(self):
                if self.lease.step_id == "first":
                    await cleaning.wait()
                    return LeaseRenewalFailedError("lease owner disappeared")
                await asyncio.Future()

            async def stop(self):
                if self.lease.step_id == "second":
                    cleaning.set()
                    await release.wait()

        monkeypatch.setattr("components.resource.scheduler.binder.LeaseKeepAlive", KeepAlive)
        for key in ("first", "second"):
            runtime.agent_registry.resolve_by_id(key).run = execute
        run = _prepare(runtime)
        service = runtime.acg_execution_service
        project = service._project_event
        stopping = asyncio.Event()
        def observe(current, state, event):
            project(current, state, event)
            if event["type"] == "superstep_stopping":
                stopping.set()
        monkeypatch.setattr(service, "_project_event", observe)
        task = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
        try:
            await asyncio.wait_for(stopping.wait(), 1)
            assert not task.done()
        finally:
            release.set()
            with pytest.raises(ACGSuperstepError) as caught:
                await task
        saved = runtime.workflow_store.get_run(run.run_id)
        assert caught.value.cancelled_step_ids == ()
        assert saved.completed_step_ids == ["second"] and saved.get_step("second").status.value == "completed"
        assert saved.execution_state["outputRefs"]["second"]
        assert saved.active_step_ids == [] and saved.get_step("first").status.value == "failed"
    asyncio.run(scenario())
