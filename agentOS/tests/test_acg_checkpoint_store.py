"""SQLite persistence semantics for the fused checkpoint boundary."""

from __future__ import annotations

import pytest

from components.recovery.checkpoint import (
    ACGCheckpointStore,
    CheckpointConflictError,
    ExecutionResumeCommand,
)


def test_checkpoint_store_survives_reopen_and_isolates_runs(tmp_path) -> None:
    db_path = tmp_path / "nested" / "checkpoints.sqlite3"
    first = ACGCheckpointStore(db_path=db_path)
    first.save(run_id="run-a", checkpoint_id="same", state={"completedStepIds": ["one"]})
    first.save(run_id="run-b", checkpoint_id="same", state={"completedStepIds": ["other"]})
    first.close()

    reopened = ACGCheckpointStore(db_path=db_path)
    assert reopened.load(run_id="run-a", checkpoint_id="same") == {"completedStepIds": ["one"]}
    assert reopened.load(run_id="run-b", checkpoint_id="same") == {"completedStepIds": ["other"]}
    reopened.close()


def test_resume_command_round_trips_as_agentos_data() -> None:
    command = ExecutionResumeCommand(runId="run-a", payload={"decision": "approved"})

    assert command.run_id == "run-a"
    assert command.payload == {"decision": "approved"}


def test_checkpoint_store_returns_latest_checkpoint_for_a_run(tmp_path) -> None:
    store = ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3")
    store.save(run_id="run-a", checkpoint_id="first", state={"completedStepIds": ["one"]})
    store.save(run_id="run-a", checkpoint_id="second", state={"completedStepIds": ["one", "two"]})

    checkpoint_id, state = store.load_latest(run_id="run-a")

    assert checkpoint_id == "second"
    assert state == {"completedStepIds": ["one", "two"]}
    store.close()


def test_checkpoint_store_rejects_stale_compare_and_set_version(tmp_path) -> None:
    """并发写入使用版本 CAS，旧版本不得覆盖较新的执行状态。"""
    store = ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3")
    first = store.save(run_id="run-a", state={"completedStepIds": ["one"]})
    assert store.version(run_id="run-a", checkpoint_id=first) == 1

    second = store.save(run_id="run-a", state={"completedStepIds": ["one", "two"]}, expected_version=1)
    assert store.version(run_id="run-a", checkpoint_id=second) == 2

    with pytest.raises(CheckpointConflictError, match="version"):
        store.save(run_id="run-a", state={"completedStepIds": ["stale"]}, expected_version=1)
    store.close()


def test_checkpoint_store_reuses_identical_checkpoint_without_new_version(tmp_path) -> None:
    """同一逻辑检查点重复保存必须复用原版本，恢复重试不能无限制造快照。"""
    store = ACGCheckpointStore(db_path=tmp_path / "checkpoints.sqlite3")
    state = {"runId": "run-a", "completedStepIds": ["one"]}

    first = store.save(run_id="run-a", checkpoint_id="acgckpt_stable", state=state)
    repeated = store.save(
        run_id="run-a",
        checkpoint_id="acgckpt_stable",
        state=state,
        expected_version=1,
    )

    assert repeated == first
    assert store.version(run_id="run-a", checkpoint_id=first) == 1
    assert store.latest_version(run_id="run-a") == 1
    store.close()
