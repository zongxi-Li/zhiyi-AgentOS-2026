"""Public commands with production wiring, trusted middleware and temporary stores."""
import time
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from app.execution.wiring import build_default_runtime, close_runtime
from app.security.internal_auth import InternalServiceAuthMiddleware
from contracts.mission_semantic import run_intent_basis
from contracts.planning import PlannedTask
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from test_execution_runtime_application_wiring import _environment, _InjectedToolRuntime, _InjectedModelRuntime, _InjectedIntentLLM
from test_planning_loop import Agent, Planner, attach


TOKEN = "s00-isolated-internal-service-token-123456"
HEADERS = {"x-internal-service-token": TOKEN, "x-authenticated-user-id": "owner",
           "x-authenticated-user-subject": "owner", "x-authenticated-user-role": "user",
           "x-authenticated-tenant-id": "tenant"}
BODY = {"title": "display title", "workflowId": "semantic-test", "clientRequestId": "create-one",
        "input": {"source": "acg", "taskGoal": "legacy goal must not win", "planningMode": "template_preferred", "deterministicIntent": True},
        "semantics": {"objective": "formal goal", "constraints": [{"constraintId": "c1", "text": "keep sources"}], "sourceRefs": []}}


def application(env):
    @asynccontextmanager
    async def lifespan(app):
        # Production constructs these SQLite services on its event-loop thread.
        runtime = build_default_runtime(environment=env, tool_runtime=_InjectedToolRuntime(),
            model_runtime=_InjectedModelRuntime(), intent_llm=_InjectedIntentLLM())
        agent = Agent()
        runtime.agent_registry.register(agent)
        runtime.workflow_registry.register(WorkflowDefinition(workflowId="semantic-test", name="semantic test", domain="general",
            runtimeEngine="acg", planningNodes=[PlannedTask(key="step:A", title="A", objective="do A")],
            steps=[WorkflowStepDefinition(stepId="A", name="A", agentName="runner")]))
        coordinator = RunExecutionCoordinator(runtime)
        attach(runtime, Planner())
        app.include_router(create_router(runtime, coordinator))
        app.state.boundary = runtime, coordinator, agent
        try:
            yield
        finally:
            await coordinator.shutdown()
            await asyncio.get_running_loop().shutdown_default_executor()
            close_runtime(runtime)
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(InternalServiceAuthMiddleware, token=TOKEN)
    return app


@pytest.fixture
def api(tmp_path):
    env = {**_environment(tmp_path), "AGENTOS_MISSION_SEMANTIC_CONVERGENCE": "true",
           "AGENTOS_ALLOW_LEGACY_MISSION_INTENT": "false"}
    SQLiteWorkflowStore(env["AGENTOS_WORKFLOW_DB_PATH"], enable_mission_semantics=True)
    app = application(env)
    with TestClient(app, headers=HEADERS) as client:
        yield client, *app.state.boundary


def create(client, body=None):
    response = client.post("/agentos/v2/missions", json=body or BODY)
    assert response.status_code == 202, response.text
    return response.json()


def edit(client, mission, revision=1, operation="edit-one", objective="changed goal"):
    return client.post(f"/agentos/v2/missions/{mission}/semantics", json={"operationId": operation,
        "expectedMissionRevision": revision, "objective": objective, "constraints": [], "sourceRefs": []})


def finished(runtime, run_id):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        run = runtime.workflow_store.get_run(run_id)
        if run.status.value in {"completed", "failed"}:
            assert run.status.value == "completed", run.execution_state
            return run
        time.sleep(.01)
    pytest.fail("isolated execution did not finish: " + run.model_dump_json(by_alias=True))


def test_strict_public_creation_executes_and_edit_separates_runs(api):
    client, runtime, _, agent = api
    first = create(client)
    old = finished(runtime, first["runId"])
    assert agent.calls
    basis = run_intent_basis(old)
    assert (basis.source_type, basis.source_revision, basis.objective) == ("SEMANTIC", 1, "formal goal")
    assert basis.constraints[0].constraint_id == "c1"
    old_plan = runtime.identity_lifecycle.repositories.runs.get(old.run_id)
    old_state = old.model_dump(mode="json", exclude={"trace"})
    response = edit(client, first["missionId"])
    assert response.status_code == 200, response.text
    assert edit(client, first["missionId"]).json() == response.json()
    assert client.get(f'/agentos/v2/missions/{first["missionId"]}/semantics/receipts/edit-one').json()["result"] == response.json()
    assert len(client.get(f'/agentos/v2/missions/{first["missionId"]}/semantics/commits').json()["items"]) == 2
    replay = create(client)
    assert replay["runId"] == old.run_id
    new = client.post(f'/agentos/v2/missions/{first["missionId"]}/runs', json={"clientRequestId": "rerun-two",
        "sourceRunId": old.run_id, "rerunReason": "manual_rerun", "input": {"planningMode": "template_preferred", "deterministicIntent": True}})
    assert new.status_code == 202, new.text
    successor = finished(runtime, new.json()["runId"])
    assert run_intent_basis(successor).source_revision == 2
    assert run_intent_basis(successor).objective == "changed goal"
    assert run_intent_basis(successor).constraints == ()
    assert runtime.workflow_store.get_run(old.run_id).model_dump(mode="json", exclude={"trace"}) == old_state
    assert runtime.identity_lifecycle.repositories.runs.get(old.run_id).blueprint_id == old_plan.blueprint_id
    workspace = client.get(f'/agentos/v2/missions/{first["missionId"]}/workspace', params={"runId": old.run_id})
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["missionSemanticView"]["missionRevision"] == 2
    assert workspace.json()["selectedRunBasis"]["sourceRevision"] == 1


def test_conflicts_receipts_and_trusted_authorization(api):
    client, runtime, _, _ = api
    first = create(client)
    mission = first["missionId"]
    assert edit(client, mission).status_code == 200
    conflict = edit(client, mission, operation="stale")
    assert conflict.status_code == 409 and conflict.json()["status"] == "REVISION_CONFLICT"
    assert edit(client, mission, operation="stale").json() == conflict.json()
    assert edit(client, mission, revision=2, operation="stale").json()["status"] == "OPERATION_CONFLICT"
    no_op = edit(client, mission, revision=2, operation="unchanged")
    assert no_op.status_code == 200 and no_op.json()["status"] == "NO_OP"
    assert len(runtime.workflow_store.list_semantic_commits(mission)) == 2
    for headers in [{"x-authenticated-user-id": "intruder"}, {"x-authenticated-tenant-id": "other"}]:
        assert client.post(f"/agentos/v2/missions/{mission}/semantics", json={"operationId": "attack", "expectedMissionRevision": 2,
            "objective": "forged", "constraints": []}, headers=headers).status_code == 403
        assert client.get(f"/agentos/v2/missions/{mission}/semantics/receipts/edit-one", headers=headers).status_code == 403
    assert client.post('/agentos/v2/missions', json=BODY, headers={"x-internal-service-token": "wrong"}).status_code == 403
    assert client.post('/agentos/v2/missions', json={**BODY, "title": "different"}).status_code == 409
    assert runtime.workflow_store.get_semantic_snapshot(mission).mission_revision == 2


@pytest.mark.parametrize("semantics", [None, {"objective": " ", "constraints": []},
    {"objective": "x"}, {"objective": "x", "constraints": [{"constraintId": "a", "text": "x"}, {"constraintId": "a", "text": "y"}]},
    {"objective": "x", "constraints": [], "actorId": "spoof"}])
def test_invalid_creation_is_rejected_before_writes(api, semantics):
    client, runtime, _, _ = api
    assert client.post('/agentos/v2/missions', json={**BODY, "semantics": semantics}).status_code == 422
    assert not runtime.workflow_store.list_missions().items


@pytest.mark.parametrize("phase", ["identity", "commit_before", "commit_after", "prepare", "submit"])
def test_partial_creation_failure_recovers_same_mission_and_commit(api, monkeypatch, phase):
    client, runtime, coordinator, _ = api
    target, name = {"identity": (runtime.identity_lifecycle, "on_mission_created"),
        "commit_before": (runtime.mission_semantic_service, "commit"),
        "commit_after": (runtime.mission_semantic_service, "commit"),
        "prepare": (runtime, "prepare_run"), "submit": (coordinator, "submit")}[phase]
    original = getattr(target, name)
    if phase == "submit":
        async def fail(*args, **kwargs):
            raise RuntimeError("injected coordinator interruption")
    else:
        def fail(*args, **kwargs):
            if phase == "commit_after":
                original(*args, **kwargs)
            raise RuntimeError("injected creation interruption")
    monkeypatch.setattr(target, name, fail)
    response = client.post('/agentos/v2/missions', json=BODY)
    assert response.status_code == 503, response.text
    missions = runtime.workflow_store.list_missions().items
    assert len(missions) == 1
    mission = missions[0]
    assert client.post('/agentos/v2/missions', json={**BODY, "title": "changed"}).status_code == 409
    monkeypatch.setattr(target, name, original)
    recovered = create(client)
    assert recovered["missionId"] == mission.mission_id
    assert len(runtime.workflow_store.list_missions().items) == 1
    assert len(runtime.workflow_store.list_runs(owner_user_id="owner", owner_tenant_id="tenant").items) == 1
    assert len(runtime.workflow_store.list_semantic_commits(mission.mission_id)) == 1
    finished(runtime, recovered["runId"])


def test_flag_disabled_and_legacy_mission_initialization(api):
    client, runtime, _, _ = api
    runtime.mission_semantic_service = None
    legacy = create(client, {"title": "legacy", "workflowId": "semantic-test", "clientRequestId": "legacy-create",
        "input": {"source": "acg", "planningMode": "template_preferred", "deterministicIntent": True}})
    run = finished(runtime, legacy["runId"])
    assert run_intent_basis(run) is None
    assert client.get(f'/agentos/v2/missions/{legacy["missionId"]}/semantics').status_code == 409
    # Re-enable the existing installed schema. No migration or inferred facts.
    from components.mission_manager.semantic_service import MissionSemanticService
    repositories = runtime.identity_lifecycle.repositories
    runtime.mission_semantic_service = MissionSemanticService(store=runtime.workflow_store,
        authorize=lambda p, m, a: repositories.missions.get(m).user_id == p.actor_id
        and repositories.missions.get(m).metadata.get("tenantId") == p.tenant_id)
    view = client.get(f'/agentos/v2/missions/{legacy["missionId"]}/semantics').json()
    assert view["semanticStatus"] == "UNINITIALIZED" and view["objective"] is None
    assert edit(client, legacy["missionId"], revision=0).status_code == 200
    assert run_intent_basis(runtime.workflow_store.get_run(run.run_id)) is None


def test_concurrent_public_cas(api):
    client, runtime, _, _ = api
    mission = create(client)["missionId"]
    barrier = Barrier(2)
    def update(op):
        barrier.wait()
        return edit(client, mission, operation=op, objective=op)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["writer-one", "writer-two"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert runtime.workflow_store.get_semantic_snapshot(mission).mission_revision == 2


def test_committed_creation_recovers_after_runtime_reconstruction(tmp_path, monkeypatch):
    env = {**_environment(tmp_path), "AGENTOS_MISSION_SEMANTIC_CONVERGENCE": "true"}
    SQLiteWorkflowStore(env["AGENTOS_WORKFLOW_DB_PATH"], enable_mission_semantics=True)
    app = application(env)
    with TestClient(app, headers=HEADERS) as client:
        runtime, coordinator, _ = app.state.boundary
        async def fail(*args):
            raise RuntimeError("interrupt before submission")
        monkeypatch.setattr(coordinator, "submit", fail)
        assert client.post('/agentos/v2/missions', json=BODY).status_code == 503
        mission = runtime.workflow_store.list_missions().items[0]
        initial = runtime.workflow_store.list_runs(owner_user_id="owner", owner_tenant_id="tenant").items[0]
        commits = runtime.workflow_store.list_semantic_commits(mission.mission_id)
    app = application(env)
    with TestClient(app, headers=HEADERS) as client:
        runtime, _, _ = app.state.boundary
        recovered = create(client)
        assert recovered["missionId"] == mission.mission_id and recovered["runId"] == initial.run_id
        assert runtime.workflow_store.list_semantic_commits(mission.mission_id) == commits
        finished(runtime, initial.run_id)


def test_edit_storage_failure_retry_and_invalid_edit(api, monkeypatch):
    client, runtime, _, _ = api
    mission = create(client)["missionId"]
    service = runtime.mission_semantic_service
    original = service.store.commit_semantics
    def fail(*args):
        raise sqlite3.OperationalError("temporary storage outage")
    monkeypatch.setattr(service.store, "commit_semantics", fail)
    # HTTP exposes a retryable failure rather than fabricating a receipt.
    assert edit(client, mission).status_code == 503
    monkeypatch.setattr(service.store, "commit_semantics", original)
    assert edit(client, mission).status_code == 200
    invalid = {"operationId": "invalid", "expectedMissionRevision": 2, "objective": "x", "constraints": [], "actorId": "owner"}
    assert client.post(f'/agentos/v2/missions/{mission}/semantics', json=invalid).status_code == 422
    assert service.store.get_semantic_receipt(mission, "invalid") is None


def test_deleted_mission_hides_semantic_commands_and_receipts(api):
    client, runtime, _, _ = api
    created = create(client)
    finished(runtime, created["runId"])
    mission = created["missionId"]
    assert edit(client, mission).status_code == 200
    assert client.delete(f'/agentos/v2/missions/{mission}').status_code == 200
    assert client.post('/agentos/v2/missions', json=BODY).status_code == 404
    assert edit(client, mission).status_code == 404
    for suffix in ["", "/commits", "/receipts/edit-one"]:
        assert client.get(f'/agentos/v2/missions/{mission}/semantics' + suffix).status_code == 404
    assert len(runtime.workflow_store.list_semantic_commits(mission)) == 2
