"""Atomic lease coordination adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Protocol

from contracts.resource import ResourceLease


class LeaseCoordinator(Protocol):
    def acquire(
        self,
        *,
        lease_id: str,
        resource_id: str,
        capacity: int,
        run_id: str,
        step_id: str,
        attempt_id: str,
        slot_count: int,
        ttl: timedelta,
        now: datetime,
    ) -> ResourceLease | None: ...

    def release(self, lease_id: str) -> bool: ...


class InMemoryLeaseCoordinator:
    """Deterministic test/local coordinator with an atomic slot critical section."""

    def __init__(self) -> None:
        self._leases: dict[str, ResourceLease] = {}
        self._lock = RLock()

    def acquire(
        self,
        *,
        lease_id: str,
        resource_id: str,
        capacity: int,
        run_id: str,
        step_id: str,
        attempt_id: str,
        slot_count: int = 1,
        ttl: timedelta = timedelta(seconds=60),
        now: datetime | None = None,
    ) -> ResourceLease | None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("lease clock must be timezone-aware")
        if slot_count < 1 or capacity < 1 or ttl <= timedelta(0):
            raise ValueError("capacity, slot_count and ttl must be positive")
        with self._lock:
            self._expire(current)
            existing = self._leases.get(lease_id)
            if existing is not None:
                return existing.model_copy(deep=True)
            active = sum(
                lease.slot_count
                for lease in self._leases.values()
                if lease.resource_id == resource_id and lease.status == "active"
            )
            if active + slot_count > capacity:
                return None
            lease = ResourceLease(
                leaseId=lease_id,
                resourceId=resource_id,
                ownerId=attempt_id,
                runId=run_id,
                stepId=step_id,
                attemptId=attempt_id,
                slotCount=slot_count,
                createdAt=current,
                expiresAt=current + ttl,
            )
            self._leases[lease_id] = lease
            return lease.model_copy(deep=True)

    def release(self, lease_id: str) -> bool:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None or lease.status != "active":
                return False
            self._leases[lease_id] = lease.model_copy(update={"status": "released"})
            return True

    def active_slots(self, resource_id: str, *, now: datetime | None = None) -> int:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            self._expire(current)
            return sum(
                lease.slot_count
                for lease in self._leases.values()
                if lease.resource_id == resource_id and lease.status == "active"
            )

    def _expire(self, now: datetime) -> None:
        for lease_id, lease in tuple(self._leases.items()):
            if lease.status == "active" and lease.expires_at <= now:
                self._leases[lease_id] = lease.model_copy(update={"status": "expired"})


def issue_lease(lease_id: str, resource_id: str, owner_id: str, seconds: int = 60) -> ResourceLease:
    created_at = datetime.now(timezone.utc)
    return ResourceLease(
        leaseId=lease_id,
        resourceId=resource_id,
        ownerId=owner_id,
        createdAt=created_at,
        expiresAt=created_at + timedelta(seconds=max(1, seconds)),
    )


__all__ = ["InMemoryLeaseCoordinator", "LeaseCoordinator", "issue_lease"]
