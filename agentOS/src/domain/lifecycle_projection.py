"""WKN 生命周期事实投影到身份库时使用的持久化日志。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from domain.models import DomainModel, utc_now


class ProjectionEventStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"


class LifecycleProjectionEvent(DomainModel):
    event_id: str = Field(alias="eventId", min_length=1)
    event_type: str = Field(alias="eventType", min_length=1)
    aggregate_id: str = Field(alias="aggregateId", min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = Field(alias="payloadHash", min_length=1)
    status: ProjectionEventStatus = ProjectionEventStatus.PENDING
    attempts: int = Field(default=1, ge=1)
    last_error: str | None = Field(default=None, alias="lastError")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")


__all__ = ["LifecycleProjectionEvent", "ProjectionEventStatus"]
