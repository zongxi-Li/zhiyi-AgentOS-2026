"""Pending tool decisions retain the existing trusted Run and semantic boundaries."""
import asyncio

import pytest

from app.tools import permissions
from contracts.workflow import WorkflowStatus
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
