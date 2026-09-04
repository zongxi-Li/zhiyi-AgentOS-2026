from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from components.scheduler.leases import RedisLeaseCoordinator
from components.scheduler.models import SchedulerUnavailable


class _RedisStub:
    def __init__(self, results: list[int], payload: bytes | None = None) -> None:
        self.results = list(results)
        self.payload = payload
        self.calls: list[tuple] = []

    def eval(self, *args):
        self.calls.append(args)
        return self.results.pop(0)

    def get(self, key):
        self.calls.append(("get", key))
        return self.payload


class _BrokenRedis:
    def eval(self, *args):
        raise ConnectionError("redis unavailable")


def _acquire(coordinator: RedisLeaseCoordinator, *, lease_id: str = "lease-1"):
    return coordinator.acquire(
        lease_id=lease_id,
        resource_id="worker-1",
        capacity=2,
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        slot_count=1,
        ttl=timedelta(seconds=30),
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_redis_coordinator_uses_one_atomic_script_for_allocation() -> None:
    client = _RedisStub([1])
    lease = _acquire(RedisLeaseCoordinator(client))

    assert lease is not None
    assert lease.resource_id == "worker-1"
    assert len(client.calls) == 1
    assert client.calls[0][1] == 4
    assert "HVALS" in client.calls[0][0]
    assert "SET" in client.calls[0][0]


def test_redis_coordinator_returns_existing_idempotent_lease() -> None:
    original = _acquire(RedisLeaseCoordinator(_RedisStub([1])))
    assert original is not None
    client = _RedisStub([2], original.model_dump_json(by_alias=True).encode())

    repeated = _acquire(RedisLeaseCoordinator(client))

    assert repeated == original


def test_redis_coordinator_never_falls_back_when_redis_is_unavailable() -> None:
    with pytest.raises(SchedulerUnavailable, match="SCHEDULER_UNAVAILABLE"):
        _acquire(RedisLeaseCoordinator(_BrokenRedis()))
