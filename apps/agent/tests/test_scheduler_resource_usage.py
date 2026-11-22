from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from components.environment.content import SQLiteContentManifestStore
from components.mission.store import WorkflowRegistry
from components.recovery.checkpoint import ACGCheckpointStore
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowStep, WorkflowStatus
from runtime import ExecutionRuntime
from adapters.agent import AgentRegistry
from support.stores.memory_workflow_store import MemoryWorkflowStore


@pytest.fixture
def resource_usage_runtime(tmp_path):
    store = MemoryWorkflowStore()
    mission = RuntimeMissionRecord(title="Scheduler usage")
    store.save_mission(mission)
    run = RuntimeRunRecord(missionId=mission.mission_id, workflowId="usage-test",
        domain="general", runtimeEngine="acg", status="running")
    store.save_run(run)
    content = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    runtime = ExecutionRuntime(agent_registry=AgentRegistry(), workflow_registry=WorkflowRegistry(),
        workflow_store=store, checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoint.sqlite3"),
        content_manifest_store=content)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    try:
        yield runtime, run, app
    finally:
        content.close()


def _step(step_id, status="pending", **kwargs):
    return WorkflowStep(stepId=step_id, name=step_id, agentName="reader", status=status, **kwargs)


def _bind(runtime, run, step_id, *, run_id=None, expired=False):
    attempt_id = f"attempt:{step_id}"
    lease_id = f"lease:{step_id}"
    now = datetime.now(timezone.utc)
    runtime.resource_binder.coordinator.acquire(lease_id=lease_id, resource_id="runtime:host",
        capacity=10, run_id=run_id or run.run_id, step_id=step_id, attempt_id=attempt_id,
        now=now - timedelta(minutes=2) if expired else now, ttl=timedelta(minutes=1))
    run.execution_state.setdefault("executionBindings", {})[step_id] = {
        "runId": run.run_id, "stepId": step_id, "attemptId": attempt_id,
        "resourceId": "runtime:host", "leaseId": lease_id,
    }
    return lease_id, attempt_id


@pytest.mark.asyncio
async def test_scheduler_usage_counts_owned_host_leases_and_current_admitted_queue(resource_usage_runtime):
    runtime, run, app = resource_usage_runtime
    run.steps = [_step("executing", "running"), _step("queued"), _step("blocked"),
        _step("stale", "retrying", attempt=1), _step("expired", "running"),
        _step("released", "completed"), _step("foreign", "running"),
        _step("retry", "retrying", retryCount=2), _step("old-loop")]
    run.active_step_ids = ["executing", "queued", "stale", "expired", "foreign", "retry", "old-loop"]
    _, attempt_id = _bind(runtime, run, "executing")
    agent_lease = runtime.resource_binder.coordinator.acquire(lease_id="lease:executing:agent",
        resource_id="agent:reader", capacity=1, run_id=run.run_id, step_id="executing",
        attempt_id=attempt_id, ttl=timedelta(minutes=1))
    run.execution_state["executionBindings"]["executing"]["agentLeaseId"] = agent_lease.lease_id
    _bind(runtime, run, "expired", expired=True)
    lease_id, _ = _bind(runtime, run, "released")
    runtime.resource_binder.coordinator.release(lease_id)
    _bind(runtime, run, "foreign", run_id="another-run")
    run.execution_state.update({
        "schedulingStates": {
            key: {"status": "queued", "attemptId": identity}
            for key, identity in [("queued", "queue-current"), ("stale", "queue-old"),
                                  ("retry", "retry-current"), ("old-loop", "loop-old"),
                                  ("released", "completed-old")]
        },
        "attemptIds": {"queued:1:root": "queue-current", "stale:1:root": "queue-old",
            "stale:2:root": "retry-new", "retry:3:2": "retry-current",
            "old-loop:1:1": "loop-old", "old-loop:1:2": "loop-current",
            "released:1:root": "completed-old"},
        "loopPaths": {"retry": [2], "old-loop": [2]},
    })
    runtime.workflow_store.save_run(run)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage")
    assert result.status_code == 200, result.text
    assert result.json()["scheduler"] == {
        "activeSlots": 1, "queueDepth": 2, "checkpointCount": 0, "recoveryCount": 0,
    }


@pytest.mark.asyncio
async def test_terminal_run_still_reports_retained_unknown_capacity(resource_usage_runtime):
    runtime, run, app = resource_usage_runtime
    run.status = WorkflowStatus.FAILED
    run.steps = [_step("unknown", "failed"), _step("queued")]
    _, attempt_id = _bind(runtime, run, "unknown")
    run.execution_state.update({
        "taskSettlement": {attempt_id: {"outcome": "unknown", "leaseState": "retained_unknown"}},
        "schedulingStates": {"queued": {"status": "queued", "attemptId": "queued-current"}},
        "attemptIds": {"queued:1:root": "queued-current"},
    })
    runtime.workflow_store.save_run(run)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage")
    assert result.status_code == 200, result.text
    assert result.json()["scheduler"]["activeSlots"] == 1
    assert result.json()["scheduler"]["queueDepth"] == 0
