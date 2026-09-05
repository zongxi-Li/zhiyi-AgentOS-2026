from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import uvicorn
from fastapi import FastAPI

import app.api.agentos_v2 as agentos_v2
import components.executor.node_runner as node_runner
import runtime.live_events as live_events
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from components.executor import InMemoryExecutionValueStore
from components.mission_manager.store import WorkflowRegistry
from components.recovery.checkpoint import ACGCheckpointStore
from contracts.planning import PlannedTask
from contracts.workflow import (
    WorkflowDefinition,
    WorkflowDefinitionType,
    WorkflowStatus,
    WorkflowStepDefinition,
)
from runtime import ExecutionRuntime
from runtime.app_setup import ApplicationSetup
from runtime.live_events import RuntimeEventBroker
from service.agents import AgentRegistry
from adapters.model.native import NativeGeneralAgent
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _StreamingProviderHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    native_response_chunks = (
        '{"task_summary":"streamed',
        ' native task","constraints":[],"success_criteria":["visible"],'
        '"assumptions":[],"open_questions":[]}',
    )

    @classmethod
    def response_chunks(cls, payload: dict) -> tuple[str, ...]:
        schema = (
            payload.get("response_format", {})
            .get("json_schema", {})
            .get("schema", {})
        )
        required = set(schema.get("required") or [])
        if "primaryGoal" in required:
            value = {
                "primaryGoal": "Understand the streamed task",
                "keyConstraints": [],
                "requiredCapabilities": ["task_understanding"],
                "expectedArtifacts": [],
                "verificationRequirements": [],
                "estimatedComplexity": "simple",
                "domainHint": "general",
                "taskTypeHint": "general",
                "implicitRequirements": [],
                "riskLevel": "normal",
            }
        elif "tasks" in required:
            value = {
                "tasks": [{
                    "key": "understand",
                    "title": "Understand streamed task",
                    "objective": "consume the streamed task understanding result",
                    "capabilityId": "task_understanding",
                    "acceptanceCriteria": ["the streamed result is visible"],
                    "sourceRefs": [],
                    "decompositionRationale": "production streaming E2E",
                    "logicalRole": "task",
                }],
                "relations": [],
            }
        else:
            return cls.native_response_chunks
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        midpoint = max(1, len(serialized) // 2)
        return serialized[:midpoint], serialized[midpoint:]

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        self.requests.append(payload)
        if not payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for index, chunk in enumerate(self.response_chunks(payload)):
            event = {"choices": [{"delta": {"content": chunk}}]}
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
            if index == 0:
                time.sleep(0.3)
        self.wfile.write(
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        )
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, _format: str, *_args) -> None:
        return None


def _model_environment(base_url: str) -> dict[str, str]:
    return {
        "AGENTOS_MODELS": json.dumps([
            {
                "capabilityId": "model.runtime.streaming.e2e",
                "provider": "openai_compatible",
                "models": ["local-streaming-model"],
                "baseUrl": base_url,
                "apiKeyEnv": "LOCAL_STREAMING_KEY",
                "allowInsecure": True,
                "priority": 100,
            }
        ]),
        "LOCAL_STREAMING_KEY": "test-only-key",
    }


def _runtime(tmp_path, model_registry: ModelCompatibilityRegistry) -> ExecutionRuntime:
    native = NativeGeneralAgent()
    agents = AgentRegistry()
    agents.register(native)
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflowId="native-http-streaming-e2e",
            name="Native HTTP streaming E2E",
            domain="general",
            runtimeEngine="acg",
            planningNodes=[PlannedTask(
                key="understand",
                title="Understand streamed task",
                objective="consume the native streaming model",
            )],
            steps=[WorkflowStepDefinition(
                stepId="understand",
                name="Understand streamed task",
                agentName=native.profile.agent_name,
                capability="task_understanding",
            )],
        )
    )
    return ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "native-http-checkpoints.sqlite3"),
        execution_value_store=InMemoryExecutionValueStore(),
        model_registry=model_registry,
    )


def _planner_runtime(tmp_path, model_registry: ModelCompatibilityRegistry) -> ExecutionRuntime:
    native = NativeGeneralAgent()
    agents = AgentRegistry()
    agents.register(native)
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="planner-http-streaming-e2e",
        name="Planner HTTP streaming E2E",
        domain="general",
        runtimeEngine="acg",
        definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP,
        steps=[],
    ))
    return ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "planner-http-checkpoints.sqlite3"),
        execution_value_store=InMemoryExecutionValueStore(),
        model_registry=model_registry,
    )


def _start_http_app(app: FastAPI) -> tuple[uvicorn.Server, threading.Thread, str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "uvicorn did not start"
    socket = server.servers[0].sockets[0]
    port = socket.getsockname()[1]
    return server, thread, f"http://127.0.0.1:{port}"


def test_native_http_provider_to_fastapi_sse_streams_before_node_completion(
    tmp_path, monkeypatch
) -> None:
    asyncio.run(_test_native_http_provider_to_fastapi_sse_streams_before_node_completion(tmp_path, monkeypatch))


async def _test_native_http_provider_to_fastapi_sse_streams_before_node_completion(
    tmp_path, monkeypatch
) -> None:
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _StreamingProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    _StreamingProviderHandler.requests = []

    registry = ModelCompatibilityRegistry()
    setup = ApplicationSetup.from_environment(
        _model_environment(f"http://127.0.0.1:{provider.server_port}/v1"),
        model_registry=registry,
    )
    await setup.start()
    runtime = _runtime(tmp_path, registry)
    runtime.default_model_binding = setup.default_model_binding

    broker = RuntimeEventBroker()
    monkeypatch.setattr(live_events, "runtime_event_broker", broker)
    monkeypatch.setattr(node_runner, "runtime_event_broker", broker)
    monkeypatch.setattr(agentos_v2, "runtime_event_broker", broker)
    import adapters.model.native as native_module

    monkeypatch.setattr(native_module, "runtime_event_broker", broker)

    task = runtime.create_mission(
        "Native HTTP streaming acceptance",
        workflow_id="native-http-streaming-e2e",
        input={"userIntent": "understand this streamed task"},
    )
    _, run = runtime.prepare_run(task.mission_id, workflow_id="native-http-streaming-e2e")
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    server, server_thread, base_url = _start_http_app(app)
    execution = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
    event_types: list[str] = []
    payloads: list[dict] = []
    saw_delta_before_completion = False

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            async with client.stream(
                "GET", f"{base_url}/agentos/v2/runs/{run.run_id}/events"
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                event_type = ""
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                        event_types.append(event_type)
                    elif line.startswith("data:"):
                        payload = json.loads(line.split(":", 1)[1].strip())
                        payloads.append(payload)
                        if event_type == "model.output.delta":
                            status = runtime.get_status(run.run_id)
                            saw_delta_before_completion = status.status is not WorkflowStatus.COMPLETED
                        if event_type == "run.completed":
                            break
        result = await asyncio.wait_for(execution, timeout=10)
        assert result.status is WorkflowStatus.COMPLETED
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        server.should_exit = True
        server_thread.join(timeout=5)
        await setup.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)

    assert _StreamingProviderHandler.requests
    assert _StreamingProviderHandler.requests[0]["stream"] is True
    assert "model.output.delta" in event_types
    assert event_types.index("model.output.delta") < event_types.index("node.completed")
    assert event_types[-1] == "run.completed"
    assert saw_delta_before_completion
    deltas = [
        payload.get("payload", {}).get("delta", "")
        for payload in payloads
        if payload.get("eventType") == "model.output.delta"
    ]
    assert deltas and "task_summary" in "".join(deltas)
    assert all("prompt" not in json.dumps(payload, ensure_ascii=False) for payload in payloads)
    assert run.run_id not in broker._queues


def test_planner_http_provider_to_fastapi_sse_precedes_planner_completion(tmp_path, monkeypatch) -> None:
    asyncio.run(_test_planner_http_provider_to_fastapi_sse_precedes_planner_completion(tmp_path, monkeypatch))


async def _test_planner_http_provider_to_fastapi_sse_precedes_planner_completion(
    tmp_path, monkeypatch
) -> None:
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _StreamingProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    _StreamingProviderHandler.requests = []
    registry = ModelCompatibilityRegistry()
    setup = ApplicationSetup.from_environment(
        _model_environment(f"http://127.0.0.1:{provider.server_port}/v1"),
        model_registry=registry,
    )
    await setup.start()
    runtime = _planner_runtime(tmp_path, registry)
    runtime.default_model_binding = setup.default_model_binding
    runtime.set_intent_llm(RegisteredModelRuntime(
        registry=registry,
        provider="openai_compatible",
        model="local-streaming-model",
    ))

    broker = RuntimeEventBroker()
    monkeypatch.setattr(live_events, "runtime_event_broker", broker)
    monkeypatch.setattr(node_runner, "runtime_event_broker", broker)
    monkeypatch.setattr(agentos_v2, "runtime_event_broker", broker)
    import adapters.model.native as native_module

    monkeypatch.setattr(native_module, "runtime_event_broker", broker)
    task = runtime.create_mission(
        "Planner HTTP streaming acceptance",
        workflow_id="planner-http-streaming-e2e",
        input={
            "userIntent": "understand this task through the planner",
            "usePlanner": True,
            "deterministicIntent": False,
        },
    )
    _, run = runtime.prepare_run(
        task.mission_id,
        workflow_id="planner-http-streaming-e2e",
        defer_acg_planning=True,
    )
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    server, server_thread, base_url = _start_http_app(app)
    execution = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
    event_types: list[str] = []
    payloads: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "GET", f"{base_url}/agentos/v2/runs/{run.run_id}/events"
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                event_type = ""
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                        event_types.append(event_type)
                    elif line.startswith("data:"):
                        payload = json.loads(line.split(":", 1)[1].strip())
                        payloads.append(payload)
                        if event_type == "run.completed":
                            break
        result = await asyncio.wait_for(execution, timeout=15)
        assert result.status is WorkflowStatus.COMPLETED
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        server.should_exit = True
        server_thread.join(timeout=5)
        await setup.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)

    # The first planner.started can be published while the HTTP client is still
    # completing its response handshake; at least one complete model lifecycle
    # must nevertheless be observable on the formal SSE path.
    assert event_types.count("planner.model.started") >= 1
    assert "planner.model.first_token" in event_types
    assert "planner.model.completed" in event_types
    assert "planner.completed" in event_types
    assert event_types.index("planner.model.first_token") < event_types.index("planner.completed")
    assert event_types.index("planner.completed") < event_types.index("node.started")
    assert "planner.model.output.delta" in event_types
    assert all(
        not any(key in json.dumps(payload, ensure_ascii=False) for key in ("prompt", "reasoning", '"data"'))
        for payload in payloads
        if payload.get("eventType", "").startswith("planner.")
    )
    assert len(_StreamingProviderHandler.requests) >= 3
    assert all(request.get("stream") is True for request in _StreamingProviderHandler.requests)
    assert run.run_id not in broker._queues
