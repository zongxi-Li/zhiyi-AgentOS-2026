"""Shared resource-store contract and restart semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from components.resource.store import (
    InMemoryResourceStore,
    SQLiteResourceStore,
    VersionConflict,
)
from contracts.resource import ResourceHealthStatus, ResourceProfile, ResourceSnapshot, ResourceType


def _profile(resource_id: str) -> ResourceProfile:
    return ResourceProfile(
        resourceId=resource_id,
        resourceType=ResourceType.AGENT,
        capabilities=["analyse"],
        domains=["general"],
    )


def _snapshot(resource_id: str, *, slots: int = 1) -> ResourceSnapshot:
    return ResourceSnapshot(
        resourceId=resource_id,
        availableSlots=slots,
        utilization=0.0,
        healthStatus=ResourceHealthStatus.ONLINE,
    )


@pytest.fixture(params=("memory", "sqlite"))
def store(request, tmp_path: Path):
    value = (
        InMemoryResourceStore()
        if request.param == "memory"
        else SQLiteResourceStore(tmp_path / "resources.sqlite3")
    )
    yield value
    close = getattr(value, "close", None)
    if callable(close):
        close()


def test_resource_store_contract_create_get_list_duplicate_and_cas(store) -> None:
    original = _snapshot("b")
    first = store.register(_profile("b"), original)
    store.register(_profile("a"), _snapshot("a"))

    assert first.version == 1
    assert store.get_profile("b").resource_type is ResourceType.AGENT
    assert [item.resource_id for item in store.list_profiles()] == ["a", "b"]
    assert store.register(_profile("b"), original).version == 1

    updated = store.update_snapshot(_snapshot("b", slots=0), expected_version=1)
    assert updated.version == 2
    assert updated.snapshot.available_slots == 0
    scaled = store.update_capacity("b", 4, expected_capacity=1)
    assert scaled.version == 3
    assert scaled.snapshot.available_slots == 3
    assert scaled.snapshot.utilization == 0.25
    assert store.get_profile("b").capacity == 4
    with pytest.raises(VersionConflict):
        store.update_capacity("b", 5, expected_capacity=1)
    with pytest.raises(VersionConflict):
        store.update_snapshot(_snapshot("b"), expected_version=1)
    with pytest.raises(ValueError, match="already registered"):
        store.register(_profile("b").model_copy(update={"capacity": 2}), _snapshot("b"))


def test_sqlite_restart_keeps_profile_but_downgrades_snapshot_health(tmp_path: Path) -> None:
    path = tmp_path / "resources.sqlite3"
    first = SQLiteResourceStore(path)
    first.register(_profile("worker-1"), _snapshot("worker-1"))
    first.close()

    restarted = SQLiteResourceStore(path)
    try:
        assert restarted.get_profile("worker-1") == _profile("worker-1")
        restored = restarted.get_snapshot("worker-1")
        assert restored.version == 1
        assert restored.snapshot.health_status is ResourceHealthStatus.UNKNOWN
    finally:
        restarted.close()
