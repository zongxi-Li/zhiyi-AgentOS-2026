"""Mission-scoped authorization above the existing formal tool dispatch boundary."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.tools.permissions import ApprovalDecision
from contracts.task_operator_policy import task_approval_scope_matches, task_operator_policy_projection
from contracts.workflow import MissionRecordState, RunRecordState, WorkflowStatus


class ApprovalPolicyChanged(RuntimeError):
    """A policy decision was revoked before its request WAL was committed."""


def assert_task_policy_target(store, run):
    """Authorize a current Mission policy target without mutating its Run."""
    mission = store.get_mission(run.mission_id)
    if (run.record_state != RunRecordState.ACTIVE or mission.record_state != MissionRecordState.ACTIVE
            or run.execution_state.get("supersededByRunId")
            or run.status not in {WorkflowStatus.PENDING, WorkflowStatus.PLANNING, WorkflowStatus.RUNNING,
                                  WorkflowStatus.RETRYING, WorkflowStatus.WAITING_REVIEW, WorkflowStatus.FAILED}):
        raise ValueError("Mission policy cannot be changed from this Run")
    # List summaries use updatedAt for recency. A late cleanup write on an old
    # Run must not make it the authority for a newer Run's Mission settings.
    page_number, found = 1, False
    while True:
        page = store.list_run_overviews(mission_id=run.mission_id,
            owner_user_id=run.input.get("authenticatedUserId"),
            owner_tenant_id=run.input.get("authenticatedTenantId"), page=page_number, page_size=100)
        for item in page.items:
            found = found or item.run_id == run.run_id
            if (item.created_at, item.run_id) > (run.created_at, run.run_id):
                raise ValueError("Historical Run cannot change the current Mission policy")
        if page_number * page.page_size >= page.total:
            break
        page_number += 1
    if not found:
        raise ValueError("Current Mission policy Run is unavailable")


def user_approval_decision(actor) -> dict[str, Any]:
    decision = {"source": "user", "decidedAt": datetime.now(timezone.utc).isoformat()}
    if actor is not None:
        decision["actor"] = {"userId": actor.user_id, "tenantId": actor.tenant_id}
    return decision


@dataclass(frozen=True)
class FormalApprovalContext:
    """Server-created identity. It is never accepted from a tool/model request."""
    mission_id: str
    run_id: str
    step_id: str
    attempt_id: str
    commit_id: str
    workspace_scope: dict[str, str]
    validate: Callable[[], None]


class TaskApprovalCoordinator:
    def __init__(self, runtime, permissions):
        self.runtime = runtime
        self.permissions = permissions
        self.store = getattr(runtime, "workflow_store", None)

    def _lock(self, mission_id):
        lock = getattr(self.store, "task_operator_policy_lock", None)
        return lock(mission_id) if callable(lock) else nullcontext()

    def workspace_scope(self, run) -> dict[str, str]:
        binding = run.input.get("workspaceBinding")
        if not isinstance(binding, dict) or not binding.get("workspaceId") or not binding.get("grantId"):
            raise PermissionError("Automatic approval requires the Run's frozen workspace authorization")
        authority = getattr(self.runtime, "workspace_authority", None)
        authorization = (authority.resolve(run) if authority else
                         getattr(self.runtime, "local_runtime_authorization", None))
        if (authorization is None or binding["workspaceId"] != authorization.workspace_id
                or binding["grantId"] != authorization.grant_id):
            raise PermissionError("Workspace authorization does not match the frozen Run")
        profile = getattr(getattr(self.runtime, "local_runtime_resource", None), "profile", None)
        resource_id = binding.get("resourceId") or getattr(profile, "runtime_id", None)
        scope = {"workspaceId": authorization.workspace_id, "grantId": authorization.grant_id}
        if resource_id:
            scope["resourceId"] = resource_id
        return scope

    def policy_projection(self, run):
        policy = self.store.get_task_operator_policy(run.mission_id)
        try:
            scope = self.workspace_scope(run)
        except Exception:
            # Read-side availability is not execution authority. Retain the
            # configured policy while reporting that FULL is not effective
            # when its live grant cannot be verified.
            scope = None
        return task_operator_policy_projection(policy, scope)

    def bind_context(self, context, guard, authorization) -> FormalApprovalContext | None:
        # Legacy/test runtimes without the policy port retain their existing ASK
        # behavior. Production formal Runs always have this port and a binding.
        if not callable(getattr(self.store, "get_task_operator_policy", None)):
            return None
        run = context.run
        try:
            scope = self.workspace_scope(run)
        except PermissionError:
            return None
        if (scope["workspaceId"] != authorization.workspace_id
                or scope["grantId"] != authorization.grant_id):
            raise PermissionError("Tool approval workspace identity changed")
        permit_id = run.execution_state.get("executionPermitId")

        def validate():
            guard()
            current = self.store.get_run(run.run_id)
            mission = self.store.get_mission(run.mission_id)
            if (current.mission_id != run.mission_id or current.status.value != "running"
                    or getattr(mission.record_state, "value", mission.record_state) != "active"
                    or getattr(current.record_state, "value", current.record_state) != "active"
                    or not permit_id or current.execution_state.get("executionPermitId") != permit_id
                    or current.execution_state.get("supersededByRunId")
                    or self.workspace_scope(current) != scope):
                raise PermissionError("Formal tool approval no longer belongs to a live execution")
            binding = current.execution_state.get("executionBindings", {}).get(context.step.step_id)
            if binding is not None and binding.get("attemptId") != context.attempt_id:
                raise PermissionError("Formal tool approval belongs to an obsolete Attempt")

        return FormalApprovalContext(run.mission_id, run.run_id, context.step.step_id,
                                     context.attempt_id, context.commit_id, scope, validate)

    @staticmethod
    def _matches(policy, context):
        return (policy.mission_id == context.mission_id
                and policy.permission == "task_collaboration" and policy.approval_mode == "full"
                and task_approval_scope_matches(policy, context.workspace_scope))

    def automatic_decision(self, context: FormalApprovalContext | None):
        if context is None:
            return None
        with self._lock(context.mission_id):
            policy = self.store.get_task_operator_policy(context.mission_id)
            if not self._matches(policy, context):
                return None
            context.validate()
            return self._policy_decision(policy)

    @staticmethod
    def _policy_decision(policy):
        return {"source": "policy", "policyRevision": policy.policy_revision,
                "actor": policy.updated_by.model_dump(by_alias=True, mode="json") if policy.updated_by else None,
                "decidedAt": datetime.now(timezone.utc).isoformat()}

    def admit(self, *, context, approval_decision, resource_id, commit):
        """Commit the original request WAL while serializing policy revocation.

        The callback is synchronous. No network dispatch or await occurs while
        this lock is held; its successful WAL commit is the admission point.
        """
        with self._lock(context.mission_id) if context else nullcontext():
            if context is not None:
                context.validate()
                if context.workspace_scope.get("resourceId", resource_id) != resource_id:
                    raise PermissionError("Tool resource differs from the frozen workspace binding")
            if approval_decision and approval_decision.get("source") == "policy":
                policy = self.store.get_task_operator_policy(context.mission_id)
                if (not self._matches(policy, context)
                        or policy.policy_revision != approval_decision.get("policyRevision")):
                    raise ApprovalPolicyChanged("Automatic approval changed before dispatch admission")
            return commit()

    def update(self, run, request, actor):
        if actor is None:
            raise PermissionError("Authenticated user required")
        assert_task_policy_target(self.store, run)
        scope = self.workspace_scope(run) if request.approval_mode == "full" else None
        with self._lock(run.mission_id):
            receipt = self.store.set_task_operator_policy(run.mission_id,
                permission=request.permission, approval_mode=request.approval_mode,
                workspace_scope=scope, actor={"userId": actor.user_id, "tenantId": actor.tenant_id},
                operation_id=request.operation_id,
                expected_policy_revision=request.expected_policy_revision)
            # Replaying an earlier enable operation must never revive it after
            # a later revocation. The Store returns that operation's receipt;
            # waiters and the UI use the current effective policy.
            policy = self.store.get_task_operator_policy(run.mission_id)
            approved = self._drain(policy)
        projection_scope = scope
        if projection_scope is None:
            try:
                projection_scope = self.workspace_scope(run)
            except PermissionError:
                pass
        return {"missionId": run.mission_id,
                **task_operator_policy_projection(policy, projection_scope),
                "operationPolicy": receipt.model_dump(by_alias=True, mode="json"),
                "autoApprovedCount": approved}

    def _drain(self, policy):
        approved = 0
        for request, context in self.permissions.trusted_pending():
            if not isinstance(context, FormalApprovalContext) or not self._matches(policy, context):
                continue
            try:
                self.permissions.resolve_now(request.approval_id,
                    decision=ApprovalDecision.ALLOW_ONCE, session_id=context.run_id,
                    invocation_id=request.invocation_id, capability_id=request.capability_id,
                    relative_path=request.relative_path, decision_metadata=self._policy_decision(policy))
            except (PermissionError, KeyError, ValueError, RuntimeError):
                # Expired, cancelled and stale identities remain untouched. A
                # saved policy still governs all subsequent valid operations.
                continue
            getattr(self.runtime, "formal_tool_pending", {}).pop(request.approval_id, None)
            approved += 1
        return approved

    def reconcile(self, mission_id):
        """Idempotent recovery if a policy update outlived its HTTP handler."""
        with self._lock(mission_id):
            return self._drain(self.store.get_task_operator_policy(mission_id))
