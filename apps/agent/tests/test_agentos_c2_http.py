"""Real HTTP -> production composition -> temporary SQLite C2 integration."""
import asyncio
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from app.execution.wiring import build_default_runtime, close_runtime
from app.security.internal_auth import InternalServiceAuthMiddleware
from examples.contract_review import CONTRACT, WORKFLOW_ID, ContractReviewAgent, workflow
from support.stores import c2_schema_upgrade as ops
from runtime.execution_permit import ExecutionPermitError


TOKEN = "c2-http-test-service-token-32-characters"
HEADERS = {"X-Internal-Service-Token": TOKEN, "X-Authenticated-User-Id": "owner",
           "X-Authenticated-User-Subject": "test-owner", "X-Authenticated-User-Role": "user",
           "X-Authenticated-Tenant-Id": "tenant"}
PREFIX = "/agentos/v2"


class ScopedTools:
    def scoped(self, allowed_tools):
        return self


class NoModel:
    def generate_json(self, *args, **kwargs):
        raise AssertionError("deterministic template must not call a model")


def prepare(folder):
    paths = {role: folder / f"{role}.sqlite" for role in ("workflow", "checkpoint", "identity")}
    for role, path in paths.items():
        ops._initialize(role, path)
    assert ops.upgrade_databases(**paths)["status"] == "READY"


@contextmanager
def server(folder, *, semantic=True, c2=True, legacy=False):
    keys = ("EXECUTION_VALUE", "CONTENT_MANIFEST", "EXECUTION_MEMORY", "PROVENANCE", "AUDIT",
            "RESOURCE", "NODE", "AGENT", "RESOURCE_HEALTH", "EVOLUTION")
    env = {f"AGENTOS_{key}_DB": str(folder / f"{key}.sqlite") for key in keys}
    env.update(AGENTOS_WORKFLOW_DB_PATH=str(folder / "workflow.sqlite"),
               AGENTOS_LANGGRAPH_CHECKPOINT_DB=str(folder / "checkpoint.sqlite"),
               AGENTOS_IDENTITY_DB=str(folder / "identity.sqlite"),
               AGENTOS_MISSION_SEMANTIC_CONVERGENCE=str(semantic).lower(),
               AGENTOS_C2_EXECUTION_AUTHORITIES=str(c2).lower(),
               AGENTOS_ALLOW_LEGACY_MISSION_INTENT=str(legacy).lower())
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        # Match production lifespan ownership: SQLite resources and background
        # execution live on the same server thread, not the TestClient caller.
        runtime = build_default_runtime(environment=env, tool_runtime=ScopedTools(),
                                        model_runtime=object(), intent_llm=NoModel())
        agent = ContractReviewAgent()
        runtime.agent_registry.register(agent)
        runtime.workflow_registry.register(workflow())
        from examples.contract_review import BoundaryPlanner
        runtime.runtime_planning_coordinator.planner_for_run = lambda run: BoundaryPlanner()
        coordinator = RunExecutionCoordinator(runtime)
        app.include_router(create_router(runtime, coordinator))
        state.update(runtime=runtime, agent=agent)
        try:
            await coordinator.startup()
            yield
        finally:
            await coordinator.shutdown()
            close_runtime(runtime)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(InternalServiceAuthMiddleware, token=TOKEN)
    with TestClient(app, headers=HEADERS) as client:
        yield client, state["runtime"], state["agent"]


def create(client, key="create", *, semantics=True, payload=None):
    body = {"title": "HTTP controlled contract review", "workflowId": WORKFLOW_ID,
            "clientRequestId": key, "input": {"contractText": CONTRACT, "deterministicIntent": True}}
    if semantics:
        body["semantics"] = {"objective": "Review the contract and produce a traceable report",
                             "constraints": [], "sourceRefs": ["input:contractText"]}
    if payload:
        body["input"].update(payload)
    response = client.post(PREFIX + "/missions", json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def accepted(client, created):
    for _ in range(200):
        response = client.get(PREFIX + "/runs/" + created["runId"])
        assert response.status_code == 200, response.text
        result = response.json()
        if result["formalControl"]["commitId"]:
            return result["formalControl"]
        assert result["status"] != "failed", result
        time.sleep(.025)
    pytest.fail("HTTP planning did not produce a formal accepted Commit")


def base(created):
    return f'{PREFIX}/missions/{created["missionId"]}/runs/{created["runId"]}/graph'


def materialize(client, created, control, operation="materialize"):
    body = {"operationId": operation, "commitId": control["commitId"],
            "expectedCommitmentRevision": control["commitmentRevision"]}
    response = client.post(base(created) + "/materializations", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def activation_body(mat):
    return {"operationId": "activate", "materializationId": mat["materializationId"],
            "expectedGraphId": mat["graphId"], "expectedGraphVersion": mat["graphVersion"]}


def facts(runtime):
    with sqlite3.connect(runtime.workflow_store.db_path) as conn:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in (
            "planning_commit_records", "planning_commit_outbox", "graph_materializations", "graph_activations",
            "graph_activation_heads", "graph_handoffs", "graph_execution_permits", "runs", "tasks")}


def test_real_http_initial_chain_idempotency_and_restart(tmp_path):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, body = create(client)
        replay = client.post(PREFIX + "/missions", json=body)
        assert replay.status_code == 202 and replay.json()["runId"] == created["runId"]
        control = accepted(client, created)
        mat, request = materialize(client, created, control)
        before = facts(runtime)
        replay = client.post(base(created) + "/materializations", json=request)
        assert replay.json()["status"] == "IDEMPOTENT_REPLAY"
        assert replay.json()["materializationId"] == mat["materializationId"]
        conflict = client.post(base(created) + "/materializations", json={**request, "operationId": "competing"})
        assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "DUPLICATE_CONFLICT"
        assert facts(runtime) == before
        response = client.post(base(created) + "/activation", json=activation_body(mat))
        assert response.status_code == 200 and response.json()["status"] == "ACTIVATED_PAUSED", response.text
        before = facts(runtime)
        replay = client.post(base(created) + "/activation", json=activation_body(mat))
        assert replay.json()["status"] == "IDEMPOTENT_REPLAY"
        assert replay.json()["activationId"] == response.json()["activationId"]
        assert client.post(base(created) + "/activation", json={
            **activation_body(mat), "operationId": "competing",
        }).status_code == 409
        assert facts(runtime) == before
        run_response = client.get(PREFIX + "/runs/" + created["runId"]).json()
        final = run_response["formalControl"]
        assert final["status"] == "ACTIVATED_PAUSED" and final["executionAuthorized"] is False
        assert not agent.calls
        # Even a direct execution attempt cannot escape the no-Permit cut.
        with pytest.raises(ExecutionPermitError, match="still paused"):
            asyncio.run(runtime.execute_prepared_run(created["runId"]))
        assert not agent.calls
        assert not runtime.execution_value_store.list_node_commits(run_id=created["runId"])
        assert not before["graph_handoffs"] and not before["graph_execution_permits"]
        public = str([created, mat, response.json(), run_response])
        for secret in (TOKEN, "initialSourceFingerprint", "sourceProvenance", "idempotencyKey", "packageChecksum",
                       "authenticatedUserId", "signature", "contractText"):
            assert secret not in public
    with server(tmp_path) as (client, runtime, agent):
        restored = client.get(PREFIX + "/runs/" + created["runId"])
        assert restored.status_code == 200, restored.text
        assert restored.json()["formalControl"] == final
        assert not agent.calls
        replay = client.post(base(created) + "/activation", json=activation_body(mat))
        assert replay.status_code == 200 and replay.json()["status"] == "IDEMPOTENT_REPLAY"
    with server(tmp_path, semantic=False, c2=False, legacy=True) as (client, runtime, agent):
        restored = client.get(PREFIX + "/runs/" + created["runId"])
        assert restored.status_code == 200 and restored.json()["formalControl"] == final
        assert client.post(base(created) + "/activation", json=activation_body(mat)).status_code == 409
        before = facts(runtime)
        paused = asyncio.run(runtime.execute_prepared_run(created["runId"]))
        assert paused.execution_state["graphActivation"]["executionPermit"] is None
        assert facts(runtime) == before
        assert not agent.calls


def test_http_rejects_untrusted_stale_and_mismatched_sources_without_facts(tmp_path):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, _ = create(client)
        control = accepted(client, created)
        other, _ = create(client, "other")
        accepted(client, other)
        request = {"operationId": "materialize", "commitId": control["commitId"],
                   "expectedCommitmentRevision": control["commitmentRevision"]}
        before = facts(runtime)
        assert client.post(base(created) + "/materializations", json=request,
                           headers={"X-Internal-Service-Token": "wrong"}).status_code == 403
        for headers in ({"X-Authenticated-User-Id": "intruder"}, {"X-Authenticated-Tenant-Id": "other"}):
            assert client.post(base(created) + "/materializations", json=request, headers=headers).status_code == 403
        assert client.post(base(created) + "/materializations", json={**request, "expectedCommitmentRevision": 99}).status_code == 409
        assert client.post(base(other) + "/materializations", json=request).status_code == 409
        wrong_path = base(created).replace(created["missionId"], other["missionId"])
        assert client.post(wrong_path + "/materializations", json=request).status_code == 409
        for field in ("principal", "executionPermit", "graphVersion", "executionReceipt", "status"):
            assert client.post(base(created) + "/materializations", json={**request, field: {}}).status_code == 422
        for field in ("principal", "executionPermit", "graphVersion", "executionReceipt", "graphActivation"):
            assert client.post(PREFIX + "/missions", json={
                "title": "forged", "clientRequestId": "forged", "workflowId": WORKFLOW_ID,
                "semantics": {"objective": "forged", "constraints": [], "sourceRefs": []},
                "input": {field: {}},
            }).status_code == 422
        assert facts(runtime) == before
        mat, _ = materialize(client, created, control)
        request = activation_body(mat)
        before = facts(runtime)
        for change in ({"expectedGraphVersion": 2}, {"expectedGraphId": "forged"}, {"materializationId": "missing"}):
            assert client.post(base(created) + "/activation", json={**request, **change}).status_code == 409
        assert client.post(base(other) + "/activation", json=request).status_code == 409
        assert client.post(base(created) + "/activation", json=request,
                           headers={"X-Authenticated-User-Id": "intruder"}).status_code == 403
        assert facts(runtime) == before
        assert not agent.calls


def test_http_activation_interruption_reconciles_original_operation(tmp_path, monkeypatch):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, _ = create(client)
        mat, _ = materialize(client, created, accepted(client, created))
        with monkeypatch.context() as patch:
            def interrupted(*args, **kwargs):
                raise RuntimeError("private-signature-must-not-leak")
            patch.setattr(runtime, "commit_graph_activation", interrupted)
            response = client.post(base(created) + "/activation", json=activation_body(mat))
        assert response.status_code == 503 and "private-signature" not in response.text
        control = client.get(PREFIX + "/runs/" + created["runId"]).json()["formalControl"]
        assert control["status"] == "ACTIVATION_PREPARED" and control["executionAuthorized"] is False
        response = client.post(base(created) + "/activation", json=activation_body(mat))
        assert response.status_code == 200 and response.json()["status"] == "ACTIVATED_PAUSED"
        assert len(facts(runtime)["graph_activations"]) == 1
        assert not agent.calls


def test_http_changed_mission_revision_cannot_materialize_accepted_old_sources(tmp_path):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, _ = create(client)
        control = accepted(client, created)
        response = client.post(f'{PREFIX}/missions/{created["missionId"]}/semantics', json={
            "operationId": "edit", "expectedMissionRevision": 1, "objective": "A different contract review objective",
            "constraints": [], "sourceRefs": ["input:contractText"],
        })
        assert response.status_code == 200, response.text
        before = facts(runtime)
        response = client.post(base(created) + "/materializations", json={
            "operationId": "materialize", "commitId": control["commitId"],
            "expectedCommitmentRevision": control["commitmentRevision"],
        })
        assert response.status_code == 409, response.text
        assert facts(runtime) == before
        assert not agent.calls


@pytest.mark.parametrize("semantic,c2,legacy", [(False, False, False), (False, False, True),
                                                 (True, False, False), (True, False, True),
                                                 (True, True, False), (True, True, True)])
def test_http_legacy_switch_matrix(tmp_path, semantic, c2, legacy):
    prepare(tmp_path)
    with server(tmp_path, semantic=semantic, c2=c2, legacy=legacy) as (client, runtime, agent):
        body = {"title": "legacy compatibility", "workflowId": WORKFLOW_ID,
                "clientRequestId": "legacy", "input": {"deterministicIntent": True, "contractText": CONTRACT}}
        response = client.post(PREFIX + "/missions", json=body)
        if semantic and not legacy:
            assert response.status_code == 422, response.text
        else:
            assert response.status_code == 202, response.text
            run_id = response.json()["runId"]
            for _ in range(200):
                run = runtime.workflow_store.get_run(run_id)
                if run.status.value in {"completed", "failed"}:
                    break
                time.sleep(.025)
            if c2:
                assert run.status.value == "failed"  # Legacy basis cannot acquire a formal Commit.
                assert not agent.calls
            else:
                assert agent.calls  # Existing direct Legacy path is retained.
        if not c2:
            assert client.post(PREFIX + "/missions/m/runs/r/graph/activation", json={
                "operationId": "x", "materializationId": "x", "expectedGraphId": "x", "expectedGraphVersion": 1,
            }).status_code == 409


def test_c2_without_semantic_convergence_refuses_assembly(tmp_path):
    with pytest.raises(RuntimeError, match="requires AGENTOS_MISSION_SEMANTIC_CONVERGENCE"):
        with server(tmp_path, semantic=False, c2=True):
            pytest.fail("invalid assembly accepted")
