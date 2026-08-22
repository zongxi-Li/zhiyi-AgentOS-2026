"""Contract tests shared by in-memory and SQLite workflow stores."""

from pathlib import Path

import pytest

from contracts.workflow import MissionRecordState, RuntimeMissionRecord, RuntimeRunRecord, WorkflowStatus
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
