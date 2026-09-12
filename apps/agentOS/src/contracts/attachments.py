"""Stable identities for user-provided Mission input files."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InputAttachmentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    READY = "READY"
    FAILED = "FAILED"


class InputAttachment(BaseModel):
    """File identity and parsing metadata; large bodies live in ContentManifest."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    attachment_id: str = Field(alias="attachmentId", min_length=1)
    owner_user_id: str = Field(alias="ownerUserId", min_length=1)
    owner_tenant_id: str | None = Field(default=None, alias="ownerTenantId")
    original_filename: str = Field(alias="originalFilename", min_length=1)
    storage_key: str = Field(alias="storageKey", min_length=1)
    mime_type: str = Field(alias="mimeType", min_length=1)
    extension: str = Field(min_length=1)
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    status: InputAttachmentStatus
    extracted_content_ref: str | None = Field(default=None, alias="extractedContentRef")
    character_count: int = Field(default=0, alias="characterCount", ge=0)
    parser: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    parse_error: str | None = Field(default=None, alias="parseError")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="updatedAt"
    )


__all__ = ["InputAttachment", "InputAttachmentStatus"]
