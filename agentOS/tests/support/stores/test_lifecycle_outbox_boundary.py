from contracts.workflow import AgentTask, WorkflowRun
from support.stores.memory_workflow_store import MemoryWorkflowStore


def test_run_snapshot_outbox_excludes_execution_bodies() -> None:
    store = MemoryWorkflowStore()
    task = AgentTask(
        taskId="task-1",
        title="Task",
        domain="general",
        intent="execute",
        input={"taskGoal": "Task"},
    )
    store.save_task(task)
    run = WorkflowRun(
        runId="run-1",
        taskId=task.task_id,
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
        input={"secret": "must-not-leave-wkn"},
        output={"body": "must-not-leave-wkn"},
        trace=[],
        executionState={
            "compiledPackageId": "pkg-1",
            "compiledPackageChecksum": "a" * 64,
            "compiledPackageVersion": 2,
            "outputRefs": {"step-1": "artifact:output:1"},
        },
    )

    store.save_run(run)

    event = next(item for item in store.list_outbox() if item["aggregate_id"] == "run-1")
    assert "must-not-leave-wkn" not in event["payload"]
    assert "artifact:output:1" in event["payload"]
    assert '"input"' not in event["payload"]
    assert '"output"' not in event["payload"]
