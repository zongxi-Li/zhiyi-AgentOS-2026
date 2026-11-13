from types import SimpleNamespace

from app.execution import run_capabilities
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowStatus


def test_tool_approval_authority_does_not_drift_when_live_pending_requests_change(monkeypatch):
    principal = SimpleNamespace(user_id="owner", tenant_id="tenant")
    monkeypatch.setattr(run_capabilities, "current_trusted_user", lambda: principal)
    monkeypatch.setattr(run_capabilities, "current_semantic_principal", lambda: principal)
    owner = {"authenticatedUserId": "owner", "authenticatedTenantId": "tenant"}
    mission = RuntimeMissionRecord(missionId="mission", title="task", input=owner)
    run = RuntimeRunRecord(missionId="mission", workflowId="workflow", domain="general", runtimeEngine="acg", input=owner,
        status=WorkflowStatus.RUNNING, executionState={"executionPermitId": "permit"})
    semantic = SimpleNamespace(require_read_access=lambda *_: None, require_write_access=lambda *_: None)
    runtime = SimpleNamespace(workflow_store=SimpleNamespace(get_mission=lambda _: mission, get_run=lambda _: run),
        mission_semantic_service=semantic, execution_permit_authority=object(), formal_tool_pending={})
    before = run_capabilities.project_run_capabilities(runtime, run)
    runtime.formal_tool_pending["approval"] = {"sessionId": run.run_id}
    after = run_capabilities.project_run_capabilities(runtime, run)
    assert before["canResolveToolApproval"] is True
    assert before == after
    def revoked(*_):
        raise PermissionError("revoked")
    semantic.require_write_access = revoked
    assert run_capabilities.project_run_capabilities(runtime, run)["canResolveToolApproval"] is False
