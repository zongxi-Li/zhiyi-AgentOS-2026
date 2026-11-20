"""Mission-owned operator authorization, independent of graph and Run revisions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _PolicyContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class TaskApprovalWorkspaceScope(_PolicyContract):
    workspace_id: str = Field(alias="workspaceId", min_length=1)
    grant_id: str = Field(alias="grantId", min_length=1)
    resource_id: str | None = Field(default=None, alias="resourceId", min_length=1)


class TaskOperatorActor(_PolicyContract):
    user_id: str = Field(alias="userId", min_length=1)
    tenant_id: str | None = Field(default=None, alias="tenantId", min_length=1)


class TaskOperatorPolicy(_PolicyContract):
    mission_id: str = Field(alias="missionId", min_length=1)
    permission: Literal["read_only", "task_collaboration"] = "task_collaboration"
    approval_mode: Literal["ask", "full"] = Field(default="ask", alias="approvalMode")
    policy_revision: int = Field(default=0, alias="policyRevision", ge=0)
    workspace_scope: TaskApprovalWorkspaceScope | None = Field(default=None, alias="workspaceScope")
    updated_by: TaskOperatorActor | None = Field(default=None, alias="updatedBy")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    operation_id: str | None = Field(default=None, alias="operationId", min_length=1)

    @model_validator(mode="after")
    def validate_auto_approval_scope(self):
        if self.approval_mode == "full" and (
            self.permission != "task_collaboration" or self.workspace_scope is None
        ):
            raise ValueError("automatic approval requires task collaboration and a workspace scope")
        return self


class TaskOperatorPolicyChange(_PolicyContract):
    """Normalized request identity shared by persistent Store adapters."""

    permission: Literal["read_only", "task_collaboration"]
    approval_mode: Literal["ask", "full"] = "ask"
    workspace_scope: TaskApprovalWorkspaceScope | None = None
    actor: TaskOperatorActor | None = None
    operation_id: str | None = Field(default=None, min_length=1)
    expected_policy_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_auto_approval_request(self):
        if self.approval_mode == "full" and (
            self.permission != "task_collaboration" or self.workspace_scope is None
            or self.actor is None or not self.operation_id or self.expected_policy_revision is None
        ):
            raise ValueError("automatic approval requires collaboration, scope, actor, operationId and expectedPolicyRevision")
        return self


class TaskOperatorPolicyConflict(ValueError):
    """A policy CAS or operation identity conflicts with a committed change."""


def task_approval_scope_matches(policy: TaskOperatorPolicy, binding) -> bool:
    scope = policy.workspace_scope
    return bool(scope and isinstance(binding, dict) and not binding.get("revoked", False)
        and binding.get("workspaceId") == scope.workspace_id
        and binding.get("grantId") == scope.grant_id
        and binding.get("resourceId") == scope.resource_id)


def task_operator_policy_projection(policy: TaskOperatorPolicy, binding) -> dict:
    scope_matches = task_approval_scope_matches(policy, binding)
    effective_mode = "full" if (policy.permission == "task_collaboration"
        and policy.approval_mode == "full" and scope_matches) else "ask"
    return {"taskPermission": policy.permission, "approvalMode": effective_mode,
        "policyRevision": policy.policy_revision,
        "approvalPolicy": {**policy.model_dump(by_alias=True, mode="json"),
            "effectiveApprovalMode": effective_mode, "effectiveScopeMatch": scope_matches}}


def public_approval_decision(value) -> dict | None:
    """Project only public decision provenance from an existing request WAL."""
    if not isinstance(value, dict) or value.get("source") not in {"policy", "user"}:
        return None
    decided_at = value.get("decidedAt")
    if not isinstance(decided_at, str):
        return None
    try:
        datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    result = {"source": value["source"], "decidedAt": decided_at}
    revision = value.get("policyRevision")
    if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0:
        result["policyRevision"] = revision
    actor = value.get("actor")
    if isinstance(actor, dict) and isinstance(actor.get("userId"), str) and actor["userId"]:
        tenant_id = actor.get("tenantId")
        if tenant_id is None or isinstance(tenant_id, str):
            result["actor"] = {"userId": actor["userId"], "tenantId": tenant_id}
    return result
