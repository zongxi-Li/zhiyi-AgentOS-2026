"""SQLite persistence semantics for the fused checkpoint boundary."""

from __future__ import annotations

from components.recovery.checkpoint import ACGCheckpointStore, ExecutionResumeCommand


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
