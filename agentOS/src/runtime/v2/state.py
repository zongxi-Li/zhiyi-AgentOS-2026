"""新领域对象的最小状态迁移规则。"""

from __future__ import annotations

from enum import Enum

from domain.models import AttemptStatus, RunStatus, UserTaskStatus


_TASK_TRANSITIONS = {
    UserTaskStatus.CREATED: {UserTaskStatus.PLANNING, UserTaskStatus.ARCHIVED},
    UserTaskStatus.PLANNING: {UserTaskStatus.READY, UserTaskStatus.ARCHIVED},
    UserTaskStatus.READY: {UserTaskStatus.RUNNING, UserTaskStatus.ARCHIVED},
    UserTaskStatus.RUNNING: {UserTaskStatus.COMPLETED, UserTaskStatus.READY, UserTaskStatus.ARCHIVED},
    UserTaskStatus.COMPLETED: {UserTaskStatus.ARCHIVED},
    UserTaskStatus.ARCHIVED: set(),
}

_RUN_TRANSITIONS = {
    # A run may fail before its first node starts (for example during graph
    # validation or scheduler preparation), so FAILED is a valid terminal
    # outcome directly from PENDING.
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.SUPERSEDED},
    RunStatus.RUNNING: {RunStatus.FAILED, RunStatus.SUCCEEDED, RunStatus.CANCELLED, RunStatus.SUPERSEDED},
    RunStatus.FAILED: set(),
    RunStatus.SUCCEEDED: set(),
    RunStatus.CANCELLED: set(),
    RunStatus.SUPERSEDED: set(),
}

_ATTEMPT_TRANSITIONS = {
    AttemptStatus.PENDING: {AttemptStatus.RUNNING, AttemptStatus.CANCELLED},
    AttemptStatus.RUNNING: {
        AttemptStatus.FAILED,
        AttemptStatus.SUCCEEDED,
        AttemptStatus.CANCELLED,
    },
    AttemptStatus.FAILED: set(),
    AttemptStatus.SUCCEEDED: set(),
    AttemptStatus.CANCELLED: set(),
}


def require_transition(current: Enum, target: Enum) -> None:
    tables = {
        UserTaskStatus: _TASK_TRANSITIONS,
        RunStatus: _RUN_TRANSITIONS,
        AttemptStatus: _ATTEMPT_TRANSITIONS,
    }
    table = tables.get(type(current))
    if table is None or type(current) is not type(target) or target not in table[current]:
        raise ValueError(f"invalid lifecycle transition: {current.value} -> {target.value}")


__all__ = ["require_transition"]
