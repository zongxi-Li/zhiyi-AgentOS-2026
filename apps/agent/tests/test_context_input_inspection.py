"""Context inspection exposes failed input addresses without publishing bodies."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agentos_v2 import create_router
from app.security.internal_auth import InternalServiceAuthMiddleware
from components.communicator.contracts import ContextPack
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.execution import NodeExecutionPhase, NodeExecutionRecord
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
from support.stores.memory_workflow_store import MemoryWorkflowStore


TOKEN = "context-inspection-test-service-token-32-characters"
HEADERS = {"X-Internal-Service-Token": TOKEN, "X-Authenticated-User-Id": "owner",
           "X-Authenticated-User-Subject": "owner-subject", "X-Authenticated-User-Role": "user",
           "X-Authenticated-Tenant-Id": "tenant"}
PRIVATE_BODY = "PRIVATE-ADMITTED-INPUT-MUST-NOT-LEAVE-INSPECTOR"


@pytest.fixture(params=[False, True], ids=["runtime", "identity"])
def inspection(tmp_path, request):
    workflows = MemoryWorkflowStore()
    values = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    missions, runs = {}, {}
    for suffix, owner in [("000000000001", "owner"), ("000000000002", "another-owner")]:
        mission = RuntimeMissionRecord(missionId="mission_" + suffix, title="Inspect failed context")
        run = RuntimeRunRecord(runId="run_" + suffix, missionId=mission.mission_id,
            workflowId="inspection", domain="general", runtimeEngine="acg",
            input={"authenticatedUserId": owner, "authenticatedTenantId": "tenant"})
        workflows.save_mission(mission)
        workflows.save_run(run)
        missions[mission.mission_id] = SimpleNamespace(user_id=owner, metadata={"tenantId": "tenant"})
        runs[run.run_id] = SimpleNamespace(mission_id=mission.mission_id, metadata={})
    run = workflows.get_run("run_000000000001")
    repositories = SimpleNamespace(runs=SimpleNamespace(get=runs.get), missions=SimpleNamespace(get=missions.get))
    runtime = SimpleNamespace(workflow_store=workflows, execution_value_store=values,
        get_status=workflows.get_run, get_status_cached=workflows.get_run,
        identity_lifecycle=SimpleNamespace(repositories=repositories) if request.param else None)
    app = FastAPI()
    app.add_middleware(InternalServiceAuthMiddleware, token=TOKEN)
    app.include_router(create_router(runtime, SimpleNamespace()))

    def snapshot(step_id="review", phase=NodeExecutionPhase.PREPARED, *, owner_run=run.run_id):
        operation = "commit:" + owner_run + ":" + step_id + ":0"
        pack = ContextPack(runId=owner_run, stepId=step_id, objective="Inspect context flow",
            stepGoal="Review accepted source", data={"finding": PRIVATE_BODY},
            sourceData={"source": {"finding": PRIVATE_BODY}}, sourceStepIds=["source"],
            evidenceRefs=["evidence:source"], tokensDelivered=12, tokensAvailable=12)
        reference = values.put_context_pack(run_id=owner_run, step_id=step_id,
            payload=pack.model_dump(by_alias=True, mode="json"), operation_id=operation)
        values.prepare_node_commit(run_id=owner_run, commit_id=operation)
        node = NodeExecutionRecord(operationId=operation, executionInstanceId=operation,
            runId=owner_run, stepId=step_id, attemptId="attempt:" + step_id,
            phase=phase, artifactRefs={"context": reference})
        values.transition_node_execution(node)
        return node, reference

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, values=values, workflows=workflows, run=run,
                              snapshot=snapshot, repositories=repositories, identity=request.param)
    values.close()


@pytest.mark.parametrize("phase", [NodeExecutionPhase.PREPARED, NodeExecutionPhase.FAILED])
def test_failed_or_prepared_context_returns_metadata_without_input_body(inspection, phase):
    node, reference = inspection.snapshot(phase=phase)
    before = inspection.workflows.get_run(inspection.run.run_id).model_dump(mode="json")

    response = inspection.client.get(f"/agentos/v2/runs/{inspection.run.run_id}/context-packs", headers=HEADERS)

    assert response.status_code == 200, response.text
    assert PRIVATE_BODY not in response.text
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["contextRef"] == reference and item["available"] is True
    assert item["operationId"] == node.operation_id and item["attemptId"] == node.attempt_id
    assert item["executionPhase"] == phase.value and item["snapshotKind"] == "execution_input"
    assert item["dataKeys"] == ["finding"] and item["sourceDataKeys"] == ["source"]
    assert item["fieldCount"] == item["sourceCount"] == 1
    assert "data" not in item and "sourceData" not in item
    assert inspection.workflows.get_run(inspection.run.run_id).model_dump(mode="json") == before
    assert inspection.values.get_node_commit(run_id=inspection.run.run_id, commit_id=node.operation_id)["stage"] == "prepared"


def test_context_inspection_rejects_unauthenticated_or_other_owner_run(inspection):
    inspection.snapshot(owner_run="run_000000000002")
    assert inspection.client.get(f"/agentos/v2/runs/{inspection.run.run_id}/context-packs").status_code == 401
    response = inspection.client.get("/agentos/v2/runs/run_000000000002/context-packs", headers=HEADERS)
    assert response.status_code == 404
    assert PRIVATE_BODY not in response.text


def test_context_inspection_cannot_dereference_another_runs_wal_input(inspection):
    _, private_reference = inspection.snapshot(owner_run="run_000000000002")
    operation = "commit:" + inspection.run.run_id + ":review:0"
    inspection.values.transition_node_execution(NodeExecutionRecord(operationId=operation,
        executionInstanceId=operation, runId=inspection.run.run_id, stepId="review",
        attemptId="own-attempt", phase=NodeExecutionPhase.PREPARED,
        artifactRefs={"context": private_reference}))

    response = inspection.client.get(f"/agentos/v2/runs/{inspection.run.run_id}/context-packs", headers=HEADERS)

    assert response.status_code == 200
    assert PRIVATE_BODY not in response.text
    item = response.json()["items"][0]
    assert item["available"] is False and "dataKeys" not in item
