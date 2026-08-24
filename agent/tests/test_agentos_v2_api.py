from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from components.executor import InMemoryExecutionValueStore
from components.planner import TaskDecompositionError
from components.recovery.checkpoint import ACGCheckpointStore
from components.mission_manager.store import WorkflowRegistry
from contracts.evolution import PolicyMutation, Trajectory
from contracts.planning import PlannedTask
from contracts.workflow import (
    StepStatus,
    TraceEventType,
    WorkflowDefinition,
    WorkflowProgressPhase,
    WorkflowStatus,
    WorkflowStepDefinition,
)
from runtime import ExecutionRuntime
from runtime.v2 import AcgIdentityLifecycleService, IdentityProjectionBridge
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage


_SECRET = "REFERENCE-ONLY-OUTPUT-BODY"


class _ApiAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(agentName="api-agent", domain="general"))

    async def run(self, context):
        return AgentOutput(output={"report": _SECRET}, summary="safe report summary")


def _runtime(tmp_path, *, with_identity: bool = False) -> ExecutionRuntime:
    agents = AgentRegistry()
    agents.register(_ApiAgent())
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="api-workflow",
            name="API workflow",
            domain="general",
            runtimeEngine="acg",
            planningNodes=[PlannedTask(
                key="report",
                title="report",
                objective="produce the requested report",
            )],
            steps=[
                WorkflowStepDefinition(
                    stepId="report",
                    name="report",
                    agentName="api-agent",
                    outputSpec={
                        "type": "object",
                        "required": ["report"],
                        "properties": {"report": {"type": "string"}},
                    },
                )
            ],
        )
    )
    identity_lifecycle = None
    if with_identity:
        identity_service = AcgIdentityLifecycleService(
            SQLiteV2Repositories(SQLiteV2Storage(":memory:"))
        )
        identity_lifecycle = IdentityProjectionBridge(
            identity_service,
            identity_service.repositories,
        )
    return ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "api-checkpoints.sqlite3"),
        execution_value_store=InMemoryExecutionValueStore(),
        identity_lifecycle=identity_lifecycle,
    )


async def test_v2_run_state_is_reference_only_and_output_requires_owned_reference(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission(
        "API projection must not leak input",
        workflow_id="api-workflow",
        input={"contractText": "PRIVATE-TASK-INPUT"},
    )
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    runtime.trace_store.append(
        run,
        TraceEventType.RUNTIME_EVENT_CLASSIFIED,
        payload={"prompt": "PRIVATE-PROMPT", "safeCode": "classified"},
    )
    runtime.workflow_store.save_run(run)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/agentos/v2/runs/{run.run_id}")
        assert response.status_code == 200
        state_body = response.json()
        serialized = response.text
        assert state_body["title"] == "API projection must not leak input"
        assert state_body["outputRef"] == run.output["outputRef"]
        assert state_body["steps"][0]["outputSummary"] == "safe report summary"
        assert _SECRET not in serialized
        assert "PRIVATE-TASK-INPUT" not in serialized
        assert "input" not in state_body
        assert "output" not in state_body["steps"][0]

        output_ref = state_body["outputRef"]
        output = await client.get(f"/agentos/v2/runs/{run.run_id}/outputs/{output_ref}")
        assert output.status_code == 200
        assert output.json()["content"] == {"report": _SECRET}
        assert (await client.get(f"/agentos/v2/runs/{run.run_id}/outputs/output:other:step:hash")).status_code == 404

        trace = await client.get(f"/agentos/v2/runs/{run.run_id}/trace")
        assert trace.status_code == 200
        assert "PRIVATE-PROMPT" not in trace.text
        assert any(event["payload"].get("prompt") == "[redacted]" for event in trace.json()["events"])


async def test_v2_run_history_applies_all_filters_and_matches_detail_visibility(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    visible_task = runtime.create_mission(
        "Visible ACG run",
        workflow_id="api-workflow",
        input={"source": "acg"},
    )
    _, visible_run = runtime.prepare_run(visible_task.mission_id, workflow_id="api-workflow")
    visible_run.status = WorkflowStatus.WAITING_REVIEW
    visible_run.lifecycle_phase = WorkflowProgressPhase.REVIEW
    visible_run.steps[0].status = StepStatus.WAITING_REVIEW
    visible_run.current_step_id = visible_run.steps[0].step_id
    visible_run.execution_state.update({
        "checkpointId": "acgckpt_api_history",
        "reviewPayload": {"stepId": visible_run.steps[0].step_id},
    })
    runtime.workflow_store.save_run(visible_run)

    hidden_task = runtime.create_mission(
        "Owned by another user",
        workflow_id="api-workflow",
        input={"source": "acg", "authenticatedUserId": "other-user"},
    )
    _, hidden_run = runtime.prepare_run(hidden_task.mission_id, workflow_id="api-workflow")
    runtime.workflow_store.save_run(hidden_run)

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/agentos/v2/runs",
            params={
                "statuses": "running,waiting_review",
                "domain": "general",
                "workflowId": "api-workflow",
                "missionId": visible_task.mission_id,
                "lifecyclePhase": "review",
                "sources": "acg,chat",
                "summary": "true",
            },
        )
        hidden_detail = await client.get(f"/agentos/v2/runs/{hidden_run.run_id}")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["runId"] == visible_run.run_id
    assert response.json()["items"][0]["source"] == "acg"
    assert hidden_detail.status_code == 404


async def test_v2_run_history_does_not_apply_removed_architecture_heuristics(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    current_task = runtime.create_mission(
        "Current architecture run",
        workflow_id="api-workflow",
        input={"source": "acg"},
    )
    _, current_run = runtime.prepare_run(current_task.mission_id, workflow_id="api-workflow")

    legacy_task = runtime.create_mission(
        "Pre-compiled architecture run",
        workflow_id="api-workflow",
        input={"source": "acg"},
    )
    _, legacy_run = runtime.prepare_run(legacy_task.mission_id, workflow_id="api-workflow")
    legacy_run.execution_state.pop("compiledPackageId", None)
    runtime.workflow_store.save_run(legacy_run)

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/agentos/v2/runs",
            params={"sources": "acg"},
        )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {item["runId"] for item in response.json()["items"]} == {
        current_run.run_id,
        legacy_run.run_id,
    }


async def test_v2_projects_scheduling_and_versioned_evolution_without_bodies(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("Scheduling projection", workflow_id="api-workflow")
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    proposal = runtime.evolution_service.propose(
        [
            Trajectory(
                trajectoryId=f"trajectory-{index}",
                task={"domain": "general"},
                outcome={"status": "completed"},
            )
            for index in range(3)
        ],
        PolicyMutation(mutationType="budget_adjustment", target="analysis", value=4096),
    )
    assert proposal is not None
    runtime.evolution_service.approve(proposal, approved_by="reviewer")
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        scheduling = await client.get(f"/agentos/v2/runs/{run.run_id}/scheduling")
        assert scheduling.status_code == 200
        assert scheduling.json()["items"][0]["binding"]["resourceId"] == "api-agent"

        active = await client.get("/agentos/v2/evolution/active")
        assert active.json()["version"] == 1
        history = await client.get("/agentos/v2/evolution/history")
        assert history.json()["total"] == 2
        rolled_back = await client.post(
            "/agentos/v2/evolution/rollback",
            json={"targetVersion": 0, "reviewer": "reviewer"},
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["version"] == 2


async def test_v2_legacy_outputs_are_read_only_and_only_available_without_refs(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("Legacy API projection", workflow_id="api-workflow")
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    run.execution_state.pop("outputRefs", None)
    run.output = {"final_answer": _SECRET}
    run.steps[0].output = {"report": _SECRET}
    runtime.workflow_store.save_run(run)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/agentos/v2/runs/{run.run_id}/legacy-outputs")
        assert response.status_code == 200
        assert response.json()["items"] == [
            {
                "stepId": "report",
                "name": "report",
                "status": "completed",
                "content": {"report": _SECRET},
            }
        ]

        run.execution_state["outputRefs"] = {"report": "output:owned"}
        runtime.workflow_store.save_run(run)
        response = await client.get(f"/agentos/v2/runs/{run.run_id}/legacy-outputs")
        assert response.status_code == 404


async def test_v2_history_config_returns_only_owner_visible_workbench_fields(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission(
        "Historical workbench",
        workflow_id="api-workflow",
        input={
            "taskGoal": "Restore the saved objective",
            "materialText": "Owner-visible material",
            "constraints": ["No external writes"],
            "expectedArtifacts": ["Report"],
            "webSearchEnabled": False,
            "apiKey": _SECRET,
        },
    )
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow", review_mode="human_in_loop")
    run.enabled_plugin_ids = ["kinlin.legal"]
    runtime.workflow_store.save_run(run)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/agentos/v2/runs/{run.run_id}/history-config")

    assert response.status_code == 200
    body = response.json()
    assert body["runId"] == run.run_id
    assert body["title"] == "Historical workbench"
    assert body["reviewMode"] == "human_in_loop"
    assert body["enabledPluginIds"] == ["kinlin.legal"]
    assert body["input"]["taskGoal"] == "Restore the saved objective"
    assert body["input"]["materialText"] == "Owner-visible material"
    assert body["input"]["constraints"] == ["No external writes"]
    assert body["input"]["expectedArtifacts"] == ["Report"]
    assert body["input"]["webSearchEnabled"] is False
    assert _SECRET not in response.text


async def test_v2_provenance_falls_back_to_read_only_legacy_snapshot(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("Legacy provenance projection", workflow_id="api-workflow")
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    run.provenance = {
        "schemaVersion": 2,
        "integrityStatus": "valid",
        "productions": [{"eventId": "prod_000001", "producerStepId": "report", "fieldNames": ["report"]}],
        "consumptions": [{"eventId": "cons_000002", "consumerStepId": "deliver", "tokensAvailable": 100, "tokensDelivered": 40}],
        "interactions": [{"eventId": "int_000003", "interactionId": "int_000003", "consumerStepId": "deliver", "tokensAvailable": 100, "tokensDelivered": 40, "savingRatio": 0.6, "content": _SECRET}],
    }
    runtime.workflow_store.save_run(run)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/agentos/v2/runs/{run.run_id}/provenance")

    assert response.status_code == 200
    assert response.json()["legacy"] is True
    assert response.json()["schemaVersion"] == 2
    assert response.json()["productions"][0]["producerStepId"] == "report"
    assert response.json()["interactions"][0]["savingRatio"] == 0.6
    assert response.json()["interactions"][0]["tokensAvailable"] == 100
    assert _SECRET not in response.text


async def test_v2_graph_provenance_and_checkpoint_are_separate_safe_resources(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("API resources", workflow_id="api-workflow")
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        graph = await client.get(f"/agentos/v2/runs/{run.run_id}/graph")
        assert graph.status_code == 200
        assert graph.json()["nodes"]
        assert "runtimeGraph" not in graph.json()
        assert _SECRET not in graph.text

        provenance = await client.get(f"/agentos/v2/runs/{run.run_id}/provenance")
        assert provenance.status_code == 200
        assert provenance.json()["integrityStatus"] == "valid"
        assert provenance.json()["events"]
        assert _SECRET not in provenance.text

        checkpoints = await client.get(f"/agentos/v2/runs/{run.run_id}/checkpoints")
        assert checkpoints.status_code == 200
        for item in checkpoints.json()["items"]:
            assert set(item) == {"checkpointId", "version", "canResume"}

        paths = app.openapi()["paths"]
        assert "/agentos/v2/runs/{run_id}/reviews" in paths


async def test_v2_create_mission_is_idempotent_and_rejects_fingerprint_conflicts(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    payload = {
        "title": "Create through the application API",
        "workflowId": "api-workflow",
        "clientRequestId": "request-42",
        "input": {"contractText": "PRIVATE-CREATE-INPUT"},
    }

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/agentos/v2/missions", json=payload)
            assert first.status_code == 202
            assert "PRIVATE-CREATE-INPUT" not in first.text

            repeated = await client.post("/agentos/v2/missions", json=payload)
            assert repeated.status_code == 202
            assert repeated.json()["runId"] == first.json()["runId"]

            conflict = await client.post(
                "/agentos/v2/missions",
                json={**payload, "title": "Different request body"},
            )
            assert conflict.status_code == 409
            assert conflict.json() == {"detail": "clientRequestId conflict"}
    finally:
        await coordinator.shutdown()


async def test_v2_create_mission_acknowledges_before_deferred_planning_finishes(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    planning_started = threading.Event()
    release_planning = threading.Event()
    original = runtime._materialize_deferred_acg_run

    def block_planning(run_id: str):
        planning_started.set()
        if not release_planning.wait(timeout=5):
            raise TimeoutError("test did not release deferred planning")
        return original(run_id)

    runtime._materialize_deferred_acg_run = block_planning  # type: ignore[method-assign]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(
                client.post(
                    "/agentos/v2/missions",
                    json={"title": "Deferred planning", "workflowId": "api-workflow"},
                ),
                timeout=1,
            )
        assert response.status_code == 202
        assert await asyncio.to_thread(planning_started.wait, 1)
        prepared = runtime.get_status(response.json()["runId"])
        assert prepared.status is WorkflowStatus.PLANNING
        assert prepared.execution_state["planningDeferred"] is True
    finally:
        release_planning.set()
        await coordinator.shutdown()


async def test_v2_deferred_planning_preserves_identity_projection_alignment(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agentos/v2/missions",
                json={"title": "Deferred identity planning", "workflowId": "api-workflow"},
            )
            assert response.status_code == 202
            run_id = response.json()["runId"]
            for _ in range(200):
                run = runtime.get_status(run_id)
                if run.status in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED}:
                    break
                await asyncio.sleep(0.01)
            assert run.status is WorkflowStatus.COMPLETED

            projected = await client.get(f"/agentos/v2/runs/{run_id}")
            graph = await client.get(f"/agentos/v2/runs/{run_id}/graph")
            health = await client.get("/agentos/v2/identity/health")
        assert projected.status_code == 200
        assert projected.json()["identity"]["blueprintId"].startswith("blueprint_")
        assert graph.status_code == 200
        assert graph.json()["taskBindings"][0]["acgNodeId"] == "report"
        assert health.json()["unappliedEventCount"] == 0
    finally:
        await coordinator.shutdown()
        runtime.identity_lifecycle.lifecycle_service.close()


async def test_v2_deferred_planning_failure_is_classified_without_identity_backlog(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))

    def reject_plan(_run_id: str):
        raise TaskDecompositionError("private planner validation detail")

    runtime._materialize_deferred_acg_run = reject_plan  # type: ignore[method-assign]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agentos/v2/missions",
                json={"title": "Deferred planning failure", "workflowId": "api-workflow"},
            )
            assert response.status_code == 202
            run_id = response.json()["runId"]
            for _ in range(200):
                run = runtime.get_status(run_id)
                if run.status is WorkflowStatus.FAILED:
                    break
                await asyncio.sleep(0.01)
            health = await client.get("/agentos/v2/identity/health")

        assert run.status is WorkflowStatus.FAILED
        assert run.error == {
            "code": "task_decomposition_failed",
            "message": "private planner validation detail",
        }
        assert health.json()["unappliedEventCount"] == 0
        assert not any(
            event["aggregate_id"] == run_id
            for event in runtime.workflow_store.list_outbox()
        )
    finally:
        await coordinator.shutdown()
        runtime.identity_lifecycle.lifecycle_service.close()


async def test_v2_create_mission_surfaces_safe_taskplan_validation_error(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))

    def reject_plan(*_args, **_kwargs):
        raise TaskDecompositionError("private planner validation detail")

    runtime.prepare_run = reject_plan  # type: ignore[method-assign]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agentos/v2/missions",
                json={"title": "Planning contract failure", "workflowId": "api-workflow"},
            )
        assert response.status_code == 422
        assert response.json() == {
            "detail": "ACG task planning validation failed after one repair "
            "(TASK_PLAN_VALIDATION_FAILED)"
        }
        assert "private planner validation detail" not in response.text
    finally:
        await coordinator.shutdown()


async def test_v2_identity_queries_and_graph_read_from_identity_source(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    task = runtime.create_mission("Identity API source", workflow_id="api-workflow")
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    repositories = runtime.identity_lifecycle.repositories
    attempts = repositories.attempts.list_for_run(run.run_id)
    execution = repositories.step_executions.list_for_attempt(
        attempts[0].attempt_id
    )[0]
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            tasks = await client.get("/agentos/v2/missions")
            health = await client.get("/agentos/v2/identity/health")
            detail = await client.get(f"/agentos/v2/missions/{task.mission_id}")
            history = await client.get(f"/agentos/v2/missions/{task.mission_id}/runs")
            projected_run = await client.get(f"/agentos/v2/runs/{run.run_id}")
            graph = await client.get(f"/agentos/v2/runs/{run.run_id}/graph")
            tree = await client.get(
                f"/agentos/v2/runs/{run.run_id}/execution-tree"
            )
            attempt_history = await client.get(
                f"/agentos/v2/runs/{run.run_id}/attempts",
                params={"taskId": attempts[0].task_id},
            )
            attempt = await client.get(
                f"/agentos/v2/attempts/{attempts[0].attempt_id}"
            )
            step = await client.get(
                f"/agentos/v2/step-executions/{execution.step_execution_id}"
            )
            provenance = await client.get(
                f"/agentos/v2/step-executions/{execution.step_execution_id}/provenance"
            )

        assert tasks.status_code == 200
        assert health.json()["status"] == "healthy"
        assert health.json()["unappliedEventCount"] == 0
        assert tasks.json()["source"] == "agentos-v2"
        assert tasks.json()["items"][0]["mission"]["missionId"] == task.mission_id
        assert detail.json()["tasks"][0]["taskId"].startswith("task_")
        assert history.json()["runs"][0]["runId"] == run.run_id
        assert projected_run.json()["identity"]["blueprintId"].startswith("blueprint_")
        assert graph.json()["source"] == "agentos-v2"
        assert graph.json()["blueprintId"].startswith("blueprint_")
        assert graph.json()["taskBindings"][0]["acgNodeId"] == "report"
        assert tree.json()["nodes"][0]["attempts"][0]["attempt"]["attemptId"] == attempts[0].attempt_id
        assert attempt_history.json()["attempts"][0]["attempt"]["attemptId"] == attempts[0].attempt_id
        assert attempt.json()["executionBinding"]["attemptId"] == attempts[0].attempt_id
        assert step.json()["origin"]["mission"]["missionId"] == task.mission_id
        assert provenance.json()["stepExecutionId"] == execution.step_execution_id
    finally:
        runtime.identity_lifecycle.lifecycle_service.close()
