"""Ancestry validation depends on the retained chain, never an arbitrary depth."""
from types import SimpleNamespace

import pytest

from runtime.orchestration.graph_materialization import validate_acceptance_ancestry


def chain(count):
    records = {f"commit:{revision}": SimpleNamespace(commit_id=f"commit:{revision}",
        mission_id="mission", commitment_revision=revision,
        parent_commit_id=f"commit:{revision - 1}" if revision > 1 else None)
        for revision in range(1, count + 1)}
    return records, records[f"commit:{count}"]


def test_valid_history_beyond_the_old_depth_ceiling_is_fully_verified():
    records, head = chain(513)
    reads = []

    def get(key):
        reads.append(key)
        return records.get(key)

    validate_acceptance_ancestry(SimpleNamespace(get=get), head, mission_id="mission")
    assert len(reads) == 512 and reads[-1] == "commit:1"


@pytest.mark.parametrize("damage", ["missing", "mission", "revision", "cycle", "root"])
def test_invalid_history_is_still_rejected_after_the_old_depth_ceiling(damage):
    records, head = chain(513)
    if damage == "missing":
        del records["commit:2"]
    elif damage == "mission":
        records["commit:2"].mission_id = "foreign"
    elif damage == "revision":
        records["commit:2"].commitment_revision = 99
    elif damage == "cycle":
        records["commit:2"].parent_commit_id = "commit:513"
    else:
        records["commit:2"].parent_commit_id = None
    with pytest.raises(ValueError):
        validate_acceptance_ancestry(SimpleNamespace(get=records.get), head, mission_id="mission")
