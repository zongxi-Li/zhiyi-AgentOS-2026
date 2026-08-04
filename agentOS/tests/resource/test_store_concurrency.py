"""内存资源快照更新的并发保护测试。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from contracts.resource import ResourceProfile, ResourceSnapshot
from resource.store import InMemoryResourceStore, VersionConflict


def _snapshot(available_slots: int) -> ResourceSnapshot:
    return ResourceSnapshot(
        resourceId="worker",
        availableSlots=available_slots,
        utilization=0.2,
        observedAt=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


def test_concurrent_snapshot_updates_allow_only_one_matching_version():
    """两个更新同时期待版本一时，只能有一个提交为版本二。"""
    store = InMemoryResourceStore()
    store.register(ResourceProfile(resourceId="worker", capabilities=["summarize"]), _snapshot(2))
    barrier = threading.Barrier(2)
    successes: list[int] = []
    conflicts: list[BaseException] = []

    def update(slots: int) -> None:
        barrier.wait()
        try:
            successes.append(store.update_snapshot(_snapshot(slots), expected_version=1).version)
        except VersionConflict as error:
            conflicts.append(error)

    threads = [threading.Thread(target=update, args=(slots,)) for slots in (1, 0)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert successes == [2]
    assert len(conflicts) == 1
    assert store.get_snapshot("worker").version == 2
