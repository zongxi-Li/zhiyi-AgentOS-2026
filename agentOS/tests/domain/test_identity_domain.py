from __future__ import annotations

import pytest

from domain.models import (
    AcgBlueprint,
    Attempt,
    IdentityOwnership,
    RunStatus,
    TaskNode,
    UserTask,
    WorkflowRun,
)


def test_user_task_can_own_multiple_workflow_runs() -> None:
    task = UserTask(userId="user-1", goal="审查软件开发合同")
    blueprint = AcgBlueprint(
        taskId=task.task_id,
        graphId="acg_runtime_graph_1",
        graph={"nodes": [], "edges": []},
    )
    failed = WorkflowRun(
        taskId=task.task_id,
        blueprintId=blueprint.blueprint_id,
        status=RunStatus.FAILED,
    )
    succeeded = WorkflowRun(
        taskId=task.task_id,
        blueprintId=blueprint.blueprint_id,
        status=RunStatus.SUCCEEDED,
    )

    ownership = IdentityOwnership()
    ownership.bind_blueprint(blueprint)
    ownership.bind_run(failed)
    ownership.bind_run(succeeded)

    assert failed.run_id != succeeded.run_id
    assert ownership.runs_for_blueprint(blueprint.blueprint_id) == {
        failed.run_id,
        succeeded.run_id,
    }


def test_task_node_is_distinct_from_runtime_graph_node() -> None:
    task = UserTask(userId="user-1", goal="合同审查")
    node = TaskNode(
        taskId=task.task_id,
        title="识别风险",
        objective="识别所有高风险合同条款",
        metadata={"acgNodeRef": "risk_detect"},
    )

    assert node.node_id.startswith("node_")
    assert node.metadata["acgNodeRef"] != node.node_id


def test_different_tasks_cannot_share_a_run_id() -> None:
    task_one = UserTask(userId="user-1", goal="目标一")
    task_two = UserTask(userId="user-2", goal="目标二")
    blueprint_id = "blueprint_0123456789ab"
    shared_run_id = "run_0123456789ab"
    first = WorkflowRun(
        runId=shared_run_id,
        taskId=task_one.task_id,
        blueprintId=blueprint_id,
    )
    second = WorkflowRun(
        runId=shared_run_id,
        taskId=task_two.task_id,
        blueprintId=blueprint_id,
    )
    ownership = IdentityOwnership()
    ownership.bind_run(first)

    with pytest.raises(ValueError, match="different taskIds"):
        ownership.bind_run(second)


def test_different_runs_cannot_share_an_attempt_id() -> None:
    task = UserTask(userId="user-1", goal="目标")
    blueprint = AcgBlueprint(
        taskId=task.task_id,
        graphId="acg_runtime_graph_1",
        graph={"nodes": [], "edges": []},
    )
    run_one = WorkflowRun(taskId=task.task_id, blueprintId=blueprint.blueprint_id)
    run_two = WorkflowRun(taskId=task.task_id, blueprintId=blueprint.blueprint_id)
    node = TaskNode(taskId=task.task_id, title="节点", objective="完成节点")
    shared_attempt_id = "attempt_0123456789ab"
    first = Attempt(
        attemptId=shared_attempt_id,
        runId=run_one.run_id,
        nodeId=node.node_id,
        attemptNumber=1,
    )
    second = Attempt(
        attemptId=shared_attempt_id,
        runId=run_two.run_id,
        nodeId=node.node_id,
        attemptNumber=1,
    )
    ownership = IdentityOwnership()
    ownership.bind_attempt(first)

    with pytest.raises(ValueError, match="different runIds"):
        ownership.bind_attempt(second)


def test_run_task_must_match_registered_blueprint_task() -> None:
    task_one = UserTask(userId="user-1", goal="目标一")
    task_two = UserTask(userId="user-2", goal="目标二")
    blueprint = AcgBlueprint(
        taskId=task_one.task_id,
        graphId="acg_runtime_graph_1",
        graph={"nodes": [], "edges": []},
    )
    wrong_run = WorkflowRun(
        taskId=task_two.task_id,
        blueprintId=blueprint.blueprint_id,
    )
    ownership = IdentityOwnership()
    ownership.bind_blueprint(blueprint)

    with pytest.raises(ValueError, match="must match"):
        ownership.bind_run(wrong_run)
