"""Read-only public projection of persisted repository review facts."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from contracts.execution_evidence import workspace_relative_path


class _DisplayFact(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)


class _ReviewGaps(_DisplayFact):
    missing_read_count: int = Field(alias="missingReadCount", ge=0)
    missing_listing_count: int = Field(alias="missingListingCount", ge=0)
    unsupported_entry_count: int = Field(alias="unsupportedEntryCount", ge=0)
    missing_reads: list[str] = Field(default_factory=list, alias="missingReads")
    missing_listings: list[str] = Field(default_factory=list, alias="missingListings")
    unsupported_entries: list[str] = Field(default_factory=list, alias="unsupportedEntries")

    @field_validator("missing_reads", "missing_listings", "unsupported_entries")
    @classmethod
    def relative_paths(cls, values):
        return [workspace_relative_path(value) for value in values]


class _ReviewRound(_DisplayFact):
    round: int = Field(ge=0)
    graph_version: int = Field(alias="graphVersion", ge=1)
    action: str
    reason: str | None = None
    step_ids: list[str] = Field(default_factory=list, alias="stepIds")
    added_step_ids: list[str] = Field(default_factory=list, alias="addedStepIds")
    observation_ref: str | None = Field(default=None, alias="observationRef")
    decision_ref: str | None = Field(default=None, alias="decisionRef")
    patch_ref: str | None = Field(default=None, alias="patchRef")
    trace_refs: list[str] = Field(default_factory=list, alias="traceRefs")


class _WorkspaceReview(_DisplayFact):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    round: int = Field(ge=0)
    graph_version: int = Field(alias="graphVersion", ge=1)
    status: Literal["reading", "reviewing", "completed", "blocked"]
    gaps: _ReviewGaps
    rounds: list[_ReviewRound] = Field(default_factory=list)


def workspace_review_status(action, observation_id, graph_version, continuation) -> str:
    """Only the proposal owned by this observation can keep its review open."""
    if action == "complete":
        return "completed"
    if (isinstance(continuation, dict) and continuation.get("observationId") == observation_id
            and continuation.get("sourceGraphVersion") == graph_version):
        return "blocked" if continuation.get("blocked") else "reviewing"
    if action in {"wait", "abort"}:
        return "blocked"
    return "reviewing" if action == "revise" else "reading"


def workspace_review_projection(run) -> dict | None:
    """Project only explicit review facts; never infer progress or issue work."""
    raw = run.execution_state.get("workspaceReview")
    if not isinstance(raw, dict):
        return None
    try:
        result = _WorkspaceReview.model_validate(raw).model_dump(by_alias=True, mode="json", exclude_none=True)
    except ValidationError:
        # An incomplete/stale display payload cannot block authorized Run reads
        # or be presented as completed evidence. Execution state is untouched.
        return None
    # Older writers treated any pending proposal as a live review, even when
    # recovery had moved to another observation. A matching applied wait is an
    # explicit current fact; its old proposal's diagnostic is not its cause.
    state = run.execution_state
    current = ((state.get("planningLoop") or {}).get("current") or {})
    review = state.get("reviewPayload") or {}
    status = getattr(run, "status", None)
    if (getattr(status, "value", status) == "waiting_review"
            and result["status"] == "reviewing" and result["graphVersion"] == state.get("graphVersion")
            and current.get("status") == "applied" and review.get("subjectType") == "planner"
            and review.get("subjectId") == state.get("graphId")
            and current.get("observationId") == review.get("observationId")
            and (current.get("decision") or {}).get("action") == "wait"):
        for round_ in reversed(result["rounds"]):
            if (round_["round"] == result["round"] and round_["graphVersion"] == result["graphVersion"]
                    and round_.get("observationRef") == current.get("observationId")):
                result["status"] = workspace_review_status(round_["action"], round_["observationRef"],
                    result["graphVersion"], state.get("workspaceReviewContinuation"))
                break
    return result


def with_workspace_review(graph: dict | None, run) -> dict | None:
    """Join matching display facts without changing the formal graph snapshot."""
    if graph is None:
        return None
    review = workspace_review_projection(run)
    if review is None or graph.get("graphVersion") != review["graphVersion"]:
        return graph
    return {**graph, "workspaceReview": review}


def workspace_transition_failure(run, display) -> dict | None:
    """Read matching display diagnostics without changing an accepted source."""
    state = run.execution_state
    activation = state.get("graphActivation") or {}
    pending = state.get("workspaceReviewContinuation") or {}
    status = getattr(run.status, "value", run.status)
    if (not activation.get("activationId") or activation.get("executionPermit") is not None
            or not pending.get("observationId") or not isinstance(display, dict)
            or status in {"completed", "failed", "cancelled", "superseded"}):
        return None
    for event in reversed(display.get("events") or ()):
        if not isinstance(event, dict) or not str(event.get("eventType", "")).startswith("workspace.review."):
            continue
        payload = event.get("payload") or {}
        if (payload.get("activationId") != activation["activationId"]
                or payload.get("observationId") != pending["observationId"]
                or payload.get("graphVersion") != state.get("graphVersion")):
            return None
        if event.get("eventType") != "workspace.review.blocked":
            return None
        result = {"kind": "blocked", "status": "blocked", "canApprove": False,
            "message": "自动修订暂时停止，已完成结果已保留",
            "observationId": pending["observationId"],
            "errorCode": str(payload.get("errorCode") or "GRAPH_TRANSITION_REJECTED")}
        for source, target in (("authorityReason", "reason"), ("errorType", "errorType")):
            if isinstance(payload.get(source), str):
                result[target] = payload[source][:500]
        return result
    return None
