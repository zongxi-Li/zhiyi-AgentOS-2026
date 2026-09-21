"""Grant store ports and an in-memory authority for the first runtime."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import GrantRecord, WorkspaceRecord


class GrantStore(Protocol):
    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None: ...

    def get_grant(self, grant_id: str) -> GrantRecord | None: ...


class InMemoryGrantStore:
    """Testable local authority; it never accepts a grant root from a request."""

    def __init__(self) -> None:
        self._workspaces: dict[str, WorkspaceRecord] = {}
        self._grants: dict[str, GrantRecord] = {}

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        return self._workspaces.get(workspace_id)

    def get_grant(self, grant_id: str) -> GrantRecord | None:
        return self._grants.get(grant_id)

    def put_workspace(self, workspace: WorkspaceRecord) -> None:
        self._workspaces[workspace.workspace_id] = workspace

    def put_grant(self, grant: GrantRecord) -> None:
        workspace = self.get_workspace(grant.workspace_id)
        if workspace is None:
            raise ValueError("grant workspace must be registered")
        if workspace.canonical_root != grant.canonical_root:
            raise ValueError("grant root must match its registered workspace")
        self._grants[grant.grant_id] = grant

    def issue_workspace(
        self,
        *,
        workspace_id: str,
        root: Path,
        resolver,
    ) -> WorkspaceRecord:
        workspace = WorkspaceRecord(
            workspace_id=workspace_id,
            canonical_root=resolver.canonicalize_root(root),
        )
        self.put_workspace(workspace)
        return workspace

    def issue_grant(
        self,
        *,
        grant_id: str,
        workspace_id: str,
        capabilities: set[str] | frozenset[str],
        created_at: datetime,
        expires_at: datetime | None = None,
        revoked: bool = False,
    ) -> GrantRecord:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError("grant workspace must be registered")
        grant = GrantRecord(
            grant_id=grant_id,
            workspace_id=workspace_id,
            canonical_root=workspace.canonical_root,
            allowed_capabilities=frozenset(capabilities),
            created_at=created_at,
            expires_at=expires_at,
            revoked=revoked,
        )
        self.put_grant(grant)
        return grant


__all__ = ["GrantStore", "InMemoryGrantStore"]
