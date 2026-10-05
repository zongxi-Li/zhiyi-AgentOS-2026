"""Transient runtime events emitted while an ACG model call is running."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class RuntimeEvent(BaseModel):
    """Small, non-persistent envelope shared by ACG, model and SSE projections."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:24]}", alias="eventId")
    event_type: str = Field(alias="eventType", min_length=1)
    run_id: str = Field(alias="runId", min_length=1)
    node_id: str | None = Field(default=None, alias="nodeId")
    attempt_id: str | None = Field(default=None, alias="attemptId")
    sequence: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)


# Live progress is disposable; durable lifecycle events carry references and summaries.
TRANSIENT_RUNTIME_EVENT_TYPES = frozenset({
    "model.output.delta", "model.activity", "planner.model.activity",
    "planner.model.output.delta", "planner.draft.updated",
})


__all__ = ["RuntimeEvent", "TRANSIENT_RUNTIME_EVENT_TYPES"]
