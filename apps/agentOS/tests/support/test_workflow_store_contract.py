"""Contract tests shared by in-memory and SQLite workflow stores."""

from datetime import timedelta
from pathlib import Path
import sqlite3

import pytest

from contracts.workflow import MissionRecordState, RuntimeMissionRecord, RuntimeRunRecord, WorkflowStatus, utc_now
from support.stores.workflow_store import RuntimeRunRecordNotTerminalError
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


@pytest.mark.parametrize(
    "store_factory",
    [
        lambda _: MemoryWorkflowStore(),
        lambda path: SQLiteWorkflowStore(path / "workflow.db"),
    ],
)
def test_store_rejects_run_without_saved_parent_task(store_factory, tmp_path: Path) -> None:
    store = store_factory(tmp_path)
    run = RuntimeRunRecord(
        missionId="mission_000000000003",
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
    )

    with pytest.raises(ValueError, match="workflow run task does not exist"):
        store.save_run(run)


@pytest.mark.parametrize(
    "store_factory",
    [lambda _: MemoryWorkflowStore(), lambda path: SQLiteWorkflowStore(path / "workflow.db")],
)
def test_deferred_planning_placeholder_is_persisted_without_prepared_identity_event(
    store_factory,
    tmp_path: Path,
) -> None:
    store = store_factory(tmp_path)
    mission = RuntimeMissionRecord(missionId="mission_deferred", title="Deferred mission")
    store.save_mission(mission)
    run = RuntimeRunRecord(
        runId="run_deferred",
        missionId=mission.mission_id,
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
        executionState={"planningDeferred": True},
    )

    store.save_run(run)

    assert store.get_run(run.run_id).execution_state["planningDeferred"] is True
    assert not any(
        event["aggregate_id"] == run.run_id
        for event in store.list_outbox()
    )


@pytest.mark.parametrize(
    "store_factory",
    [lambda _: MemoryWorkflowStore(), lambda path: SQLiteWorkflowStore(path / "workflow.db")],
)
def test_mission_record_state_covers_all_runs_without_deleting_history(store_factory, tmp_path: Path) -> None:
    store = store_factory(tmp_path)
    mission = RuntimeMissionRecord(missionId="mission_000000000004", title="Mission")
    store.save_mission(mission)
    for run_id in ("run_000000000004", "run_000000000005"):
        store.save_run(RuntimeRunRecord(
            runId=run_id, missionId=mission.mission_id, workflowId="workflow-1",
            domain="general", runtimeEngine="acg", status=WorkflowStatus.COMPLETED,
        ))

    archived, affected = store.set_mission_record_state(mission.mission_id, MissionRecordState.ARCHIVED)
    assert archived.record_state is MissionRecordState.ARCHIVED
    assert affected == 2
    assert store.list_runs(mission_record_state=MissionRecordState.ACTIVE).total == 0
    assert store.list_runs(mission_record_state=MissionRecordState.ARCHIVED).total == 2
    assert len(store.list_all_runs()) == 2

    restored, _ = store.set_mission_record_state(mission.mission_id, MissionRecordState.ACTIVE)
    assert restored.record_state is MissionRecordState.ACTIVE
    deleted, _ = store.set_mission_record_state(mission.mission_id, MissionRecordState.DELETED)
    assert deleted.record_state is MissionRecordState.DELETED
    assert store.list_runs(mission_record_state=MissionRecordState.ACTIVE).total == 0
    assert len(store.list_all_runs()) == 2
    with pytest.raises(ValueError, match="immutable"):
        store.set_mission_record_state(mission.mission_id, MissionRecordState.ACTIVE)


@pytest.mark.parametrize(
    "store_factory",
    [lambda _: MemoryWorkflowStore(), lambda path: SQLiteWorkflowStore(path / "workflow.db")],
)
def test_mission_record_state_rejects_active_runs(store_factory, tmp_path: Path) -> None:
    store = store_factory(tmp_path)
    mission = RuntimeMissionRecord(missionId="mission_000000000006", title="Mission")
    store.save_mission(mission)
    store.save_run(RuntimeRunRecord(
        runId="run_000000000006", missionId=mission.mission_id, workflowId="workflow-1",
        domain="general", runtimeEngine="acg", status=WorkflowStatus.RUNNING,
    ))
    with pytest.raises(RuntimeRunRecordNotTerminalError):
        store.set_mission_record_state(mission.mission_id, MissionRecordState.ARCHIVED)
    assert store.get_mission(mission.mission_id).record_state is MissionRecordState.ACTIVE


@pytest.mark.parametrize(
    "store_factory",
    [lambda _: MemoryWorkflowStore(), lambda path: SQLiteWorkflowStore(path / "workflow.db")],
)
def test_batch_mission_summary_preserves_latest_count_and_visibility(
    store_factory,
    tmp_path: Path,
) -> None:
    store = store_factory(tmp_path)
    active = RuntimeMissionRecord(missionId="mission_batch_active", title="Active")
    archived = RuntimeMissionRecord(missionId="mission_batch_archived", title="Archived")
    store.save_mission(active)
    store.save_mission(archived)
    store.set_mission_record_state(archived.mission_id, MissionRecordState.ARCHIVED)

    now = utc_now()
    older = RuntimeRunRecord(
        runId="run_batch_older",
        missionId=active.mission_id,
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
        input={
            "authenticatedUserId": "user-a",
            "authenticatedTenantId": "tenant-a",
        },
        updatedAt=now,
    )
    newer = older.model_copy(
        update={
            "run_id": "run_batch_newer",
            "updated_at": now + timedelta(seconds=1),
        }
    )
    other_owner = older.model_copy(
        update={
            "run_id": "run_batch_other_owner",
            "input": {
                "authenticatedUserId": "user-b",
                "authenticatedTenantId": "tenant-a",
            },
        }
    )
    store.save_run(older)
    store.save_run(newer)
    store.save_run(other_owner)

    assert store.list_mission_ids(mission_record_state=MissionRecordState.ACTIVE) == {
        active.mission_id
    }
    summaries = store.list_mission_run_summaries(
        [active.mission_id, archived.mission_id],
        mission_record_state=MissionRecordState.ACTIVE,
        owner_user_id="user-a",
        owner_tenant_id="tenant-a",
    )

    assert summaries[active.mission_id].run_count == 2
    assert summaries[active.mission_id].latest_run is not None
    assert summaries[active.mission_id].latest_run.run_id == newer.run_id
    assert archived.mission_id not in summaries


def test_sqlite_mission_summary_does_not_deserialize_run_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "workflow.db"
    store = SQLiteWorkflowStore(db_path)
    mission = RuntimeMissionRecord(missionId="mission_summary_projection", title="Mission")
    store.save_mission(mission)
    run = RuntimeRunRecord(
        runId="run_summary_projection",
        missionId=mission.mission_id,
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
        status=WorkflowStatus.COMPLETED,
        input={"authenticatedUserId": "user-a"},
    )
    store.save_run(run)

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE runs SET payload = 'not-list-readable' WHERE run_id = ?", (run.run_id,))
        conn.commit()

    summaries = store.list_mission_run_summaries(
        [mission.mission_id],
        mission_record_state=MissionRecordState.ACTIVE,
        owner_user_id="user-a",
    )

    summary = summaries[mission.mission_id]
    assert summary.run_count == 1
    assert summary.latest_run is not None
    assert summary.latest_run.run_id == run.run_id
    assert summary.latest_run.status is WorkflowStatus.COMPLETED


@pytest.mark.parametrize(
    "store_factory",
    [lambda _: MemoryWorkflowStore(), lambda path: SQLiteWorkflowStore(path / "workflow.db")],
)
def test_store_accepts_only_recoverable_acg_control_review_barriers(store_factory, tmp_path: Path) -> None:
    store = store_factory(tmp_path)
    mission = RuntimeMissionRecord(missionId="mission_control_review", title="Mission")
    store.save_mission(mission)
    run = RuntimeRunRecord(
        runId="run_control_review",
        missionId=mission.mission_id,
        workflowId="workflow-control",
        domain="general",
        runtimeEngine="acg",
        status=WorkflowStatus.WAITING_REVIEW,
        currentStepId="ctrl_join",
        acgBlueprint={
            "graphId": "acg-control",
            "nodes": [
                {
                    "nodeId": "ctrl_join",
                    "nodeType": "control",
                    "name": "JOIN",
                    "controlType": "consensus",
                }
            ],
        },
        executionState={
            "checkpointId": "acgckpt_control",
            "reviewPayload": {
                "subjectType": "control",
                "subjectId": "ctrl_join",
                "controlId": "ctrl_join",
                "reasonCode": "CONSENSUS_UNRESOLVED",
            },
        },
    )

    store.save_run(run)
    assert store.get_run(run.run_id).status is WorkflowStatus.WAITING_REVIEW

    invalid = run.model_copy(deep=True)
    invalid.run_id = "run_control_review_invalid"
    invalid.execution_state.pop("checkpointId")
    with pytest.raises(ValueError, match="no checkpoint"):
        store.save_run(invalid)
