"""Current-Run recovery must retain the existing Permit and admitted Dispatch."""
import asyncio
import inspect
import os
from pathlib import Path
import sqlite3
import sys

from fastapi import FastAPI
import httpx
import pytest

from adapters.agent.invocation import AgentInvocationAdapter
from contracts import stable_checksum
from contracts.runtime_planning import RuntimePlanningDecision
from contracts.workflow import ReviewDecision
from adapters.agent.registry import AgentNotFound
from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from app.security.internal_auth import (InternalServiceAuthMiddleware, TrustedUserContext,
    _trusted_user_context, current_semantic_principal)
from runtime.orchestration.planning_operations import RuntimeTaskOperations
from support.stores.execution_dispatch_store import DispatchCommand, SQLiteExecutionDispatchStore

# Share the existing durable v2 prefix fixture; it uses only actual Runtime
# authorities and never relies on the removed example application package.
from TEST.tests.components.planner.test_permit_recovery import ready_handoff
from TEST.tests.components.planner.test_horizon import ready_boundary, runtime_boundary
from TEST.tests.components.planner.test_initial_planning_sources import initial_run as initial_runtime
from TEST.tests.components.planner.test_initial_execution_permit import prepared_initial

PREFIX = "/agentos/v2"
TOKEN = "formal-recovery-http-token-32-characters"


@pytest.fixture(scope="module")
def recovery_seed(tmp_path_factory):
    from TEST.tests.components.planner import test_permit_recovery, test_react_loop
    original = test_react_loop.runtime_at

    def owned_runtime(path):
        runtime, store, agent = original(path)
        create = runtime.create_mission

        def owned_mission(*args, **kwargs):
            kwargs["input"] = {**(kwargs.get("input") or {}),
                "authenticatedUserId": "owner", "authenticatedTenantId": "tenant"}
            return create(*args, **kwargs)

        runtime.create_mission = owned_mission
        return runtime, store, agent

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(test_react_loop, "runtime_at", owned_runtime)
        patch.setenv("PYTHONPATH", os.pathsep.join([str(Path(test_react_loop.__file__).parent),
            str(Path(__file__).resolve().parents[2] / "agentOS" / "src"),
            str(Path(__file__).resolve().parents[2] / "agentOS"), os.environ.get("PYTHONPATH", "")]))
        yield from test_permit_recovery.recovery_seed.__wrapped__(tmp_path_factory)


class HttpHarness:
    """Keep HTTP requests and managed execution on one persistent owning loop."""
    def __init__(self, runtime):
        self.runner = asyncio.Runner()
        self.coordinator = RunExecutionCoordinator(runtime)
        app = FastAPI()
        app.include_router(create_router(runtime, self.coordinator))
        app.add_middleware(InternalServiceAuthMiddleware, token=TOKEN)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://recovery.test",
            headers={"X-Internal-Service-Token": TOKEN, "X-Authenticated-User-Id": "owner",
                "X-Authenticated-User-Subject": "test-owner", "X-Authenticated-User-Role": "user",
                "X-Authenticated-Tenant-Id": "tenant"})

    def get(self, url):
        return self.runner.run(self.client.get(url))

    def post(self, url, **kwargs):
        return self.runner.run(self.client.post(url, **kwargs))

    def close(self):
        self.runner.run(self.coordinator.shutdown())
        self.runner.run(self.client.aclose())
        self.runner.close()


def trusted_call(client, function, *args):
    async def invoke():
        token = _trusted_user_context.set(TrustedUserContext("owner", "test-owner", "user", "tenant"))
        try:
            result = function(*args)
            return await result if inspect.isawaitable(result) else result
        finally:
            _trusted_user_context.reset(token)
    return client.runner.run(invoke())


def wait_run(client, created):
    async def settle():
        task = client.coordinator._tasks.get(created["runId"])
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=20)
    client.runner.run(settle())
    response = client.get(PREFIX + "/runs/" + created["runId"])
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def failed_formal_run(ready_handoff, monkeypatch):  # noqa: F811 - imported pytest fixture
    original = AgentInvocationAdapter.invoke
    failed_once = []

    async def missing_registration(self, *, context, agent=None):
        if context.step.step_id != "B" or failed_once:
            return await original(self, context=context, agent=agent)
        failed_once.append(True)
        registry = self.registry

        class Missing:
            def resolve_by_id(self, agent_id):
                raise AgentNotFound(agent_id)

        self.registry = Missing()
        try:
            return await original(self, context=context, agent=agent)
        finally:
            self.registry = registry

    class Planner:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="wait" if observation.failed_step_ids else "continue" if observation.remaining_step_ids else "complete",
                reason="formal recovery boundary")

    monkeypatch.setattr(AgentInvocationAdapter, "invoke", missing_registration)
    runtime, store, agent, run_id, _, _, _, _, handoff_id = ready_handoff
    store.enable_existing_mission_semantics()
    issued = runtime.issue_execution_permit(handoff_id, idempotency_key="operator-recovery-permit")
    assert issued.status == "ISSUED", issued
    SQLiteExecutionDispatchStore.upgrade_schema(store.db_path)
    runtime.execution_dispatch_store = SQLiteExecutionDispatchStore(store.db_path)
    runtime.execution_dispatch_enabled = True
    runtime.runtime_planning_coordinator.planner_for_run = lambda _: Planner()
    runtime.semantic_principal_provider = current_semantic_principal
    client = HttpHarness(runtime)
    run = store.get_run(run_id)
    created = {"runId": run_id, "missionId": run.mission_id}
    command = DispatchCommand(dispatch_id="dispatch:" + run_id, operation_key="operator-recovery-dispatch",
        request_fingerprint="operator-recovery-http-fixture", mission_id=run.mission_id, run_id=run_id,
        permit_id=issued.permit_id, graph_id=run.execution_state["graphId"], graph_version=run.execution_state["graphVersion"],
        runtime_revision=run.runtime_revision, actor_id="owner", tenant_id="tenant")
    try:
        accepted, replay = trusted_call(client, client.coordinator.submit_permitted, command)
        assert accepted == command and not replay
        paused = wait_run(client, created)
        assert paused["status"] == "waiting_review", paused
        assert agent.calls == []  # A was committed by the durable seed.
        rejected = trusted_call(client, runtime.apply_review, ReviewDecision(
            runId=created["runId"], stepId=paused["currentStepId"], decision="rejected", operationId="reject-failed-plan"))
        assert rejected.status.value == "failed"
        yield client, runtime, agent, created, rejected
    finally:
        client.close()


def retry_url(created):
    return f'{PREFIX}/runs/{created["runId"]}/steps/B/retry'


def retry_body(failed):
    return {"mode": "current_run", "clientRequestId": "operator-retry",
            "expectedRuntimeRevision": failed.runtime_revision}


def run_count(runtime, mission_id):
    with sqlite3.connect(runtime.workflow_store.db_path) as conn:
        return conn.execute("SELECT count(*) FROM runs WHERE mission_id=?", (mission_id,)).fetchone()[0]


def test_http_formal_recovery_retains_run_permit_and_successful_prefix(failed_formal_run):
    client, runtime, agent, created, failed = failed_formal_run
    permit = failed.execution_state["executionPermitId"]
    trusted_call(client, RuntimeTaskOperations(runtime).assert_current_run_recovery, failed)
    offers = client.get(PREFIX + "/runs/" + failed.run_id).json()["actionCapabilities"]
    assert offers["canRecoverCurrentRun"] is True and offers["retryMode"] == "current_run", offers
    assert offers["retryStepId"] == "B" and offers["canRetrySuccessor"] is False
    response = client.post(retry_url(created), json=retry_body(failed))
    assert response.status_code == 202, response.text
    assert response.json()["runId"] == failed.run_id
    result = wait_run(client, created)
    assert result["status"] == "completed", result
    assert agent.calls == ["B", "C", "D"]
    saved = runtime.workflow_store.get_run(failed.run_id)
    assert saved.execution_state["executionPermitId"] == permit
    assert saved.execution_state["executionGeneration"] == failed.execution_state["executionGeneration"]
    assert saved.recovery_count == 1
    assert run_count(runtime, failed.mission_id) == 1
    replay = client.post(retry_url(created), json=retry_body(failed))
    assert replay.status_code == 202, replay.text
    assert runtime.workflow_store.get_run(failed.run_id).recovery_count == 1
    assert agent.calls == ["B", "C", "D"]
    conflict = client.post(retry_url(created), json={**retry_body(failed), "reason": "different request"})
    assert conflict.status_code == 409


@pytest.mark.parametrize("damage", ["stale_revision", "missing_revision", "missing_dispatch", "dispatch_actor",
    "detached_planning_authority", "detached_dispatch_store", "revoked_write", "foreign_actor", "unsettled",
    "cancelled_run", "running_run"])
def test_http_recovery_requires_live_authority_and_settled_proof(failed_formal_run, monkeypatch, damage):
    client, runtime, agent, created, failed = failed_formal_run
    body = retry_body(failed)
    headers = {}
    if damage == "stale_revision":
        body["expectedRuntimeRevision"] += 1
    elif damage == "missing_revision":
        body.pop("expectedRuntimeRevision")
    elif damage == "missing_dispatch":
        with sqlite3.connect(runtime.workflow_store.db_path) as conn:
            conn.execute("DELETE FROM execution_dispatch_commands WHERE run_id=?", (failed.run_id,))
    elif damage == "dispatch_actor":
        command = runtime.execution_dispatch_store.get(failed.run_id).model_copy(update={"actor_id": "foreign"})
        with sqlite3.connect(runtime.workflow_store.db_path) as conn:
            conn.execute("UPDATE execution_dispatch_commands SET payload=?,checksum=? WHERE run_id=?",
                (command.model_dump_json(), stable_checksum(command), failed.run_id))
    elif damage == "detached_planning_authority":
        monkeypatch.setattr(runtime, "planning_commit_authority", None)
    elif damage == "detached_dispatch_store":
        monkeypatch.setattr(runtime, "execution_dispatch_store", None)
    elif damage == "revoked_write":
        monkeypatch.setattr(runtime.mission_semantic_service, "authorize", lambda principal, mission, action: action == "read")
    elif damage == "foreign_actor":
        headers["X-Authenticated-User-Id"] = "foreign"
    elif damage in {"cancelled_run", "running_run"}:
        from contracts.workflow import WorkflowStatus
        changed = failed.model_copy(update={"status": WorkflowStatus(damage.removesuffix("_run"))})
        # Terminal overwrite protection intentionally ignores an ordinary save.
        # Simulate a different persisted lifecycle cut only in this test ledger.
        with runtime.workflow_store._connect() as conn:
            conn.execute("UPDATE runs SET payload=?,status=? WHERE run_id=?",
                (changed.model_dump_json(by_alias=True), changed.status.value, changed.run_id))
        body["expectedRuntimeRevision"] = changed.runtime_revision
    else:
        # A prepared operation without the Adapter's trusted failed phase is
        # not evidence that an external operation was never invoked.
        with sqlite3.connect(runtime.execution_value_store.db_path) as conn:
            conn.execute("UPDATE acg_node_executions SET payload_json=json_set(payload_json,'$.phase','executed') "
                         "WHERE run_id=? AND json_extract(payload_json,'$.stepId')='B'", (failed.run_id,))
    before = runtime.workflow_store.get_run(failed.run_id)
    offer = client.get(PREFIX + "/runs/" + failed.run_id)
    if damage not in {"stale_revision", "missing_revision", "foreign_actor"} and offer.status_code == 200:
        capabilities = offer.json()["actionCapabilities"]
        assert capabilities["canRecoverCurrentRun"] is False and capabilities["retryMode"] is None
    response = client.post(retry_url(created), json=body, headers=headers)
    assert response.status_code in {403, 404, 409}, response.text
    assert runtime.workflow_store.get_run(failed.run_id) == before
    assert agent.calls == []


def test_copilot_formal_recovery_and_lost_receipt_do_not_create_second_attempt(failed_formal_run, monkeypatch):
    client, runtime, agent, created, failed = failed_formal_run
    base = f'{PREFIX}/runs/{failed.run_id}/copilot/actions'
    preview = client.post(base + "/preview", json={"operationId": "recover-proposal", "kind": "recover",
        "content": "从失败节点继续", "permission": "task_collaboration"})
    assert preview.status_code == 200, preview.text
    proposal = preview.json()
    assert proposal["action"]["retryMode"] == "current_run"
    assert proposal["action"]["reusedStepIds"] == ["A"]
    body = {"proposalId": proposal["operationId"], "expectedRevision": failed.runtime_revision,
            "permission": "task_collaboration"}
    original = runtime.workflow_store.save_copilot_exchange

    def interrupted(run_id, operation_id, value):
        if operation_id.startswith("receipt:"):
            raise RuntimeError("lost acknowledgement after durable retry")
        return original(run_id, operation_id, value)

    monkeypatch.setattr(runtime.workflow_store, "save_copilot_exchange", interrupted)
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        client.post(base, json=body)
    queued = runtime.workflow_store.get_run(failed.run_id)
    assert queued.status.value == "retrying" and queued.recovery_count == 1
    monkeypatch.setattr(runtime.workflow_store, "save_copilot_exchange", original)
    response = client.post(base, json=body)
    assert response.status_code == 202, response.text
    receipt = response.json()
    assert receipt["receipt"]["runId"] == failed.run_id
    assert "当前运行" in receipt["assistant"]
    assert wait_run(client, created)["status"] == "completed"
    assert client.post(base, json=body).json() == receipt
    assert runtime.workflow_store.get_run(failed.run_id).recovery_count == 1
    assert agent.calls == ["B", "C", "D"]


def test_permit_cannot_be_recovered_as_successor(failed_formal_run):
    client, runtime, agent, created, failed = failed_formal_run
    response = client.post(retry_url(created), json={**retry_body(failed), "mode": "successor_run"})
    assert response.status_code == 409, response.text
    assert runtime.workflow_store.get_run(failed.run_id) == failed
    assert run_count(runtime, failed.mission_id) == 1
    assert agent.calls == []


def test_legacy_run_cannot_use_public_current_run_recovery(tmp_path):
    from TEST.tests.components.planner.test_react_loop import runtime_at
    runtime, store, agent = runtime_at(tmp_path)
    mission = runtime.create_mission("legacy retry", workflow_id="seq")
    _, run = runtime.prepare_run(mission.mission_id)
    client = HttpHarness(runtime)
    try:
        response = client.post(f"{PREFIX}/runs/{run.run_id}/steps/A/retry", json=retry_body(run))
        assert response.status_code == 409, response.text
        assert store.get_run(run.run_id) == run and agent.calls == []
    finally:
        client.close()


def test_http_initial_v1_failure_recovers_without_relaxing_terminal_execution(initial_runtime, monkeypatch):  # noqa: F811
    runtime = initial_runtime[0]
    create = runtime.create_mission

    def owned_mission(*args, **kwargs):
        kwargs["input"] = {**(kwargs.get("input") or {}),
            "authenticatedUserId": "owner", "authenticatedTenantId": "tenant"}
        return create(*args, **kwargs)

    monkeypatch.setattr(runtime, "create_mission", owned_mission)
    runtime.resource_plane.set_runtime_enabled("runtime:horizon-test", enabled=False)
    runtime, store, agent, run, commit, handoff_id = prepared_initial(initial_runtime, fresh=True)
    issued = runtime.issue_execution_permit(handoff_id, idempotency_key="initial-http-recovery")
    assert issued.status == "ISSUED", issued
    permit = runtime.execution_permit_authority.store.get_permit(issued.permit_id)
    assert permit.source_kind == "initial_plan" and permit.graph_version == 1
    original = AgentInvocationAdapter.invoke
    attempts = []

    async def missing_registration(self, *, context, agent=None):
        if attempts:
            return await original(self, context=context, agent=agent)
        attempts.append(context.step.step_id)
        registry = self.registry

        class Missing:
            def resolve_by_id(self, agent_id):
                raise AgentNotFound(agent_id)

        self.registry = Missing()
        try:
            return await original(self, context=context, agent=agent)
        finally:
            self.registry = registry

    class Planner:
        def decide_runtime(self, *, observation, task_plan):
            return RuntimePlanningDecision(observationId=observation.fingerprint(),
                action="wait" if observation.failed_step_ids else "continue" if observation.remaining_step_ids else "complete",
                reason="initial recovery boundary")

    monkeypatch.setattr(AgentInvocationAdapter, "invoke", missing_registration)
    runtime.runtime_planning_coordinator.planner_for_run = lambda _: Planner()
    SQLiteExecutionDispatchStore.upgrade_schema(store.db_path)
    runtime.execution_dispatch_store = SQLiteExecutionDispatchStore(store.db_path)
    runtime.execution_dispatch_enabled = True
    runtime.semantic_principal_provider = current_semantic_principal
    client = HttpHarness(runtime)
    run = store.get_run(run.run_id)
    created = {"runId": run.run_id, "missionId": run.mission_id}
    command = DispatchCommand(dispatch_id="dispatch:" + run.run_id, operation_key="initial-recovery-dispatch",
        request_fingerprint="initial-recovery-fixture", mission_id=run.mission_id, run_id=run.run_id,
        permit_id=issued.permit_id, graph_id=permit.graph_id, graph_version=1,
        runtime_revision=run.runtime_revision, actor_id="owner", tenant_id="tenant")
    try:
        trusted_call(client, client.coordinator.submit_permitted, command)
        paused = wait_run(client, created)
        assert paused["status"] == "waiting_review" and agent.calls == [], paused
        failed = trusted_call(client, runtime.apply_review, ReviewDecision(runId=run.run_id,
            stepId=paused["currentStepId"], decision="rejected", operationId="reject-initial-failure"))
        assert failed.status.value == "failed"
        with pytest.raises(ValueError):
            trusted_call(client, runtime.execution_permit_authority.assert_dispatchable, failed)
        provider = runtime.planning_commit_authority._provider(run.run_id, commit.proposal_payload, True)
        assert trusted_call(client, provider.authorize) is False
        offers = client.get(PREFIX + "/runs/" + run.run_id).json()["actionCapabilities"]
        assert offers["canRecoverCurrentRun"] is True and offers["retryMode"] == "current_run", offers
        response = client.post(f"{PREFIX}/runs/{run.run_id}/steps/A/retry", json=retry_body(failed))
        assert response.status_code == 202, response.text
        final = wait_run(client, created)
        assert final["status"] == "completed" and agent.calls == ["A"], final
        saved = store.get_run(run.run_id)
        assert saved.execution_state["executionPermitId"] == permit.permit_id
        assert saved.execution_state["executionGeneration"] == permit.attempt_generation
        assert saved.execution_state["graphVersion"] == 1 and saved.recovery_count == 1
        assert run_count(runtime, run.mission_id) == 1
        with pytest.raises(ValueError):
            trusted_call(client, runtime.execution_permit_authority.assert_dispatchable, saved)
        with pytest.raises(ValueError):
            trusted_call(client, RuntimeTaskOperations(runtime).assert_current_run_recovery, saved)
    finally:
        client.close()
