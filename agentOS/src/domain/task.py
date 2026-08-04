"""Domain model for a task aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _normalize_text(value: str | None, *, default: str) -> str:
    normalized = (value or "").strip().lower()
    return normalized or default


def _first_nonblank(preferred: str | None, fallback: str | None, *, default: str) -> str:
    for value in (preferred, fallback):
        normalized = (value or "").strip().lower()
        if normalized:
            return normalized
    return default


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    RETRYING = "retrying"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_TASK_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"planning", "running", "cancelled"},
    "planning": {"running", "failed", "cancelled"},
    "running": {"waiting_review", "retrying", "failed", "completed", "cancelled"},
    "waiting_review": {"running", "retrying", "failed", "completed", "cancelled"},
    "retrying": {"running", "failed", "cancelled"},
    "failed": {"retrying", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


@dataclass
class Task:
    title: str
    domain: str = "general"
    intent: str = "general"
    input: dict[str, object] = field(default_factory=dict)
    security_level: str = "internal"
    priority: str = "normal"
    status: TaskStatus = TaskStatus.PENDING
    recommended_workflow: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    task_id: str = field(default_factory=lambda: new_id("task"))
    role_type: str | None = None
    task_type: str | None = None

    def __post_init__(self) -> None:
        self.title = (self.title or "").strip()
        if not self.title:
            raise ValueError("title is required")
        self.domain = _first_nonblank(self.role_type, self.domain, default="general")
        self.intent = _first_nonblank(self.task_type, self.intent, default="general")
        self.input = dict(self.input or {})
        self.security_level = _normalize_text(self.security_level, default="internal")
        self.priority = _normalize_text(self.priority, default="normal")
        self.status = self.status if isinstance(self.status, TaskStatus) else TaskStatus(str(self.status))
        self.role_type = self.domain
        self.task_type = self.intent

    def assign_workflow(self, workflow_id: str | None) -> None:
        self.recommended_workflow = (workflow_id or "").strip() or None
        self.updated_at = utc_now()

    def transition_to(self, target: TaskStatus | str) -> "Task":
        target_status = target if isinstance(target, TaskStatus) else TaskStatus(str(target))
        if target_status != self.status and target_status.value not in _TASK_TRANSITIONS.get(self.status.value, set()):
            raise ValueError(f"illegal transition: {self.status.value} -> {target_status.value}")
        self.status = target_status
        self.updated_at = utc_now()
        return self
