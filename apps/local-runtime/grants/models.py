"""Authoritative local workspace and grant records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def _require_id(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    canonical_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _require_id(self.workspace_id, "workspace_id"))
        root = Path(self.canonical_root)
        if not root.is_absolute():
            raise ValueError("canonical_root must be absolute")
        object.__setattr__(self, "canonical_root", root)


@dataclass(frozen=True)
class GrantRecord:
    grant_id: str
    workspace_id: str
    canonical_root: Path
    allowed_capabilities: frozenset[str]
    created_at: datetime
    expires_at: datetime | None = None
    revoked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _require_id(self.grant_id, "grant_id"))
        object.__setattr__(self, "workspace_id", _require_id(self.workspace_id, "workspace_id"))
        root = Path(self.canonical_root)
        if not root.is_absolute():
            raise ValueError("canonical_root must be absolute")
        object.__setattr__(self, "canonical_root", root)
        object.__setattr__(
            self,
            "allowed_capabilities",
            frozenset(str(item).strip() for item in self.allowed_capabilities if str(item).strip()),
        )
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")


__all__ = ["GrantRecord", "WorkspaceRecord"]
