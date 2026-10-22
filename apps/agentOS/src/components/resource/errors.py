"""Explicit persistence failures surfaced by ResourcePlane observations."""

from __future__ import annotations


class ResourceObservationPersistenceError(RuntimeError):
    """Resource observation could not be durably persisted."""


class ResourceDatabaseLockedError(ResourceObservationPersistenceError):
    """SQLite lock contention outlived the bounded retry window."""


class ResourceVersionConflictError(ResourceObservationPersistenceError):
    """Observation could not be merged after optimistic-CAS retries."""


class ResourceObservationTimeInvalidError(ValueError):
    """A remote observation claims an implausible future timestamp."""


class ResourceConfigMismatchError(ValueError):
    """A repeated resource registration has a different configuration."""


__all__ = [
    "ResourceConfigMismatchError",
    "ResourceDatabaseLockedError",
    "ResourceObservationPersistenceError",
    "ResourceObservationTimeInvalidError",
    "ResourceVersionConflictError",
]
