"""Automatic approval resumes the original waiter and commits through the formal WAL."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.tools.formal_workspace import FormalWorkspaceTools
from app.tools import formal_workspace as formal_module
from app.tools.permissions import (
    ApprovalDecision, ApprovalResolutionError, ChatPermissionService,
    PermissionDecision, PermissionDeniedError, PermissionPolicy,
)
from app.tools.task_approval import ApprovalPolicyChanged, TaskApprovalCoordinator
from components.executor.value_store import SQLiteExecutionValueStore
from components.resource.scheduler.leases import InMemoryLeaseCoordinator
from contracts.local_runtime import (LocalRuntimeAuthorizationRef, LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionRequest, LocalRuntimeExecutionResult)
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowStatus
from runtime.planning_interaction import CopilotPermissionRequest
from support.stores.memory_workflow_store import MemoryWorkflowStore


def selection(mode, revision=0, operation=None):
    return CopilotPermissionRequest(permission="task_collaboration", approvalMode=mode,
        expectedPolicyRevision=revision, operationId=operation or uuid4().hex)


@pytest.fixture
def approval_scope():
    store = MemoryWorkflowStore()
    mission = RuntimeMissionRecord(missionId="mission", title="review")
    store.save_mission(mission)
    scope = {"workspaceId": "workspace", "grantId": "grant", "resourceId": "hands"}
    run = RuntimeRunRecord(runId="run", missionId="mission", workflowId="workflow", domain="general",
        runtimeEngine="acg", status=WorkflowStatus.RUNNING, input={"workspaceBinding": scope},
        executionState={"executionPermitId": "permit", "executionBindings": {"node": {"attemptId": "attempt"}}})
    store.save_run(run)
    authorization = LocalRuntimeAuthorizationRef(workspaceId="workspace", grantId="grant")
    runtime = SimpleNamespace(workflow_store=store, local_runtime_authorization=authorization,
        local_runtime_resource=SimpleNamespace(profile=SimpleNamespace(runtime_id="hands")), formal_tool_pending={})
    service = ChatPermissionService()
    coordinator = TaskApprovalCoordinator(runtime, service)
    node = SimpleNamespace(run=run, step=SimpleNamespace(step_id="node"), attempt_id="attempt", commit_id="commit")
    context = coordinator.bind_context(node, lambda: None, authorization)
    actor = SimpleNamespace(user_id="operator", tenant_id="tenant")
    return SimpleNamespace(store=store, runtime=runtime, service=service, coordinator=coordinator,
        node=node, context=context, actor=actor, run=run)


async def wait_for_approval(scope, *, context=None, call_id="operation"):
    ready = asyncio.Event()
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
        if kind == "approval_required":
            request = payload["approval"]
            scope.runtime.formal_tool_pending[request["approvalId"]] = request
            ready.set()
    context = context or scope.context
    task = asyncio.create_task(scope.service.authorize(tool_name="run_command",
        arguments={"command": "inspect", "cwd": "."}, call_id=call_id,
        session_id=context.run_id, workspace_id=context.workspace_scope["workspaceId"],
        trusted_context=context, automatic_decision=lambda: scope.coordinator.automatic_decision(context), emit=emit))
    try:
        await asyncio.wait_for(ready.wait(), 2)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    return task, events, events[0][1]["approval"]["approvalId"]


@pytest.mark.asyncio
async def test_enable_resolves_original_waiter_once_with_policy_provenance(approval_scope):
    s = approval_scope
    task, events, approval_id = await wait_for_approval(s)
    response = s.coordinator.update(s.run, selection("full"), s.actor)
    assert response["autoApprovedCount"] == 1
    assert response["approvalMode"] == "full"
    decision = await task
    assert decision["source"] == "policy" and decision["policyRevision"] == 1
    assert decision["actor"] == {"userId": "operator", "tenantId": "tenant"}
    assert events[-1][1]["approval"]["invocationId"] == "operation"
    assert events[-1][1]["approvalDecision"] == decision
    assert s.coordinator.reconcile("mission") == 0
    with pytest.raises(ApprovalResolutionError, match="already been resolved"):
        await s.service.resolve(approval_id, decision=ApprovalDecision.ALLOW_ONCE, session_id="run")


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["mission", "workspace", "grant", "resource", "attempt", "permit", "ended", "expired"])
async def test_enable_ignores_nonmatching_or_stale_waiters(approval_scope, damage):
    s = approval_scope
    context = s.context
    if damage in {"workspace", "grant", "resource"}:
        key = {"workspace": "workspaceId", "grant": "grantId", "resource": "resourceId"}[damage]
        context = replace(context, workspace_scope={**context.workspace_scope, key: "other"})
    elif damage == "mission":
        s.store.save_mission(RuntimeMissionRecord(missionId="other-mission", title="other task"))
        context = replace(context, mission_id="other-mission")
    task, _, approval_id = await wait_for_approval(s, context=context)
    if damage in {"attempt", "permit", "ended"}:
        changed = s.store.get_run("run")
        if damage == "attempt": changed.execution_state["executionBindings"]["node"]["attemptId"] = "replacement"
        if damage == "permit": changed.execution_state["executionPermitId"] = "replacement"
        if damage == "ended": changed.status = WorkflowStatus.COMPLETED
        s.store.save_run(changed)
        if damage == "ended":
            s.run = changed.model_copy(deep=True, update={"run_id": "successor", "status": WorkflowStatus.RUNNING,
                "created_at": changed.created_at + timedelta(seconds=1), "updated_at": changed.updated_at + timedelta(seconds=1)})
            s.store.save_run(s.run)
    elif damage == "expired":
        pending = s.service._pending[approval_id]
        pending.request = pending.request.model_copy(update={"created_at": datetime.now(timezone.utc) - timedelta(hours=1)})
    result = s.coordinator.update(s.run, selection("full"), s.actor)
    assert result["autoApprovedCount"] == 0
    if damage == "expired":
        with pytest.raises(PermissionDeniedError, match="denied"):
            await task
    else:
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task


@pytest.mark.asyncio
async def test_replaying_old_enable_never_reenables_after_revocation(approval_scope):
    s = approval_scope
    enable = selection("full", operation="enable")
    s.coordinator.update(s.run, enable, s.actor)
    s.coordinator.update(s.run, selection("ask", 1), s.actor)
    task, _, _ = await wait_for_approval(s)
    try:
        response = s.coordinator.update(s.run, enable, s.actor)
        assert response["approvalMode"] == "ask" and response["policyRevision"] == 2
        assert response["operationPolicy"]["policyRevision"] == 1
        assert response["autoApprovedCount"] == 0 and not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task


def test_replaying_old_ask_projects_newer_effective_auto_policy(approval_scope):
    s = approval_scope
    ask = selection("ask", operation="ask")
    s.coordinator.update(s.run, ask, s.actor)
    s.coordinator.update(s.run, selection("full", 1), s.actor)
    response = s.coordinator.update(s.run, ask, s.actor)
    assert response["approvalMode"] == "full" and response["policyRevision"] == 2
    assert response["operationPolicy"]["approvalMode"] == "ask"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", [("write_file", {"path": "x", "content": "x"}),
    ("patch_file", {"path": "x"}), ("run_command", {"command": "inspect", "cwd": "."})])
async def test_full_reuses_policy_for_writes_and_shell_but_preserves_deny(approval_scope, tool, args):
    s = approval_scope
    s.coordinator.update(s.run, selection("full"), s.actor)
    decision = await s.service.authorize(tool_name=tool, arguments=args, call_id="call", session_id="run",
        workspace_id="workspace", trusted_context=s.context,
        automatic_decision=lambda: s.coordinator.automatic_decision(s.context))
    assert decision["source"] == "policy" and not s.service.trusted_pending()
    class Deny(PermissionPolicy):
        def evaluate(self, *args, **kwargs): return PermissionDecision.DENY
    s.service.policy = Deny()
    with pytest.raises(PermissionDeniedError):
        await s.service.authorize(tool_name=tool, arguments=args, call_id="call", session_id="run",
            workspace_id="workspace", automatic_decision=lambda: s.coordinator.automatic_decision(s.context))


def test_policy_revocation_and_request_admission_share_serialization_point(approval_scope):
    s = approval_scope
    s.coordinator.update(s.run, selection("full"), s.actor)
    decision = s.coordinator.automatic_decision(s.context)
    commits = []
    s.coordinator.update(s.run, selection("ask", 1), s.actor)
    with pytest.raises(ApprovalPolicyChanged):
        s.coordinator.admit(context=s.context, approval_decision=decision, resource_id="hands",
            commit=lambda: commits.append("request"))
    assert commits == []


@pytest.fixture
def formal_scope(approval_scope, tmp_path, monkeypatch):
    s = approval_scope
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    leases = InMemoryLeaseCoordinator()
    calls, events = [], []
    def bind(**kwargs):
        lease = leases.acquire(lease_id=uuid4().hex, resource_id="hands", capacity=1,
            run_id="run", step_id="node", attempt_id="attempt", slot_count=1,
            ttl=timedelta(seconds=90), now=datetime.now(timezone.utc))
        return SimpleNamespace(binding=SimpleNamespace(resource_id="hands", binding_id="binding"), lease=lease)
    async def healthy(_): return True
    async def publish(_, event): events.append(event)
    async def execute(request, identity, event_sink):
        # This fake transport still requires the real request WAL before dispatch.
        wal = store.get_tool_value(run_id="run", key=request.request_id + ":request")
        assert wal["identity"] == identity
        calls.append(request.request_id)
        receipt = {"checksum": "verified-test-receipt", "identity": identity}
        return LocalRuntimeExecutionResult(requestId=request.request_id, invocationId=request.invocation_id,
            status="completed", output={"executionId": "execution-" + request.request_id, "handsReceipt": receipt},
            startedAt=datetime.now(timezone.utc), completedAt=datetime.now(timezone.utc))
    s.runtime.execution_value_store = store
    s.runtime.local_runtime_health_projector = SimpleNamespace(refresh=healthy)
    s.runtime.local_runtime_transport = SimpleNamespace(execute_with_identity=execute)
    s.runtime.resource_binder = SimpleNamespace(coordinator=leases, bind_ready=bind, release=leases.release)
    monkeypatch.setattr(formal_module, "runtime_event_broker", SimpleNamespace(publish=publish))
    monkeypatch.setattr(formal_module, "get_chat_permission_service", lambda: s.service)
    s.tools = FormalWorkspaceTools(s.runtime, SimpleNamespace(allowed_tools=()), s.node, lambda: None)
    s.calls, s.events, s.values, s.leases = calls, events, store, leases
    try: yield s
    finally: store.close()


@pytest.mark.asyncio
async def test_formal_policy_decision_is_in_original_wal_receipt_record_and_activity(formal_scope):
    s = formal_scope
    s.coordinator.update(s.run, selection("full"), s.actor)
    result = await s.tools.execute("shell.exec", {"command": "inspect", "workdir": "."}, operation_key="command")
    wal = s.values.get_tool_value(run_id="run", key="command:request")
    assert wal["approvalDecision"] == result.record["approvalDecision"]
    assert wal["approvalDecision"]["source"] == "policy"
    assert s.values.list_tool_activity(run_id="run")[0]["approvalDecision"] == wal["approvalDecision"]
    assert s.calls == ["command"] and s.leases.active_slots("hands") == 0
    assert not any(e.event_type == "tool.approval_required" for e in s.events)
    # Completed retries return the frozen result without any additional dispatch.
    s.coordinator.update(s.run, selection("ask", 1), s.actor)
    replay = await s.tools.execute("shell.exec", {"command": "inspect", "workdir": "."}, operation_key="command")
    assert replay == result and s.calls == ["command"]


@pytest.mark.asyncio
async def test_revocation_before_wal_reasks_without_dispatching_or_leaking_lease(formal_scope):
    s = formal_scope
    s.coordinator.update(s.run, selection("full"), s.actor)
    changed = False
    async def revoke(_):
        nonlocal changed
        if not changed:
            changed = True
            s.coordinator.update(s.run, selection("ask", 1), s.actor)
        return True
    s.runtime.local_runtime_health_projector.refresh = revoke
    task = asyncio.create_task(s.tools.execute("shell.exec", {"command": "inspect", "workdir": "."}, operation_key="command"))
    try:
        async with asyncio.timeout(2):
            while not s.runtime.formal_tool_pending: await asyncio.sleep(0)
        assert s.calls == [] and s.values.get_tool_value(run_id="run", key="command:request") is None
        assert s.leases.active_slots("hands") == 0
        approval_id = next(iter(s.runtime.formal_tool_pending))
        await s.service.resolve(approval_id, decision=ApprovalDecision.ALLOW_ONCE, session_id="run")
        result = await task
        assert result.record["approvalDecision"]["source"] == "user"
        assert s.calls == ["command"] and s.leases.active_slots("hands") == 0
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_revocation_after_request_commit_keeps_original_admission(formal_scope, monkeypatch):
    s = formal_scope
    s.coordinator.update(s.run, selection("full"), s.actor)
    publish = formal_module.runtime_event_broker.publish
    async def revoke_after_admission(run_id, event):
        if event.event_type == "tool.execution_started":
            assert s.values.get_tool_value(run_id="run", key="command:request") is not None
            s.coordinator.update(s.run, selection("ask", 1), s.actor)
        await publish(run_id, event)
    monkeypatch.setattr("app.tools.formal_workspace.runtime_event_broker.publish", revoke_after_admission)
    result = await s.tools.execute("shell.exec", {"command": "inspect", "workdir": "."}, operation_key="command")
    assert s.calls == ["command"]
    assert result.record["approvalDecision"]["source"] == "policy"
    assert s.store.get_task_operator_policy("mission").approval_mode == "ask"


@pytest.mark.asyncio
async def test_durable_admitted_request_without_result_replays_after_policy_revocation(formal_scope):
    s = formal_scope
    s.coordinator.update(s.run, selection("full"), s.actor)
    decision = s.coordinator.automatic_decision(s.context)
    identity = {"runId": "run", "stepId": "node", "attemptId": "attempt", "commitId": "commit"}
    request = LocalRuntimeExecutionRequest(protocolVersion="1", requestId="command", invocationId="command",
        resourceId="hands", capabilityId="shell.exec", authorization=s.runtime.local_runtime_authorization,
        input={"command": "inspect", "workdir": "."},
        limits=LocalRuntimeExecutionLimits(timeoutSeconds=90, maxStdoutBytes=64000, maxStderrBytes=32000),
        idempotencyKey="command")
    wal = {"request": request.model_dump(by_alias=True, mode="json"), "identity": identity, "approvalDecision": decision}
    s.coordinator.admit(context=s.context, approval_decision=decision, resource_id="hands",
        commit=lambda: s.values.put_tool_value(run_id="run", step_id="node", key="command:request", payload=wal))
    s.coordinator.update(s.run, selection("ask", 1), s.actor)
    result = await s.tools.execute("shell.exec", {"command": "inspect", "workdir": "."}, operation_key="command")
    assert result.record["approvalDecision"] == decision
    assert s.calls == ["command"] and not s.runtime.formal_tool_pending
    assert s.values.get_tool_value(run_id="run", key="command:request") == wal
