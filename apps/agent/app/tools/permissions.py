"""Shared tool permission policy and approval lifecycle.

This module is deliberately above the AgentOS Resource/Capability boundary.
It decides whether a Chat invocation may proceed; it never owns a host Grant,
resource credential, or filesystem executor.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictStr


ChatApprovalMode = Literal["ask", "auto", "full"]


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ApprovalDecision(str, Enum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    DENY = "deny"


class PermissionScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: StrictStr = Field(min_length=1)
    workspace_id: StrictStr = Field(min_length=1)
    relative_path: str | None = None


class SessionPermissionGrant(BaseModel):
    """An in-memory, session-scoped permission; never a Local Runtime Grant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: StrictStr = Field(alias="capabilityId", min_length=1)
    workspace_id: StrictStr = Field(alias="workspaceId", min_length=1)
    path_scope: str | None = Field(default=None, alias="pathScope")
    created_at: datetime = Field(alias="createdAt")
    session_id: StrictStr = Field(alias="sessionId", min_length=1)

    def matches(self, *, session_id: str, scope: PermissionScope) -> bool:
        return (
            self.session_id == session_id
            and self.capability_id == scope.capability_id
            and self.workspace_id == scope.workspace_id
            and self.path_scope == scope.relative_path
        )


class ApprovalRequest(BaseModel):
    """Safe-to-display approval identity; no credentials or host paths."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    approval_id: StrictStr = Field(alias="approvalId", min_length=1)
    tool_call_id: StrictStr = Field(alias="toolCallId", min_length=1)
    invocation_id: StrictStr = Field(alias="invocationId", min_length=1)
    tool_name: StrictStr = Field(alias="toolName", min_length=1)
    capability_id: StrictStr = Field(alias="capabilityId", min_length=1)
    relative_path: str | None = Field(default=None, alias="relativePath")
    operation_summary: StrictStr = Field(alias="operationSummary", min_length=1)
    created_at: datetime = Field(alias="createdAt")
    status: Literal["pending", "approved", "denied", "expired"] = "pending"
    session_id: StrictStr = Field(alias="sessionId", min_length=1)
    operation: StrictStr = Field(default="File operation", min_length=1)
    command: str | None = None
    cwd: str | None = None
    risk_notice: str | None = Field(default=None, alias="riskNotice")


class ApprovalResolutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409,
                 approval: ApprovalRequest | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        # A confirmed terminal receipt may reconcile a stale card. It is not a
        # fresh decision, permission grant, or instruction to repeat the tool.
        self.approval = approval


class PermissionDeniedError(RuntimeError):
    def __init__(
        self,
        code: str = "PERMISSION_DENIED",
        message: str = "Chat permission denied.",
        *,
        activity: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.activity = dict(activity or {})
        self.activity.setdefault("errorCode", code)


class SessionPermissionStore:
    """Ephemeral session grants; restart, session close, or clear removes them."""

    def __init__(self) -> None:
        self._grants: dict[str, list[SessionPermissionGrant]] = {}

    def add(self, grant: SessionPermissionGrant) -> SessionPermissionGrant:
        grants = self._grants.setdefault(grant.session_id, [])
        if not any(existing == grant for existing in grants):
            grants.append(grant)
        return grant

    def matches(self, session_id: str, scope: PermissionScope) -> bool:
        return any(
            grant.matches(session_id=session_id, scope=scope)
            for grant in self._grants.get(session_id, [])
        )

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._grants.clear()
        else:
            self._grants.pop(session_id, None)

    def grants(self, session_id: str) -> tuple[SessionPermissionGrant, ...]:
        return tuple(self._grants.get(session_id, ()))


class PermissionPolicy:
    DEFAULTS: Mapping[str, PermissionDecision] = {
        "fs.read": PermissionDecision.ALLOW,
        "fs.list": PermissionDecision.ALLOW,
        "fs.write": PermissionDecision.ASK,
        "fs.patch": PermissionDecision.ASK,
        "shell.exec": PermissionDecision.ASK,
    }

    def evaluate(
        self,
        scope: PermissionScope,
        *,
        session_id: str,
        session_grants: SessionPermissionStore,
    ) -> PermissionDecision:
        if session_grants.matches(session_id, scope):
            return PermissionDecision.ALLOW
        return self.DEFAULTS.get(scope.capability_id, PermissionDecision.DENY)


@dataclass
class _PendingApproval:
    request: ApprovalRequest
    future: asyncio.Future[tuple[ApprovalDecision, str | None]]
    emit: Callable[[str, dict[str, Any]], Awaitable[None]] | None
    trusted_context: Any = None
    decision_metadata: dict[str, Any] | None = None


CAPABILITY_BY_TOOL: Mapping[str, str] = {
    "read_file": "fs.read",
    "list_files": "fs.list",
    "write_file": "fs.write",
    "patch_file": "fs.patch",
    "run_command": "shell.exec",
}

_DRIVE_PATH = re.compile(r"^[A-Za-z]:")


def normalize_relative_path(value: Any) -> str | None:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return "."
    if raw.startswith("/") or _DRIVE_PATH.match(raw):
        return None
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        return None
    return "/".join(parts) or "."


def _operation_summary(
    tool_name: str,
    relative_path: str | None,
    arguments: Mapping[str, Any] | None = None,
) -> str:
    labels = {
        "read_file": "Read file",
        "list_files": "List directory",
        "write_file": "Write file",
        "patch_file": "Patch file",
        "run_command": "Run command",
    }
    label = labels.get(tool_name, "Use file capability")
    if tool_name == "run_command":
        args = arguments or {}
        mode = str(args.get("mode") or "shell")
        command = (
            " ".join([str(args.get("program") or ""), *[str(item) for item in args.get("args") or []]])
            if mode == "direct"
            else str(args.get("command") or "")
        ).strip()
        return f"{label}: {command or 'workspace command'}"
    return f"{label}: {relative_path or 'workspace target'}"


class ChatPermissionService:
    """Evaluate Chat permission and suspend the original tool call for approval."""

    def __init__(
        self,
        *,
        policy: PermissionPolicy | None = None,
        session_store: SessionPermissionStore | None = None,
        approval_ttl_seconds: float = 300.0,
    ) -> None:
        if approval_ttl_seconds <= 0:
            raise ValueError("approval_ttl_seconds must be positive")
        self.policy = policy or PermissionPolicy()
        self.session_store = session_store or SessionPermissionStore()
        self.approval_ttl = timedelta(seconds=approval_ttl_seconds)
        self._pending: dict[str, _PendingApproval] = {}
        self._completed: dict[str, ApprovalRequest] = {}

    async def authorize(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        call_id: str,
        session_id: str,
        workspace_id: str,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        approval_mode: ChatApprovalMode = "ask",
        trusted_context: Any = None,
        automatic_decision: Callable[[], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any] | None:
        capability_id = CAPABILITY_BY_TOOL.get(tool_name)
        relative_path = normalize_relative_path(
            arguments.get("cwd") if tool_name == "run_command" else arguments.get("path")
        )
        activity = self._activity(tool_name, capability_id, relative_path)
        if not capability_id or not session_id.strip() or not workspace_id.strip():
            raise PermissionDeniedError("PERMISSION_SCOPE_INVALID", activity=activity)
        if relative_path is None:
            raise PermissionDeniedError("PERMISSION_SCOPE_INVALID", activity=activity)

        scope = PermissionScope(
            capability_id=capability_id,
            workspace_id=workspace_id.strip(),
            relative_path=relative_path,
        )
        decision = self.policy.evaluate(
            scope,
            session_id=session_id,
            session_grants=self.session_store,
        )
        # Request-scoped selection never changes capability availability or path checks.
        if approval_mode not in {"ask", "auto", "full"}:
            raise PermissionDeniedError("PERMISSION_MODE_INVALID", activity=activity)
        if decision is PermissionDecision.ASK and (
            approval_mode == "full"
            or (approval_mode == "auto" and capability_id in {"fs.write", "fs.patch"})
        ):
            decision = PermissionDecision.ALLOW
        if decision is PermissionDecision.ALLOW:
            return
        if decision is PermissionDecision.DENY:
            raise PermissionDeniedError(activity=activity)

        # Only trusted application code supplies this callback/context. The
        # shared policy has already validated capability and relative paths;
        # task policy may resolve ASK, never DENY.
        if automatic_decision is not None:
            automatic = automatic_decision()
            if automatic is not None:
                return automatic

        now = datetime.now(timezone.utc)
        request = ApprovalRequest(
            approvalId=f"approval_{uuid4().hex}",
            toolCallId=call_id,
            invocationId=call_id,
            toolName=tool_name,
            capabilityId=capability_id,
            relativePath=relative_path,
            operationSummary=_operation_summary(tool_name, relative_path, arguments),
            createdAt=now,
            sessionId=session_id,
            operation="Run command" if tool_name == "run_command" else "File operation",
            command=(
                str(arguments.get("command") or "")
                if tool_name == "run_command" and str(arguments.get("mode") or "shell") != "direct"
                else None
            ),
            cwd=relative_path if tool_name == "run_command" else None,
            riskNotice=(
                "该命令将在当前 Windows 用户权限下运行，可能访问工作区外的文件或系统资源。"
                if tool_name == "run_command"
                else None
            ),
        )
        future: asyncio.Future[tuple[ApprovalDecision, str | None]] = (
            asyncio.get_running_loop().create_future()
        )
        pending = _PendingApproval(request=request, future=future, emit=emit,
                                   trusted_context=trusted_context)
        self._pending[request.approval_id] = pending
        try:
            # Register before rechecking: enabling a policy concurrently with
            # waiter creation must either drain it or be seen here.
            if automatic_decision is not None:
                automatic = automatic_decision()
                if automatic is not None:
                    self.resolve_now(request.approval_id, decision=ApprovalDecision.ALLOW_ONCE,
                        session_id=session_id, decision_metadata=automatic)
            if emit is not None and not future.done():
                await emit("approval_required", {"approval": request.model_dump(by_alias=True, mode="json")})
            try:
                resolution, resolution_code = await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=self.approval_ttl.total_seconds(),
                )
            except asyncio.TimeoutError:
                if not future.done():
                    future.set_result((ApprovalDecision.DENY, "APPROVAL_EXPIRED"))
                resolution, resolution_code = await future
            status = "approved" if resolution is not ApprovalDecision.DENY else "denied"
            if resolution_code == "APPROVAL_EXPIRED":
                status = "expired"
            resolved_request = request.model_copy(update={"status": status})
            self._completed[request.approval_id] = resolved_request
            if emit is not None:
                await emit(
                    "approval_resolved",
                    {
                        "approval": resolved_request.model_dump(by_alias=True, mode="json"),
                        "decision": resolution.value,
                        **({"approvalDecision": pending.decision_metadata}
                           if pending.decision_metadata else {}),
                    },
                )
            if resolution is ApprovalDecision.DENY:
                raise PermissionDeniedError(resolution_code or "PERMISSION_DENIED", activity=activity)
            if resolution is ApprovalDecision.ALLOW_SESSION and capability_id != "shell.exec":
                self.session_store.add(
                    SessionPermissionGrant(
                        capabilityId=scope.capability_id,
                        workspaceId=scope.workspace_id,
                        pathScope=scope.relative_path,
                        createdAt=now,
                        sessionId=session_id,
                    )
                )
            return pending.decision_metadata
        except asyncio.CancelledError:
            self._pending.pop(request.approval_id, None)
            if not future.done():
                future.cancel()
            raise
        finally:
            self._pending.pop(request.approval_id, None)

    async def resolve(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
        session_id: str,
        invocation_id: str | None = None,
        capability_id: str | None = None,
        relative_path: str | None = None,
        decision_metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        return self.resolve_now(approval_id, decision=decision, session_id=session_id,
            invocation_id=invocation_id, capability_id=capability_id,
            relative_path=relative_path, decision_metadata=decision_metadata)

    def resolve_now(
        self, approval_id: str, *, decision: ApprovalDecision, session_id: str,
        invocation_id: str | None = None, capability_id: str | None = None,
        relative_path: str | None = None,
        decision_metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Resolve once without yielding, including under a task policy lock."""
        pending = self._pending.get(approval_id)
        if pending is None:
            completed = self._completed.get(approval_id)
            if completed is not None:
                self._assert_resolution_identity(completed, session_id=session_id,
                    invocation_id=invocation_id, capability_id=capability_id, relative_path=relative_path)
                if completed.status == 'expired':
                    raise ApprovalResolutionError('APPROVAL_EXPIRED', 'approval has expired', approval=completed)
                raise ApprovalResolutionError("APPROVAL_REPLAYED", "approval has already been resolved",
                    approval=completed)
            raise ApprovalResolutionError("APPROVAL_NOT_FOUND", "approval does not exist", status_code=404)
        request = pending.request
        self._assert_resolution_identity(request, session_id=session_id,
            invocation_id=invocation_id, capability_id=capability_id, relative_path=relative_path)
        if request.capability_id == "shell.exec" and decision is ApprovalDecision.ALLOW_SESSION:
            raise ApprovalResolutionError(
                "APPROVAL_DECISION_UNSUPPORTED",
                "shell execution supports allow_once or deny only",
            )
        if datetime.now(timezone.utc) - request.created_at > self.approval_ttl:
            expired = request.model_copy(update={"status": "expired"})
            self._completed[approval_id] = expired
            self._pending.pop(approval_id, None)
            if not pending.future.done():
                pending.future.set_result((ApprovalDecision.DENY, "APPROVAL_EXPIRED"))
            raise ApprovalResolutionError("APPROVAL_EXPIRED", "approval has expired", approval=expired)
        if decision is not ApprovalDecision.DENY and pending.trusted_context is not None:
            pending.trusted_context.validate()
        pending.decision_metadata = dict(decision_metadata or {
            "source": "user", "decidedAt": datetime.now(timezone.utc).isoformat()})
        self._completed[approval_id] = request.model_copy(update={
            "status": "denied" if decision is ApprovalDecision.DENY else "approved"})
        self._pending.pop(approval_id, None)
        if not pending.future.done():
            pending.future.set_result((decision, None if decision is not ApprovalDecision.DENY else "PERMISSION_DENIED"))
        return request

    @staticmethod
    def _assert_resolution_identity(
        request: ApprovalRequest, *, session_id: str, invocation_id: str | None,
        capability_id: str | None, relative_path: str | None,
    ) -> None:
        """Apply the same isolation before resolving or revealing a receipt."""
        if request.session_id != session_id:
            raise ApprovalResolutionError("APPROVAL_SESSION_MISMATCH", "approval belongs to another session", status_code=403)
        if invocation_id is not None and invocation_id != request.invocation_id:
            raise ApprovalResolutionError("APPROVAL_INVOCATION_MISMATCH", "approval invocation does not match")
        if capability_id is not None and capability_id != request.capability_id:
            raise ApprovalResolutionError("APPROVAL_SCOPE_MISMATCH", "approval capability does not match")
        if relative_path is not None and relative_path != request.relative_path:
            raise ApprovalResolutionError("APPROVAL_SCOPE_MISMATCH", "approval path does not match")

    async def cancel_session(self, session_id: str) -> None:
        """Fail pending calls for a disconnected stream without revoking grants."""
        for approval_id, pending in list(self._pending.items()):
            if pending.request.session_id != session_id:
                continue
            self._pending.pop(approval_id, None)
            if not pending.future.done():
                pending.future.set_result((ApprovalDecision.DENY, "APPROVAL_CANCELLED"))

    async def close_session(self, session_id: str) -> None:
        """Explicitly end a Chat session and discard its ephemeral grants."""
        await self.cancel_session(session_id)
        self.session_store.clear(session_id)

    def pending(self, approval_id: str) -> ApprovalRequest | None:
        pending = self._pending.get(approval_id)
        return pending.request if pending else None

    def trusted_pending(self) -> tuple[tuple[ApprovalRequest, Any], ...]:
        """Internal coordinator view; trusted identities never enter model input."""
        return tuple((pending.request, pending.trusted_context)
                     for pending in self._pending.values()
                     if pending.trusted_context is not None)

    @staticmethod
    def _activity(tool_name: str, capability_id: str | None, relative_path: str | None) -> dict[str, Any]:
        kind = {
            "read_file": "file_read",
            "list_files": "file_list",
            "write_file": "file_write",
            "patch_file": "file_patch",
            "run_command": "terminal",
        }.get(tool_name, "file_work")
        activity: dict[str, Any] = {"kind": kind, "status": "failed"}
        if capability_id:
            activity["capabilityId"] = capability_id
        if relative_path:
            activity["relativePath"] = relative_path
        return activity


_chat_permission_service: ChatPermissionService | None = None


def get_chat_permission_service() -> ChatPermissionService:
    global _chat_permission_service
    if _chat_permission_service is None:
        from app.config import settings

        _chat_permission_service = ChatPermissionService(
            approval_ttl_seconds=float(settings.CHAT_APPROVAL_TTL_SECONDS)
        )
    return _chat_permission_service


__all__ = [
    "ApprovalDecision",
    "ApprovalRequest",
    "ApprovalResolutionError",
    "CAPABILITY_BY_TOOL",
    "ChatPermissionService",
    "PermissionDecision",
    "PermissionDeniedError",
    "PermissionPolicy",
    "PermissionScope",
    "SessionPermissionGrant",
    "SessionPermissionStore",
    "get_chat_permission_service",
    "normalize_relative_path",
]
