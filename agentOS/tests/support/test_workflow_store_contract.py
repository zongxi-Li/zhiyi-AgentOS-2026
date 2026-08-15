"""Contract tests shared by in-memory and SQLite workflow stores."""

from pathlib import Path

import pytest

from contracts.workflow import WorkflowRun
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
    run = WorkflowRun(
        taskId="missing-task",
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
    )

    with pytest.raises(ValueError, match="workflow run task does not exist"):
        store.save_run(run)
