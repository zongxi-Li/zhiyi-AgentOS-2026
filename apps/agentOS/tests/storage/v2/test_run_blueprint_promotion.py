"""Blueprint promotion updates only version-owned metadata in one transaction."""
import sqlite3

import pytest

from domain.models import AcgBlueprint
from domain.repository import IdentityConflictError
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage
from test_run_repository_visibility import _seed_run


def prepared(storage):
    repositories = SQLiteV2Repositories(storage)
    run = _seed_run(repositories, run_id="run_a00000000001")
    candidate = AcgBlueprint(missionId=run.mission_id, graphId="graph-1", version=2, graph={"version": 2, "nodes": []})
    repositories.blueprints.add(candidate)
    repositories.runs.merge_metadata(run.run_id, {"taskPlanVersion": 1,
        "compiledPackageChecksum": "old-checksum", "operatorNote": "preserve this", "parentRunId": "run_parent"})
    return repositories, repositories.runs.get(run.run_id), candidate


def test_promotion_merges_planning_metadata_without_relaxing_normal_metadata_immutability():
    with SQLiteV2Storage(":memory:") as storage:
        repositories, before, candidate = prepared(storage)
        promoted = repositories.runs.update_blueprint(before.run_id, candidate.blueprint_id, candidate.version,
            planning_metadata={"taskPlanVersion": 2, "compiledPackageChecksum": "new-checksum"})
        assert promoted.blueprint_id == candidate.blueprint_id and promoted.graph_version == 2
        assert promoted.metadata == {**before.metadata, "taskPlanVersion": 2, "compiledPackageChecksum": "new-checksum"}
        with pytest.raises(IdentityConflictError, match="immutable Run metadata"):
            repositories.runs.merge_metadata(before.run_id, {"taskPlanVersion": 3})


def test_promotion_failure_cannot_leave_new_graph_with_old_metadata():
    with SQLiteV2Storage(":memory:") as storage:
        repositories, before, candidate = prepared(storage)
        with storage.transaction() as conn:
            conn.execute("""CREATE TRIGGER reject_promotion BEFORE UPDATE ON workflow_runs_v2
                WHEN NEW.graph_version = 2 BEGIN SELECT RAISE(ABORT, 'promotion failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="promotion failure"):
            repositories.runs.update_blueprint(before.run_id, candidate.blueprint_id, candidate.version,
                planning_metadata={"taskPlanVersion": 2, "compiledPackageChecksum": "new-checksum"})
        assert repositories.runs.get(before.run_id) == before


def test_promotion_cannot_change_lineage_or_unrelated_metadata():
    with SQLiteV2Storage(":memory:") as storage:
        repositories, before, candidate = prepared(storage)
        with pytest.raises(IdentityConflictError, match="only graph planning metadata"):
            repositories.runs.update_blueprint(before.run_id, candidate.blueprint_id, candidate.version,
                planning_metadata={"parentRunId": "foreign-run"})
        assert repositories.runs.get(before.run_id) == before
