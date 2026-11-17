"""Pending tool decisions retain the existing trusted Run and semantic boundaries."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.tools import permissions
from contracts.workflow import WorkflowStatus
from contracts.local_runtime import LocalRuntimeAuthorizationRef
from test_mission_semantic_commands import api, create


def pending_run(api, monkeypatch):
    client, runtime, coordinator, _ = api

    async def hold(_):
        return False

    monkeypatch.setattr(coordinator, "submit", hold)
    created = create(client)
    run = runtime.workflow_store.get_run(created["runId"])
    run.status = WorkflowStatus.RUNNING
    run.execution_state["executionPermitId"] = "test-permit"
    runtime.workflow_store.save_run(run)
    return client, runtime, run


def test_tool_approval_snapshot_rechecks_current_semantic_read_scope(api, monkeypatch):
    client, runtime, run = pending_run(api, monkeypatch)
    service = permissions.ChatPermissionService()
    monkeypatch.setattr(permissions, "get_chat_permission_service", lambda: service)
    runtime.formal_tool_pending = {}
    task = None

    async def start():
        nonlocal task

        async def emit(kind, payload):
            if kind == "approval_required":
                request = payload["approval"]
                runtime.formal_tool_pending[request["approvalId"]] = request

        task = asyncio.create_task(service.authorize(tool_name="run_command",
            arguments={"command": "inspect", "cwd": "."}, call_id="tool-call",
            session_id=run.run_id, workspace_id="workspace", emit=emit))
        await asyncio.sleep(0)

    client.portal.call(start)
    url = f"/agentos/v2/runs/{run.run_id}/tool-approvals"
    try:
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert [item["command"] for item in response.json()["items"]] == ["inspect"]
        for headers in ({"x-authenticated-user-id": "intruder"},
                        {"x-authenticated-tenant-id": "foreign"}):
            assert client.get(url, headers=headers).status_code in {403, 404}
        authorize = runtime.mission_semantic_service.authorize
        monkeypatch.setattr(runtime.mission_semantic_service, "authorize",
            lambda principal, mission, action: action != "read" and authorize(principal, mission, action))
        assert client.get(url).status_code == 403
    finally:
        async def cleanup():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        client.portal.call(cleanup)


@pytest.mark.parametrize("blocked", ["owner", "tenant", "write", "status", "permit", "superseded"])
def test_tool_approval_command_keeps_existing_execution_scope(api, monkeypatch, blocked):
    client, runtime, run = pending_run(api, monkeypatch)
    runtime.formal_tool_pending = {"approval": {"sessionId": run.run_id}}
    headers = {}
    if blocked in {"owner", "tenant"}:
        headers = {"x-authenticated-user-id" if blocked == "owner" else "x-authenticated-tenant-id": "other"}
    elif blocked == "write":
        authorize = runtime.mission_semantic_service.authorize
        monkeypatch.setattr(runtime.mission_semantic_service, "authorize",
            lambda principal, mission, action: action != "write" and authorize(principal, mission, action))
    else:
        if blocked == "status":
            run.status = WorkflowStatus.FAILED
        elif blocked == "permit":
            run.execution_state.pop("executionPermitId")
        else:
            run.execution_state["supersededByRunId"] = "replacement"
        runtime.workflow_store.save_run(run)
    response = client.post(f"/agentos/v2/runs/{run.run_id}/tool-approvals/approval",
        json={"decision": "allow_once"}, headers=headers)
    assert response.status_code in {403, 404, 409}, response.text
    assert "approval" in runtime.formal_tool_pending


def test_tool_approval_command_requires_a_live_waiter(api, monkeypatch):
    client, runtime, run = pending_run(api, monkeypatch)
    service = permissions.ChatPermissionService()
    monkeypatch.setattr(permissions, "get_chat_permission_service", lambda: service)
    runtime.formal_tool_pending = {"approval": {"sessionId": run.run_id,
        "invocationId": "tool-call", "capabilityId": "shell.exec", "relativePath": "."}}
    response = client.post(f"/agentos/v2/runs/{run.run_id}/tool-approvals/approval",
        json={"decision": "allow_once"})
    assert response.status_code == 404, response.text
    assert "approval" in runtime.formal_tool_pending


def bind_auto_approval_workspace(runtime, run, monkeypatch):
    monkeypatch.setattr(runtime, "local_runtime_resource",
        SimpleNamespace(profile=SimpleNamespace(runtime_id="hands")), raising=False)
    scope = {"workspaceId": "workspace", "grantId": "grant",
             "resourceId": runtime.local_runtime_resource.profile.runtime_id}
    run.input["workspaceBinding"] = scope
    runtime.workflow_store.save_run(run)
    monkeypatch.setattr(runtime, "workspace_authority", None, raising=False)
    monkeypatch.setattr(runtime, "local_runtime_authorization",
        LocalRuntimeAuthorizationRef(workspaceId="workspace", grantId="grant"), raising=False)
    return scope


def test_auto_approval_http_persists_trusted_policy_and_independent_revision(api, monkeypatch):
    client, runtime, run = pending_run(api, monkeypatch)
    scope = bind_auto_approval_workspace(runtime, run, monkeypatch)
    url = f"/agentos/v2/runs/{run.run_id}/copilot/permission"
    body = {"permission": "task_collaboration", "approvalMode": "full",
            "operationId": "enable", "expectedPolicyRevision": 0}
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["approvalMode"] == "full" and payload["policyRevision"] == 1
    assert payload["approvalPolicy"]["workspaceScope"] == scope
    assert payload["approvalPolicy"]["updatedBy"] == {"userId": "owner", "tenantId": "tenant"}
    assert runtime.workflow_store.get_run(run.run_id).runtime_revision == run.runtime_revision
    assert client.get(f"/agentos/v2/runs/{run.run_id}/copilot").json()["approvalMode"] == "full"
    replay = client.post(url, json=body)
    assert replay.status_code == 200 and replay.json()["policyRevision"] == 1
    assert client.post(url, json={**body, "operationId": "stale"}).status_code == 409
    # Old clients deliberately restore the original ask behavior.
    legacy = client.post(url, json={"permission": "task_collaboration"})
    assert legacy.status_code == 200 and legacy.json()["approvalMode"] == "ask"


@pytest.mark.parametrize("error", [PermissionError("revoked grant"), RuntimeError("authority unavailable")])
def test_copilot_get_reports_ineffective_auto_policy_when_live_grant_cannot_be_verified(api, monkeypatch, error):
    client, runtime, run = pending_run(api, monkeypatch)
    bind_auto_approval_workspace(runtime, run, monkeypatch)
    response = client.post(f"/agentos/v2/runs/{run.run_id}/copilot/permission", json={
        "permission": "task_collaboration", "approvalMode": "full", "operationId": "enable", "expectedPolicyRevision": 0})
    assert response.status_code == 200, response.text
    def revoked(_): raise error
    monkeypatch.setattr(runtime, "workspace_authority", SimpleNamespace(resolve=revoked))
    response = client.get(f"/agentos/v2/runs/{run.run_id}/copilot")
    assert response.status_code == 200, response.text
    policy = response.json()
    assert policy["approvalMode"] == "ask"
    assert policy["approvalPolicy"]["approvalMode"] == "full"
    assert policy["approvalPolicy"]["effectiveScopeMatch"] is False


@pytest.mark.parametrize("blocked", ["owner", "tenant", "scope", "terminal", "missing_revision", "model_actor"])
def test_auto_approval_http_preserves_authority_and_terminal_boundaries(api, monkeypatch, blocked):
    client, runtime, run = pending_run(api, monkeypatch)
    bind_auto_approval_workspace(runtime, run, monkeypatch)
    body = {"permission": "task_collaboration", "approvalMode": "full",
            "operationId": "enable", "expectedPolicyRevision": 0}
    headers = {}
    if blocked in {"owner", "tenant"}:
        headers = {"x-authenticated-user-id" if blocked == "owner" else "x-authenticated-tenant-id": "other"}
    elif blocked == "scope":
        def revoked(_): raise PermissionError("revoked grant")
        monkeypatch.setattr(runtime, "workspace_authority", SimpleNamespace(resolve=revoked))
    elif blocked == "terminal":
        run.status = WorkflowStatus.COMPLETED
        runtime.workflow_store.save_run(run)
    elif blocked == "missing_revision":
        body.pop("expectedPolicyRevision")
    elif blocked == "model_actor":
        body["actor"] = {"userId": "forged"}
    response = client.post(f"/agentos/v2/runs/{run.run_id}/copilot/permission", json=body, headers=headers)
    assert response.status_code in {403, 404, 409, 422}, response.text
    assert runtime.workflow_store.get_task_operator_policy(run.mission_id).approval_mode == "ask"


def test_latest_failed_run_can_update_mission_policy_without_modifying_or_submitting_the_run(api, monkeypatch):
    client, runtime, run = pending_run(api, monkeypatch)
    bind_auto_approval_workspace(runtime, run, monkeypatch)
    run.status = WorkflowStatus.FAILED
    runtime.workflow_store.save_run(run)
    before = runtime.workflow_store.get_run(run.run_id)
    response = client.post(f"/agentos/v2/runs/{run.run_id}/copilot/permission", json={
        "permission": "task_collaboration", "approvalMode": "full", "operationId": "enable-for-recovery",
        "expectedPolicyRevision": 0})
    assert response.status_code == 200, response.text
    assert response.json()["approvalMode"] == "full" and response.json()["autoApprovedCount"] == 0
    assert runtime.workflow_store.get_run(run.run_id) == before


@pytest.mark.parametrize("blocked", ["newer_run", "superseded", "archived", "cancelled"])
def test_failed_run_policy_update_cannot_use_historical_or_closed_scope(api, monkeypatch, blocked):
    from contracts.workflow import MissionRecordState
    client, runtime, run = pending_run(api, monkeypatch)
    bind_auto_approval_workspace(runtime, run, monkeypatch)
    run.status = WorkflowStatus.FAILED
    if blocked == "newer_run":
        newer = run.model_copy(deep=True, update={"run_id": "newer-run", "status": WorkflowStatus.PENDING,
            "created_at": run.created_at + timedelta(seconds=1), "updated_at": run.updated_at + timedelta(seconds=1)})
        runtime.workflow_store.save_run(newer)
        # Cleanup can update the historical failed Run later than its successor.
        run.updated_at = newer.updated_at + timedelta(seconds=1)
    elif blocked == "superseded": run.execution_state["supersededByRunId"] = "replacement"
    elif blocked == "cancelled": run.status = WorkflowStatus.CANCELLED
    runtime.workflow_store.save_run(run)
    if blocked == "archived":
        runtime.workflow_store.set_mission_record_state(run.mission_id, MissionRecordState.ARCHIVED)
    response = client.post(f"/agentos/v2/runs/{run.run_id}/copilot/permission", json={
        "permission": "task_collaboration", "approvalMode": "full", "operationId": "enable",
        "expectedPolicyRevision": 0})
    assert response.status_code == 409, response.text
    assert runtime.workflow_store.get_task_operator_policy(run.mission_id).approval_mode == "ask"
