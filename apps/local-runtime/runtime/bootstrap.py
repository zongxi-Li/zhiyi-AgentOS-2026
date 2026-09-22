"""Strict startup bootstrap for local workspace and grant authority."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from contracts.local_runtime import LocalRuntimeCapability
from grants import InMemoryGrantStore
from workspace import CanonicalWorkspaceResolver


BOOTSTRAP_SCHEMA_VERSION = 1
BOOTSTRAP_CAPABILITIES = frozenset(
    {
        LocalRuntimeCapability.FS_READ.value,
        LocalRuntimeCapability.FS_LIST.value,
        LocalRuntimeCapability.FS_WRITE.value,
        LocalRuntimeCapability.FS_PATCH.value,
    }
)
SUPPORTED_CAPABILITIES = frozenset(
    {*BOOTSTRAP_CAPABILITIES, LocalRuntimeCapability.SHELL_EXEC.value}
)


class LocalRuntimeWorkspaceBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: StrictStr = Field(alias="workspaceId", min_length=1)
    root: StrictStr = Field(min_length=1)


class LocalRuntimeGrantBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: StrictStr = Field(alias="grantId", min_length=1)
    workspace_id: StrictStr = Field(alias="workspaceId", min_length=1)
    capabilities: list[StrictStr] = Field(min_length=1)
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    revoked: StrictBool = False

    @model_validator(mode="after")
    def validate_timestamps_and_capabilities(self) -> "LocalRuntimeGrantBootstrap":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("createdAt must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("expiresAt must be timezone-aware")
            if self.expires_at <= self.created_at:
                raise ValueError("expiresAt must be later than createdAt")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("grant capabilities must not contain duplicates")
        unsupported = set(self.capabilities) - SUPPORTED_CAPABILITIES
        if unsupported:
            raise ValueError("grant contains unsupported capabilities")
        return self


class LocalRuntimeGrantsBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[BOOTSTRAP_SCHEMA_VERSION] = Field(alias="schemaVersion")
    workspaces: list[LocalRuntimeWorkspaceBootstrap] = Field(min_length=1)
    grants: list[LocalRuntimeGrantBootstrap] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "LocalRuntimeGrantsBootstrap":
        workspace_ids = [item.workspace_id for item in self.workspaces]
        if len(set(workspace_ids)) != len(workspace_ids):
            raise ValueError("workspaceId values must be unique")
        grant_ids = [item.grant_id for item in self.grants]
        if len(set(grant_ids)) != len(grant_ids):
            raise ValueError("grantId values must be unique")
        workspace_set = set(workspace_ids)
        if any(item.workspace_id not in workspace_set for item in self.grants):
            raise ValueError("grant references an unknown workspaceId")
        return self


def load_grants_bootstrap(path: str | Path) -> LocalRuntimeGrantsBootstrap:
    """Load and validate a local-only bootstrap file without mutating authority."""
    bootstrap_path = Path(path).expanduser()
    try:
        payload = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        return LocalRuntimeGrantsBootstrap.model_validate(payload)
    except Exception as exc:
        raise RuntimeError("local runtime grants bootstrap is invalid") from exc


def build_grant_store_from_bootstrap(
    bootstrap: LocalRuntimeGrantsBootstrap,
    *,
    resolver: CanonicalWorkspaceResolver,
) -> InMemoryGrantStore:
    """Build the runtime-local authority from validated system configuration."""
    store = InMemoryGrantStore()
    for workspace in bootstrap.workspaces:
        store.issue_workspace(
            workspace_id=workspace.workspace_id,
            root=Path(workspace.root),
            resolver=resolver,
        )
    for grant in bootstrap.grants:
        store.issue_grant(
            grant_id=grant.grant_id,
            workspace_id=grant.workspace_id,
            capabilities=set(grant.capabilities),
            created_at=grant.created_at,
            expires_at=grant.expires_at,
            revoked=grant.revoked,
        )
    return store


__all__ = [
    "BOOTSTRAP_CAPABILITIES",
    "SUPPORTED_CAPABILITIES",
    "BOOTSTRAP_SCHEMA_VERSION",
    "LocalRuntimeGrantBootstrap",
    "LocalRuntimeGrantsBootstrap",
    "LocalRuntimeWorkspaceBootstrap",
    "build_grant_store_from_bootstrap",
    "load_grants_bootstrap",
]
