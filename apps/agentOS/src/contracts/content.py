"""Content-addressed manifests used by the existing AgentOS execution runtime.

The contracts keep large bodies outside Mission, checkpoint and graph state.  A
manifest is small and stable; immutable fragments can be paged, verified and
assembled without truncating the source material.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.timestamps import UTCTimestamp


class ContentKind(str, Enum):
    MATERIAL = "material"
    INTERMEDIATE = "intermediate"
    ARTIFACT = "artifact"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PASSED = "passed"
    FAILED = "failed"


class ContentFragmentRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    fragment_id: str = Field(alias="fragmentId", min_length=1)
    manifest_id: str = Field(alias="manifestId", min_length=1)
    sequence: int = Field(ge=0)
    checksum: str = Field(min_length=64, max_length=64)
    byte_length: int = Field(alias="byteLength", ge=0)
    estimated_tokens: int | None = Field(default=None, alias="estimatedTokens", ge=0)
    source_refs: tuple[str, ...] = Field(default=(), alias="sourceRefs")
    constraint_refs: tuple[str, ...] = Field(default=(), alias="constraintRefs")
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        alias="verificationStatus",
    )
    complete: bool = True


class ContentManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    manifest_id: str = Field(alias="manifestId", min_length=1)
    kind: ContentKind
    owner_type: str = Field(alias="ownerType", min_length=1)
    owner_id: str = Field(alias="ownerId", min_length=1)
    media_type: str = Field(default="text/plain", alias="mediaType", min_length=1)
    checksum: str | None = Field(default=None, min_length=64, max_length=64)
    byte_length: int = Field(default=0, alias="byteLength", ge=0)
    fragment_count: int = Field(default=0, alias="fragmentCount", ge=0)
    estimated_tokens: int | None = Field(default=None, alias="estimatedTokens", ge=0)
    chunking_version: str = Field(default="content-bytes.v1", alias="chunkingVersion")
    sealed: bool = False
    created_at: UTCTimestamp = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="createdAt"
    )

    @model_validator(mode="after")
    def validate_sealed_checksum(self) -> "ContentManifest":
        if self.sealed and self.checksum is None:
            raise ValueError("sealed ContentManifest requires checksum")
        return self


class FragmentEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    manifest_id: str = Field(alias="manifestId", min_length=1)
    fragment_ref: ContentFragmentRef = Field(alias="fragmentRef")
    sequence: int = Field(ge=0)
    source_refs: tuple[str, ...] = Field(default=(), alias="sourceRefs")
    constraint_refs: tuple[str, ...] = Field(default=(), alias="constraintRefs")
    checksum: str = Field(min_length=64, max_length=64)
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    complete: bool = True
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        alias="verificationStatus",
    )


class WorksetUnitKind(str, Enum):
    CHUNK = "chunk"
    SECTION = "section"
    ITEM = "item"


class WorksetSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    source_manifest_refs: tuple[str, ...] = Field(alias="sourceManifestRefs", min_length=1)
    unit_kind: WorksetUnitKind = Field(default=WorksetUnitKind.CHUNK, alias="unitKind")
    cursor_strategy: str = Field(default="sequence", alias="cursorStrategy", min_length=1)
    packing_policy: str = Field(default="api_capacity", alias="packingPolicy")
    parallelism_policy: str = Field(default="scheduler_managed", alias="parallelismPolicy")
    estimated_unit_count: int | None = Field(default=None, alias="estimatedUnitCount", ge=0)

    def validate_sources(self, material_refs) -> None:
        invalid = set(self.source_manifest_refs) - set(material_refs)
        if invalid:
            raise ValueError(
                f"workset references unregistered materials: {sorted(invalid)}. "
                "Use only registered materialRefs; constraints and expected artifacts are not input materials. "
                "Omit workset if this task uses task input or upstream task outputs."
            )


__all__ = [
    "ContentFragmentRef",
    "ContentKind",
    "ContentManifest",
    "FragmentEnvelope",
    "VerificationStatus",
    "WorksetSpec",
    "WorksetUnitKind",
]
