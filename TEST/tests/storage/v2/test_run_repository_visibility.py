"""Run 仓库软删除可见性：mark_deleted 后列表退场、直达读取保留。"""

from __future__ import annotations

from domain.models import AcgBlueprint, Mission, RunStatus, WorkflowRun
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage


def _seed_run(repositories: SQLiteV2Repositories, *, run_id: str) -> WorkflowRun:
    mission = Mission(userId="user-1", goal="目标计划")
    repositories.missions.add(mission)
    blueprint = AcgBlueprint(missionId=mission.mission_id, graphId="graph-1", graph={"nodes": []})
    repositories.blueprints.add(blueprint)
    run = WorkflowRun(runId=run_id, missionId=mission.mission_id, blueprintId=blueprint.blueprint_id)
    repositories.runs.add(run)
    return run


def test_mark_deleted_hides_run_from_lists_but_keeps_direct_read() -> None:
    with SQLiteV2Storage(":memory:") as storage:
        repositories = SQLiteV2Repositories(storage)
        kept = _seed_run(repositories, run_id="run_a00000000001")
        removed = _seed_run(repositories, run_id="run_b00000000002")

        marked = repositories.runs.mark_deleted(removed.run_id)

        assert marked.metadata["recordState"] == "deleted"
        assert repositories.runs.get(removed.run_id) is not None
        assert [run.run_id for run in repositories.runs.list_for_mission(kept.mission_id)] == [kept.run_id]
        pages = repositories.runs.list_for_missions([kept.mission_id])
        assert [run.run_id for run in pages[kept.mission_id]] == [kept.run_id]


def test_mark_deleted_is_idempotent_merge_and_keeps_other_metadata() -> None:
    with SQLiteV2Storage(":memory:") as storage:
        repositories = SQLiteV2Repositories(storage)
        run = _seed_run(repositories, run_id="run_c00000000003")
        repositories.runs.merge_metadata(run.run_id, {"parentRunId": "run_parent"})

        repositories.runs.mark_deleted(run.run_id)
        repositories.runs.mark_deleted(run.run_id)

        merged = repositories.runs.get(run.run_id)
        assert merged is not None
        assert merged.metadata["recordState"] == "deleted"
        assert merged.metadata["parentRunId"] == "run_parent"
        assert merged.status is RunStatus.PENDING
