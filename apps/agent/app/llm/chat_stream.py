from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field


class ChatStreamEventType(str, Enum):
    HEARTBEAT = "heartbeat"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"
    CONTENT_DELTA = "content_delta"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    EXECUTION_STARTED = "execution_started"
    STDOUT_DELTA = "stdout_delta"
    STDERR_DELTA = "stderr_delta"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_CANCELLED = "execution_cancelled"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"


class ChatStreamEvent(BaseModel):
    event: ChatStreamEventType
    request_id: str
    sequence: int
    data: Dict[str, Any] = Field(default_factory=dict)

    def sse_data(self) -> str:
        return json.dumps(
            {
                "event": self.event.value,
                "requestId": self.request_id,
                "sequence": self.sequence,
                "data": self.data,
            },
            ensure_ascii=False,
        )


__all__ = ["ChatStreamEvent", "ChatStreamEventType"]
