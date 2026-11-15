"""资源维度最近使用查询（execution_bindings.list_for_resource）的存储契约。"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.identity import new_attempt_id, new_binding_id, new_blueprint_id, new_run_id, new_task_id
from domain.identity_graph import ExecutionBinding, TaskBinding
from domain.models import AcgBlueprint, Attempt, AttemptStatus, Mission, SemanticTask, WorkflowRun
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage


def _seed_run_chain(repositories: SQLiteV2Repositories, *, title: str = "汇总输出") -> tuple[str, str]:
    mission = Mission(userId="user-1", goal="审查合同", metadata={})
    repositories.missions.add(mission)
    task = SemanticTask(
        taskId=new_task_id(),
        missionId=mission.mission_id,
        title=title,
        objective="输出完整活动方案文档",
        semanticTaskKey="artifact-generation",
    )
    repositories.semantic_tasks.add(task)
    blueprint = AcgBlueprint(
        missionId=mission.mission_id,
        graphId="runtime_graph_000000000001",
        graph={"nodes": [{"nodeId": "node_000000000001"}], "edges": []},
    )
    repositories.blueprints.add(blueprint)
    repositories.task_bindings.add(TaskBinding(
        taskId=task.task_id,
        blueprintId=blueprint.blueprint_id,
        acgNodeId="node_000000000001",
    ))
    run = WorkflowRun(
        runId=new_run_id(),
        missionId=mission.mission_id,
        blueprintId=blueprint.blueprint_id,
    )
    repositories.runs.add(run)
    return run.run_id, task.task_id


def _attempt(repositories: SQLiteV2Repositories, *, run_id: str, task_id: str, number: int, status: AttemptStatus) -> str:
    attempt = Attempt(
        attemptId=new_attempt_id(),
        runId=run_id,
        taskId=task_id,
        attemptNumber=number,
        status=status,
        startedAt=datetime(2026, 10, 4, 12, 0, number, tzinfo=timezone.utc),
        finishedAt=datetime(2026, 10, 4, 12, 1, number, tzinfo=timezone.utc),
    )
    repositories.attempts.add(attempt)
    return attempt.attempt_id


def _binding(repositories: SQLiteV2Repositories, *, attempt_id: str, resource_id: str, created_at: datetime) -> None:
    repositories.execution_bindings.add(ExecutionBinding(
        bindingId=new_binding_id(),
        attemptId=attempt_id,
        acgNodeId="node_000000000001",
        resourceId=resource_id,
        agentId="agent_case_intake",
        modelId="runtime-default",
        metadata={"deploymentTier": "local"},
        createdAt=created_at,
    ))


def test_list_for_resource_returns_latest_attempts_first() -> None:
    storage = SQLiteV2Storage(":memory:")
    repositories = SQLiteV2Repositories(storage)
    try:
        run_id, task_id = _seed_run_chain(repositories)
        older = _attempt(repositories, run_id=run_id, task_id=task_id, number=1, status=AttemptStatus.FAILED)
        newer = _attempt(repositories, run_id=run_id, task_id=task_id, number=2, status=AttemptStatus.SUCCEEDED)
        _binding(repositories, attempt_id=older, resource_id="case_intake", created_at=datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc))
        _binding(repositories, attempt_id=newer, resource_id="case_intake", created_at=datetime(2026, 10, 4, 12, 5, tzinfo=timezone.utc))
        other_attempt = _attempt(repositories, run_id=run_id, task_id=task_id, number=3, status=AttemptStatus.SUCCEEDED)
        _binding(repositories, attempt_id=other_attempt, resource_id="other_resource", created_at=datetime(2026, 10, 4, 12, 6, tzinfo=timezone.utc))

        records = repositories.execution_bindings.list_for_resource("case_intake", limit=10)

        assert [record.attempt_id for record in records] == [newer, older]
        assert all(record.run_id == run_id for record in records)
        assert records[0].attempt_status == AttemptStatus.SUCCEEDED.value
        assert records[0].agent_id == "agent_case_intake"

        limited = repositories.execution_bindings.list_for_resource("case_intake", limit=1)
        assert [record.attempt_id for record in limited] == [newer]
    finally:
        storage.close()


def test_list_for_resource_joins_task_title_and_mission() -> None:
    storage = SQLiteV2Storage(":memory:")
    repositories = SQLiteV2Repositories(storage)
    try:
        run_id, task_id = _seed_run_chain(repositories, title="汇总输出")
        attempt_id = _attempt(repositories, run_id=run_id, task_id=task_id, number=1, status=AttemptStatus.SUCCEEDED)
        _binding(repositories, attempt_id=attempt_id, resource_id="native_general_agent", created_at=datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc))

        records = repositories.execution_bindings.list_for_resource("native_general_agent", limit=5)

        assert len(records) == 1
        assert records[0].task_id == task_id
        assert records[0].run_id == run_id
        assert records[0].task_title == "汇总输出"
        assert records[0].semantic_task_key == "artifact-generation"
        assert records[0].mission_id is not None
    finally:
        storage.close()
