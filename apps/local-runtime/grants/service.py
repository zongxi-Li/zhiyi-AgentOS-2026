"""Per-request grant validation for the Local Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from contracts.local_runtime import LocalRuntimeAuthorizationRef, LocalRuntimeCapability

from runtime.errors import AuthorizationError
from .models import GrantRecord
from .store import GrantStore


@dataclass(frozen=True)
class AuthorizedGrant:
    grant: GrantRecord
    workspace_id: str
    canonical_root: Path


class GrantAuthorizationService:
    def __init__(self, store: GrantStore) -> None:
        self.store = store

    def authorize(
        self,
        authorization: LocalRuntimeAuthorizationRef,
        capability: LocalRuntimeCapability,
        *,
        now: datetime | None = None,
    ) -> AuthorizedGrant:
        grant = self.store.get_grant(authorization.grant_id)
        if grant is None:
            raise AuthorizationError("GRANT_NOT_FOUND")
        if grant.workspace_id != authorization.workspace_id:
            raise AuthorizationError("WORKSPACE_MISMATCH")
        workspace = self.store.get_workspace(authorization.workspace_id)
        if workspace is None:
            raise AuthorizationError("WORKSPACE_NOT_FOUND")
        if workspace.canonical_root != grant.canonical_root:
            raise AuthorizationError("GRANT_ROOT_MISMATCH")
        if grant.revoked:
            raise AuthorizationError("GRANT_REVOKED")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if grant.expires_at is not None and current >= grant.expires_at:
            raise AuthorizationError("GRANT_EXPIRED")
        if capability.value not in grant.allowed_capabilities:
            raise AuthorizationError("CAPABILITY_DENIED")
        return AuthorizedGrant(
            grant=grant,
            workspace_id=workspace.workspace_id,
            canonical_root=workspace.canonical_root,
        )


__all__ = ["AuthorizedGrant", "GrantAuthorizationService"]
