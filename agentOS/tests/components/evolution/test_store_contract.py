from __future__ import annotations

from pathlib import Path

import pytest

from components.evolution.store import (
    EvolutionVersionConflict,
    InMemoryEvolutionStore,
    SQLiteEvolutionStore,
)
from contracts.evolution import EvolutionPolicyVersion


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    value = (
        InMemoryEvolutionStore()
        if request.param == "memory"
        else SQLiteEvolutionStore(tmp_path / "evolution.sqlite3")
    )
    yield value
    close = getattr(value, "close", None)
    if callable(close):
        close()


def test_evolution_store_contract_create_get_list_and_cas(store) -> None:
    created = store.create(
        EvolutionPolicyVersion(
            version=1,
            baseVersion=0,
            proposalIds=["proposal-1"],
            policy={"budget:analysis": 20},
            approvedBy="reviewer",
        ),
        expected_active=0,
    )

    assert created.version == 1
    assert store.active() == created
    assert [item.version for item in store.list_versions()] == [0, 1]
    assert store.get(0).status == "superseded"
    with pytest.raises(EvolutionVersionConflict):
        store.create(
            EvolutionPolicyVersion(version=2, baseVersion=0, policy={}),
            expected_active=0,
        )


def test_sqlite_evolution_store_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "restart.sqlite3"
    first = SQLiteEvolutionStore(path)
    first.create(
        EvolutionPolicyVersion(version=1, baseVersion=0, policy={"route": "stable"}),
        expected_active=0,
    )
    first.close()

    restarted = SQLiteEvolutionStore(path)
    try:
        assert restarted.active().version == 1
        assert restarted.active().policy == {"route": "stable"}
        assert [item.version for item in restarted.list_versions()] == [0, 1]
    finally:
        restarted.close()
