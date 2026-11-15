from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord
from support.stores.memory_workflow_store import MemoryWorkflowStore


def test_run_snapshot_outbox_excludes_execution_bodies() -> None:
    store = MemoryWorkflowStore()
    task = RuntimeMissionRecord(
        missionId="mission_000000000001",
        title="Task",
        domain="general",
        intent="execute",
        input={"taskGoal": "Task"},
    )
    store.save_mission(task)
    run = RuntimeRunRecord(
        runId="run-1",
        missionId=task.mission_id,
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
        acgBlueprint={"graphId": "graph-1"},
        input={"secret": "must-not-leave-runtime"},
        output={"body": "must-not-leave-runtime"},
        trace=[],
        executionState={
            "compiledPackageId": "pkg-1",
            "compiledPackageChecksum": "a" * 64,
            "compiledPackageVersion": 2,
            "taskPlan": {"steps": [{"stepId": "step-1"}]},
            "taskBindings": [{"stepId": "step-1", "agentId": "agent-1"}],
            "outputRefs": {"step-1": "artifact:output:1"},
        },
    )

    store.save_run(run)

    event = next(item for item in store.list_outbox() if item["aggregate_id"] == "run-1")
    assert "must-not-leave-runtime" not in event["payload"]
    assert "artifact:output:1" in event["payload"]
    assert '"input"' not in event["payload"]
    assert '"output"' not in event["payload"]
