"""Stable identity vocabulary for Run-level deliverables."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


RUN_DELIVERABLE_ARTIFACT_KEY = "final"
RUN_DELIVERABLE_ARTIFACT_TYPE = "run_deliverable"
FINAL_SYNTHESIS_LOGICAL_ROLE = "final_synthesis"

# Planner roles retained by older templates and fallback plans.  They are
# accepted as planner intent, but the persisted Artifact still receives the
# canonical identity above.
FINAL_SYNTHESIS_ROLES = frozenset({
    "deliver",
    "delivery",
    "deliverable",
    "final",
    "final_output",
    "synthesis",
    "final_synthesis",
    "finalization",
    "aggregate",
})


class ArtifactCheck(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    check: Literal["content_integrity", "nonempty_content", "utf8_text", "json_syntax"]
    outcome: Literal["passed", "failed", "unverified"]


class ArtifactEvidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    verifier: Literal["artifact-content.v1"] = "artifact-content.v1"
    source_run_id: str = Field(alias="sourceRunId")
    commit_id: str = Field(alias="commitId")
    manifest_id: str = Field(alias="manifestId")
    checksum: str
    media_type: str = Field(alias="mediaType")
    byte_length: int = Field(alias="byteLength", ge=0)
    checks: tuple[ArtifactCheck, ...]
    # Content remains untrusted data despite its independently verified integrity.
    excerpt: str = Field(default="", max_length=2048)
    excerpt_truncated: bool = Field(default=False, alias="excerptTruncated")
    excerpt_status: Literal["included", "budget_exhausted", "not_text", "review_pending", "invalid_encoding"] = Field(alias="excerptStatus")
    business_acceptance: Literal["unverified"] = Field(default="unverified", alias="businessAcceptance")


def is_final_synthesis_role(role: Any) -> bool:
    return str(role or "").strip().lower() in FINAL_SYNTHESIS_ROLES


def is_run_deliverable_identity(artifact: Mapping[str, Any]) -> bool:
    return (
        str(artifact.get("artifactKey") or artifact.get("artifact_key") or "").strip().lower()
        == RUN_DELIVERABLE_ARTIFACT_KEY
        and str(artifact.get("artifactType") or artifact.get("artifact_type") or "").strip().lower()
        == RUN_DELIVERABLE_ARTIFACT_TYPE
    )


def canonicalize_artifact_identity(
    artifact: Mapping[str, Any], logical_role: Any = ""
) -> dict[str, Any]:
    """Apply the canonical slot/type to one persisted artifact descriptor."""
    normalized = dict(artifact)
    requested_key = str(normalized.get("artifactKey") or "primary")
    is_final = is_final_synthesis_role(logical_role)
    artifact_key = RUN_DELIVERABLE_ARTIFACT_KEY if is_final else requested_key
    artifact_type = (
        RUN_DELIVERABLE_ARTIFACT_TYPE
        if is_final
        else "primary_artifact" if artifact_key.strip().lower() == "primary"
        else "supporting_artifact"
    )
    metadata = normalized.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    metadata["logicalRole"] = (
        FINAL_SYNTHESIS_LOGICAL_ROLE if is_final else "supporting_artifact"
    )
    metadata["identityVersion"] = "run-deliverable.v1"
    normalized.update({
        "artifactKey": artifact_key,
        "artifactType": artifact_type,
        "type": artifact_type,
        "metadata": metadata,
    })
    return normalized


def final_synthesis_output_schema(
    schema: Mapping[str, Any], logical_role: Any = ""
) -> dict[str, Any]:
    """Allow the canonical final artifact type at the output boundary.

    Older persisted plans describe the final artifact as ``report`` while the
    Run-level identity contract canonicalizes it to ``run_deliverable``. Keep
    every other schema constraint intact and apply this compatibility only to
    a final-synthesis step's singular artifact type.
    """
    normalized = deepcopy(dict(schema))
    if not is_final_synthesis_role(logical_role):
        return normalized
    properties = normalized.get("properties")
    artifact = properties.get("artifact") if isinstance(properties, dict) else None
    artifact_properties = artifact.get("properties") if isinstance(artifact, dict) else None
    type_schema = artifact_properties.get("type") if isinstance(artifact_properties, dict) else None
    enum = type_schema.get("enum") if isinstance(type_schema, dict) else None
    if isinstance(enum, list) and RUN_DELIVERABLE_ARTIFACT_TYPE not in enum:
        type_schema["enum"] = [*enum, RUN_DELIVERABLE_ARTIFACT_TYPE]
    return normalized


def canonicalize_final_synthesis_nodes(
    nodes: Sequence[Any], relations: Sequence[Any]
) -> list[Any]:
    """Give one terminal artifact-generation node the canonical final role."""
    artifact_nodes = [
        node for node in nodes
        if getattr(node, "capability_requirements", ())
        and node.capability_requirements[0] == "artifact_generation"
    ]
    if not artifact_nodes:
        return list(nodes)
    explicit = [node for node in artifact_nodes if is_final_synthesis_role(node.logical_role)]
    outgoing = {relation.source_key for relation in relations}
    candidates = explicit or [node for node in artifact_nodes if node.key not in outgoing] or artifact_nodes
    final_node = candidates[-1]
    return [
        node.model_copy(update={"logical_role": FINAL_SYNTHESIS_LOGICAL_ROLE})
        if node.key == final_node.key
        else node.model_copy(update={"logical_role": "supporting_artifact"})
        if node in artifact_nodes and is_final_synthesis_role(node.logical_role)
        else node
        for node in nodes
    ]


__all__ = [
    "ArtifactCheck",
    "ArtifactEvidence",
    "FINAL_SYNTHESIS_LOGICAL_ROLE",
    "FINAL_SYNTHESIS_ROLES",
    "RUN_DELIVERABLE_ARTIFACT_KEY",
    "RUN_DELIVERABLE_ARTIFACT_TYPE",
    "canonicalize_artifact_identity",
    "canonicalize_final_synthesis_nodes",
    "final_synthesis_output_schema",
    "is_final_synthesis_role",
    "is_run_deliverable_identity",
]
