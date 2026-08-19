from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from components.executor import InMemoryExecutionValueStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.task_manager.store import WorkflowRegistry
from contracts.workflow import TraceEventType, WorkflowDefinition, WorkflowStepDefinition
from runtime import WorkflowRuntime
from service.agents import AgentRegistry
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore


_SECRET = "REFERENCE-ONLY-OUTPUT-BODY"


class _ApiAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(agentName="api-agent", domain="general"))

    async def run(self, context):
        return AgentOutput(output={"report": _SECRET}, summary="safe report summary")


def _runtime(tmp_path) -> WorkflowRuntime:
    agents = AgentRegistry()
    agents.register(_ApiAgent())
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="api-workflow",
            name="API workflow",
            domain="general",
            runtimeEngine="acg",
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
    return WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "api-checkpoints.sqlite3"),
        execution_value_store=InMemoryExecutionValueStore(),
    )


async def test_v2_run_state_is_reference_only_and_output_requires_owned_reference(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_task(
        "API projection must not leak input",
        workflow_id="api-workflow",
        input={"contractText": "PRIVATE-TASK-INPUT"},
    )
    run = await runtime.start(task.task_id, workflow_id="api-workflow")
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


async def test_v2_legacy_outputs_are_read_only_and_only_available_without_refs(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_task("Legacy API projection", workflow_id="api-workflow")
    run = await runtime.start(task.task_id, workflow_id="api-workflow")
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


async def test_v2_provenance_falls_back_to_read_only_legacy_snapshot(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_task("Legacy provenance projection", workflow_id="api-workflow")
    _, run = runtime.prepare_run(task.task_id, workflow_id="api-workflow")
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
    task = runtime.create_task("API resources", workflow_id="api-workflow")
    run = await runtime.start(task.task_id, workflow_id="api-workflow")
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
        assert f"/agentos/v2/runs/{{run_id}}/reviews" in paths


async def test_v2_create_run_is_idempotent_and_rejects_fingerprint_conflicts(tmp_path) -> None:
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
            first = await client.post("/agentos/v2/runs", json=payload)
            assert first.status_code == 202
            assert "PRIVATE-CREATE-INPUT" not in first.text

            repeated = await client.post("/agentos/v2/runs", json=payload)
            assert repeated.status_code == 202
            assert repeated.json()["runId"] == first.json()["runId"]

            conflict = await client.post(
                "/agentos/v2/runs",
                json={**payload, "title": "Different request body"},
            )
            assert conflict.status_code == 409
            assert conflict.json() == {"detail": "clientRequestId conflict"}
    finally:
        await coordinator.shutdown()
