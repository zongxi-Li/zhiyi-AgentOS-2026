from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

import app.api.agentos_v2 as agentos_v2
from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from app.security.internal_auth import TrustedUserContext, _trusted_user_context
from components.executor import InMemoryExecutionValueStore
from components.content import SQLiteContentManifestStore
from components.attachments import (
    AttachmentLimits,
    DocumentTextExtractorRegistry,
    InputAttachmentService,
    LocalAttachmentStorage,
    PlainTextExtractor,
)
from components.planner import TaskDecompositionError
from components.resource.auth import build_resource_signature
from components.recovery.checkpoint import ACGCheckpointStore
from components.mission_manager.store import WorkflowRegistry
from contracts.evolution import PolicyMutation, Trajectory
from contracts.content import ContentKind
from contracts.attachments import InputAttachmentStatus
from contracts.resource import (
    DeploymentTier,
    NodeProfile,
    NodeSnapshot,
    ResourceEndpoint,
    ResourceHealthStatus,
    ResourceProfile,
    ResourceSnapshot,
    ResourceType,
)
from contracts.planning import PlannedTask
from contracts.runtime_events import RuntimeEvent
from contracts.workflow import (
    MissionRecordState,
    StepStatus,
    TraceEventType,
    WorkflowDefinition,
    WorkflowProgressPhase,
    WorkflowStatus,
    WorkflowStepDefinition,
)
from runtime import ExecutionRuntime
from runtime.live_events import RuntimeEventBroker
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


class _ContractPlanningLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: dict, **_kwargs) -> dict:
        self.prompts.append(prompt)
        if "primaryGoal" in (schema.get("properties") or {}):
            return {
                "primaryGoal": "审查软件合同并生成风险报告",
                "keyConstraints": [],
                "requiredCapabilities": ["task_understanding", "analysis", "artifact_generation"],
                "expectedArtifacts": [],
                "verificationRequirements": [],
                "estimatedComplexity": "medium",
            }
        return {
            "tasks": [
                {
                    "key": "extract-contract-terms", "title": "提取合同核心条款",
                    "objective": "从用户上传的软件合同提取金额、付款、交付、验收和知识产权条款",
                    "capabilityId": "task_understanding", "acceptanceCriteria": ["覆盖五类核心条款"],
                    "sourceRefs": [], "decompositionRationale": "先理解输入材料", "logicalRole": "source_analysis",
                },
                {
                    "key": "analyze-contract-risks", "title": "分析双方风险与冲突",
                    "objective": "分析甲乙双方风险、条款冲突并给出高中低评级",
                    "capabilityId": "analysis", "acceptanceCriteria": ["双方风险均有评级"],
                    "sourceRefs": ["extract-contract-terms"], "decompositionRationale": "基于条款形成风险结论", "logicalRole": "analysis",
                },
                {
                    "key": "generate-contract-report", "title": "生成最终合同审查报告",
                    "objective": "综合核心条款、风险评级、冲突和修改建议形成最终报告",
                    "capabilityId": "artifact_generation", "acceptanceCriteria": ["生成可交付报告"],
                    "sourceRefs": ["analyze-contract-risks"], "decompositionRationale": "汇总最终交付物", "logicalRole": "final_synthesis",
                },
            ],
            "relations": [
                {"sourceKey": "extract-contract-terms", "targetKey": "analyze-contract-risks", "relationType": "depends_on"},
                {"sourceKey": "analyze-contract-risks", "targetKey": "generate-contract-report", "relationType": "depends_on"},
            ],
        }


class _ContractE2EAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(
            agentName="api-agent",
            domain="general",
            capabilities=["task_understanding", "analysis", "artifact_generation"],
        ))
        self.seen_attachment_ids: list[str] = []
        self.seen_contract_text = False

    async def run(self, context):
        attachment_context = context.task.input.get("attachmentContext") or {}
        documents = attachment_context.get("documents") or []
        self.seen_attachment_ids = [item["attachmentId"] for item in documents]
        self.seen_contract_text = any("800000" in item.get("content", "") for item in documents)
        capability = context.capability_descriptor.capability_id
        if capability == "task_understanding":
            return AgentOutput(output={
                "task_summary": "合同金额 800000 元，签约后 30%，验收后 70%",
                "constraints": [],
            }, summary="核心条款已提取")
        if capability == "analysis":
            return AgentOutput(output={
                "analysis": {
                    "findings": ["默示验收期较短", "知识产权共同所有边界不清"],
                    "assumptions": [], "gaps": [],
                }
            }, summary="双方风险与冲突已分析")
        attachment_ids = list(context.task.input.get("attachmentIds") or [])
        return AgentOutput(output={
            "deliverable": {
                "title": "软件合同审查报告",
                "executiveSummary": "合同存在默示验收和知识产权边界风险。",
                "sections": [{"title": "风险", "content": "建议延长异议期并细化权利范围。", "sourceFields": ["contract.txt"]}],
                "calculations": [], "assumptions": [], "openQuestions": [],
                "sourceRefs": attachment_ids,
            },
            "final_answer": "已生成合同审查报告。",
            "verification": {"status": "passed", "checks": [], "unresolvedGaps": []},
            "artifact": {
                "artifactId": "contract-review", "artifactKey": "final", "type": "run_deliverable",
                "title": "软件合同审查报告", "mediaType": "text/markdown",
                "content": "# 软件合同审查报告\n\n金额 800000 元。高风险：知识产权边界不清。",
                "structuredData": {"sourceAttachmentIds": attachment_ids},
            },
        }, summary="最终合同审查报告已生成")


class _GatedApiAgent(BaseAgent):
    """第一步阻塞在闸门上，为取消端点制造确定性的活跃执行窗口。"""

    def __init__(self, profile: AgentProfile) -> None:
        super().__init__(profile)
        self.arrived = asyncio.Event()
        self.gate = asyncio.Event()

    async def run(self, context):
        if context.step.step_id == "report":
            self.arrived.set()
            await self.gate.wait()
            return AgentOutput(output={"report": _SECRET}, summary="safe report summary")
        return AgentOutput(output={"report": "done"}, summary="done")


def _runtime(tmp_path, *, with_identity: bool = False, agent: BaseAgent | None = None) -> ExecutionRuntime:
    agents = AgentRegistry()
    agents.register(agent or _ApiAgent())
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
    content_manifest_store = None
    if with_identity:
        identity_service = AcgIdentityLifecycleService(
            SQLiteV2Repositories(SQLiteV2Storage(":memory:"))
        )
        content_manifest_store = SQLiteContentManifestStore(tmp_path / "api-content.sqlite3")
        identity_lifecycle = IdentityProjectionBridge(
            identity_service,
            identity_service.repositories,
            content_manifest_store,
        )
    return ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
        checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "api-checkpoints.sqlite3"),
        execution_value_store=InMemoryExecutionValueStore(),
        content_manifest_store=content_manifest_store,
        identity_lifecycle=identity_lifecycle,
    )


def _attach_input_service(runtime: ExecutionRuntime, tmp_path, *, max_file_bytes: int = 1024) -> None:
    service = InputAttachmentService(
        repository=runtime.identity_lifecycle.repositories.input_attachments,
        storage=LocalAttachmentStorage(tmp_path / "attachments"),
        extractors=DocumentTextExtractorRegistry((PlainTextExtractor(),)),
        content_store=runtime.content_manifest_store,
        limits=AttachmentLimits(
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_file_bytes * 2,
            max_context_characters=4096,
        ),
    )
    runtime.attachment_service = service
    runtime.attachment_context_builder = service.context_builder


async def test_v2_run_state_is_reference_only_and_output_requires_owned_reference(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission(
        "API projection must not leak input",
        workflow_id="api-workflow",
        input={"contractText": "PRIVATE-TASK-INPUT"},
    )
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    context_ref = runtime.execution_value_store.put_context_pack(
        run_id=run.run_id,
        step_id="step_1",
        payload={
            "runId": run.run_id,
            "stepId": "step_1",
            "objective": "PRIVATE-TASK-INPUT",
            "stepGoal": "PRIVATE-STEP-GOAL",
            "data": {"private": "PRIVATE-CONTEXT-BODY"},
            "sourceData": {"source_1": {"private": "PRIVATE-SOURCE-BODY"}},
            "sourceStepIds": ["source_1"],
            "evidenceRefs": ["evidence_1"],
            "tokensDelivered": 12,
            "tokensAvailable": 20,
            "savingRatio": 0.4,
            "contractStatus": "valid",
        },
    )
    run.execution_state["contextRefs"] = {"step_1": context_ref}
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

        context = await client.get(f"/agentos/v2/runs/{run.run_id}/context-packs")
        assert context.status_code == 200
        context_body = context.json()
        assert context_body["total"] == 1
        assert context_body["items"][0] == {
            "stepId": "step_1",
            "contextRef": context_ref,
            "available": True,
            "objective": "PRIVATE-TASK-INPUT",
            "stepGoal": "PRIVATE-STEP-GOAL",
            "sourceStepIds": ["source_1"],
            "evidenceRefs": ["evidence_1"],
            "missingFields": [],
            "contractStatus": "valid",
            "tokensDelivered": 12,
            "tokensAvailable": 20,
            "savingRatio": 0.4,
            "fieldCount": 1,
            "sourceCount": 1,
            "dataKeys": ["private"],
            "sourceDataKeys": ["source_1"],
        }
        assert "PRIVATE-CONTEXT-BODY" not in context.text
        assert "PRIVATE-SOURCE-BODY" not in context.text

        trace = await client.get(f"/agentos/v2/runs/{run.run_id}/trace")
        assert trace.status_code == 200
        assert "PRIVATE-PROMPT" not in trace.text
        assert any(event["payload"].get("prompt") == "[redacted]" for event in trace.json()["events"])


async def test_v2_output_uses_identity_access_without_loading_full_runtime_run(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    task = runtime.create_mission(
        "Output lookup must stay lightweight",
        workflow_id="api-workflow",
    )
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    output_ref = run.output["outputRef"]

    def fail_full_run_load(_run_id: str):
        raise AssertionError("output lookup must not deserialize the Runtime Run snapshot")

    monkeypatch.setattr(runtime, "get_status", fail_full_run_load)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        output = await client.get(f"/agentos/v2/runs/{run.run_id}/outputs/{output_ref}")
        assert output.status_code == 200
        assert output.json()["content"] == {"report": _SECRET}
        missing = await client.get(
            f"/agentos/v2/runs/{run.run_id}/outputs/output:{run.run_id}:missing:hash"
        )
        assert missing.status_code == 404


def test_v2_runtime_events_endpoint_streams_http_before_publisher_finishes(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("Runtime event HTTP stream", workflow_id="api-workflow")
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    broker = RuntimeEventBroker()
    monkeypatch.setattr(agentos_v2, "runtime_event_broker", broker)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    def publish_later() -> None:
        time.sleep(0.5)
        broker.publish_from_thread(run.run_id, RuntimeEvent(
            eventType="model.output.delta",
            runId=run.run_id,
            nodeId="report",
            attemptId="attempt-1",
            sequence=0,
            payload={"delta": "live"},
        ))
        time.sleep(0.3)
        broker.publish_from_thread(run.run_id, RuntimeEvent(
            eventType="node.completed",
            runId=run.run_id,
            nodeId="report",
            attemptId="attempt-1",
            sequence=0,
            payload={},
        ))
        broker.publish_from_thread(run.run_id, RuntimeEvent(
            eventType="run.completed",
            runId=run.run_id,
            sequence=0,
            payload={},
        ))

    publisher = threading.Thread(target=publish_later)
    publisher.start()
    received = []
    with TestClient(app) as client:
        with client.stream("GET", f"/agentos/v2/runs/{run.run_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith("event:"):
                    received.append(line.split(":", 1)[1].strip())
            publisher.join(timeout=2)
    publisher.join(timeout=2)
    assert not publisher.is_alive()
    assert received == ["model.output.delta", "node.completed", "run.completed"]
    assert runtime.get_status(run.run_id).status == WorkflowStatus.PENDING


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


async def test_v2_run_list_summary_projects_payload_free_rows(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission(
        "Summary fast path run",
        workflow_id="api-workflow",
        input={"source": "acg"},
    )
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    runtime.workflow_store.save_run(run)

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        summary = await client.get(
            "/agentos/v2/runs",
            params={"summary": "true", "statuses": "running,pending"},
        )
        detail = await client.get("/agentos/v2/runs", params={"summary": "false"})

    assert summary.status_code == 200
    assert summary.json()["total"] == 1
    item = summary.json()["items"][0]
    assert item["runId"] == run.run_id
    assert item["title"] == "Summary fast path run"
    assert item["steps"] == []
    assert item["executionState"] == {}
    assert item["activeStepIds"] == []

    assert detail.status_code == 200
    assert detail.json()["items"][0]["runId"] == run.run_id
    assert len(detail.json()["items"][0]["steps"]) == len(run.steps)


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


async def test_v2_resources_projects_authoritative_profile_and_unknown_health(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.legacy_resource_service.register(
        ResourceProfile(
            resourceId="resource-api",
            resourceType=ResourceType.AGENT,
            capabilities=["report"],
            capacity=2,
        ),
        ResourceSnapshot(
            resourceId="resource-api",
            availableSlots=2,
            utilization=0.0,
            healthStatus=ResourceHealthStatus.UNKNOWN,
        ),
    )
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/agentos/v2/resources")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["profile"]["resourceId"] == "resource-api"
    assert item["profile"]["resourceType"] == "agent"
    assert item["snapshot"]["healthStatus"] == "unknown"
    assert item["health"]["healthy"] is False
    assert item["health"]["status"] == "unknown"
    assert item["snapshot"]["availableSlots"] == 2
    assert "cpu" not in item["snapshot"]["metrics"]
    assert "gpu" not in item["snapshot"]["metrics"]


async def test_v2_remote_resource_observation_updates_health_and_capacity(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.legacy_resource_service.register(
        ResourceProfile(
            resourceId="edge-observe",
            resourceType=ResourceType.WORKER,
            deploymentTier="edge",
            capabilities=["vision.infer"],
            ownerScope="tenant-a",
            executionEndpoint={"protocol": "http", "address": "http://edge-observe:9000"},
        ),
        ResourceSnapshot(
            resourceId="edge-observe",
            availableSlots=0,
            utilization=1.0,
            healthStatus=ResourceHealthStatus.UNKNOWN,
        ),
    )
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    credential = runtime.legacy_resource_service.issue_credential("edge-observe")
    body = json.dumps({
        "availableSlots": 2,
        "observationSequence": 2,
        "utilization": 0.25,
        "latencyMs": 18,
        "observedAt": "2026-09-01T00:00:00Z",
    }, separators=(",", ":")).encode()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    headers = {
        "content-type": "application/json",
        "X-Resource-Credential": credential.credential_id,
        "X-Resource-Timestamp": str(timestamp),
        "X-Resource-Nonce": "api-observation-1",
        "X-Resource-Signature": build_resource_signature(
            credential.secret,
            method="POST",
            path="/agentos/v2/resources/edge-observe/observation",
            timestamp=timestamp,
            nonce="api-observation-1",
            body=body,
        ),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/agentos/v2/resources/edge-observe/observation",
            content=body,
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["health"]["healthy"] is True
    assert response.json()["snapshot"]["availableSlots"] == 2

    stale_body = json.dumps({
        "availableSlots": 0,
        "observationSequence": 1,
        "utilization": 1.0,
        "observedAt": "2026-09-01T00:00:01Z",
    }, separators=(",", ":")).encode()
    stale_timestamp = int(datetime.now(timezone.utc).timestamp())
    stale_nonce = "api-observation-2"
    stale_headers = {
        "content-type": "application/json",
        "X-Resource-Credential": credential.credential_id,
        "X-Resource-Timestamp": str(stale_timestamp),
        "X-Resource-Nonce": stale_nonce,
        "X-Resource-Signature": build_resource_signature(
            credential.secret,
            method="POST",
            path="/agentos/v2/resources/edge-observe/observation",
            timestamp=stale_timestamp,
            nonce=stale_nonce,
            body=stale_body,
        ),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        stale = await client.post(
            "/agentos/v2/resources/edge-observe/observation",
            content=stale_body,
            headers=stale_headers,
        )

    assert stale.status_code == 409
    assert "stale observation" in stale.json()["detail"]


async def test_v2_remote_node_observation_requires_signature_and_strict_sequence(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    issued = runtime.node_service.register_remote(
        NodeProfile(
            nodeId="edge-node-observe",
            deploymentTier=DeploymentTier.EDGE,
            ownerScope="tenant-a",
            gpuMemoryMb=24576,
            modelIds=["vision-large"],
            executionEndpoint=ResourceEndpoint(
                protocol="https",
                address="https://edge-node-observe.example.test/execute",
            ),
        ),
        NodeSnapshot(nodeId="edge-node-observe", observationSequence=0),
    )
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    path = "/agentos/v2/nodes/edge-node-observe/observation"
    body = json.dumps({
        "observationSequence": 1,
        "cpuUtilization": 0.25,
        "gpuUtilization": 0.5,
        "availableMemoryMb": 16384,
        "queuedTasks": 1,
        "latencyMs": 18,
        "observedAt": "2026-09-11T00:00:00Z",
    }, separators=(",", ":")).encode()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    nonce = "node-observation-1"
    headers = {
        "content-type": "application/json",
        "X-Node-Credential-Id": issued.credential_id,
        "X-Node-Timestamp": str(timestamp),
        "X-Node-Nonce": nonce,
        "X-Node-Signature": build_resource_signature(
            issued.secret,
            method="POST",
            path=path,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        ),
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(path, content=body, headers={"content-type": "application/json"})
        accepted = await client.post(path, content=body, headers=headers)
        replay = await client.post(path, content=body, headers=headers)

    assert missing.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["nodeId"] == "edge-node-observe"
    assert accepted.json()["snapshot"]["observationSequence"] == 1
    assert accepted.json()["snapshot"]["availableMemoryMb"] == 16384
    assert accepted.json()["health"]["status"] in {"online", "busy"}
    assert replay.status_code == 409

    same_sequence_body = json.dumps({
        "observationSequence": 1,
        "cpuUtilization": 0.2,
        "gpuUtilization": 0.2,
        "availableMemoryMb": 20000,
        "queuedTasks": 0,
    }, separators=(",", ":")).encode()
    same_timestamp = int(datetime.now(timezone.utc).timestamp())
    same_nonce = "node-observation-2"
    same_headers = {
        "content-type": "application/json",
        "X-Node-Credential-Id": issued.credential_id,
        "X-Node-Timestamp": str(same_timestamp),
        "X-Node-Nonce": same_nonce,
        "X-Node-Signature": build_resource_signature(
            issued.secret,
            method="POST",
            path=path,
            timestamp=same_timestamp,
            nonce=same_nonce,
            body=same_sequence_body,
        ),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        same_sequence = await client.post(path, content=same_sequence_body, headers=same_headers)
        wrong_credential = await client.post(path, content=same_sequence_body, headers={
            "content-type": "application/json",
            "X-Node-Credential-Id": "wrong",
            "X-Node-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "X-Node-Nonce": "node-observation-wrong",
            "X-Node-Signature": "0" * 64,
        })

    assert same_sequence.status_code == 409
    assert "stale observation" in same_sequence.json()["detail"]
    assert wrong_credential.status_code == 401


async def test_v2_resources_projects_registered_nodes_for_legacy_clients(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.node_service.register_remote(
        NodeProfile(
            nodeId="legacy-visible-node",
            deploymentTier=DeploymentTier.EDGE,
            ownerScope="tenant-a",
            modelIds=["vision-large"],
            gpuMemoryMb=24576,
            executionEndpoint=ResourceEndpoint(
                protocol="https",
                address="https://legacy-visible-node.example.test/execute",
            ),
        ),
        NodeSnapshot(
            nodeId="legacy-visible-node",
            observationSequence=1,
            availableMemoryMb=16384,
            latencyMs=17,
        ),
    )
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/agentos/v2/resources")

    assert response.status_code == 200
    projected = next(
        item for item in response.json()["items"]
        if item["profile"]["resourceId"] == "legacy-visible-node"
    )
    assert projected["profile"]["resourceType"] == "worker"
    assert projected["profile"]["deploymentTier"] == "edge"
    assert projected["profile"]["modelIds"] == ["vision-large"]
    assert projected["profile"]["computeCapacity"]["gpuMemoryMb"] == 24576
    assert projected["snapshot"]["availableSlots"] == 1
    assert projected["snapshot"]["latencyMs"] == 17


def _operator_context():
    return _trusted_user_context.set(
        TrustedUserContext(
            user_id="operator-1",
            subject="operator-1",
            role="operator",
            tenant_id="tenant-a",
        )
    )


def _remote_registration_payload() -> dict:
    return {
        "profile": {
            "resourceId": "edge-registered",
            "resourceType": "worker",
            "deploymentTier": "edge",
            "capabilities": ["vision.infer"],
            "ownerScope": "tenant-a",
            "executionEndpoint": {
                "protocol": "https",
                "address": "https://edge-registered.example.test/execute",
            },
        },
        "snapshot": {
            "resourceId": "edge-registered",
            "availableSlots": 1,
            "utilization": 0.0,
            "observationSequence": 0,
        },
    }


async def test_v2_remote_resource_registration_requires_operator_and_returns_one_time_secret(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    body = json.dumps(_remote_registration_payload(), separators=(",", ":")).encode()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post(
            "/agentos/v2/resources/register",
            content=body,
            headers={"content-type": "application/json"},
        )
        assert denied.status_code == 401

        token = _operator_context()
        try:
            response = await client.post(
                "/agentos/v2/resources/register",
                content=body,
                headers={"content-type": "application/json"},
            )
            projection = await client.get("/agentos/v2/resources")
        finally:
            _trusted_user_context.reset(token)

    assert response.status_code == 201
    result = response.json()
    assert result["resourceId"] == "edge-registered"
    assert result["ownerScope"] == "tenant-a"
    assert len(result["secret"]) >= 32
    assert projection.status_code == 200
    assert result["secret"] not in projection.text


async def test_v2_remote_observation_requires_resource_signature_and_rejects_replay(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.legacy_resource_service.register(
        ResourceProfile(
            resourceId="edge-signed-api",
            resourceType=ResourceType.WORKER,
            deploymentTier="edge",
            capabilities=["vision.infer"],
            ownerScope="tenant-a",
            executionEndpoint={"protocol": "https", "address": "https://edge-signed-api.example.test/execute"},
        ),
        ResourceSnapshot(resourceId="edge-signed-api", availableSlots=1, utilization=0.0),
    )
    credential = runtime.legacy_resource_service.issue_credential("edge-signed-api")
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    path = "/agentos/v2/resources/edge-signed-api/observation"
    body = b'{"availableSlots":1,"observationSequence":1,"utilization":0.0}'
    timestamp = int(datetime.now(timezone.utc).timestamp())
    nonce = "signed-api-replay"
    signature = build_resource_signature(
        credential.secret,
        method="POST",
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    headers = {
        "content-type": "application/json",
        "X-Resource-Credential": credential.credential_id,
        "X-Resource-Timestamp": str(timestamp),
        "X-Resource-Nonce": nonce,
        "X-Resource-Signature": signature,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(path, content=body, headers={"content-type": "application/json"})
        first = await client.post(path, content=body, headers=headers)
        replay = await client.post(path, content=body, headers=headers)

    assert missing.status_code == 401
    assert first.status_code == 200
    assert replay.status_code == 409


async def test_v2_remote_observation_rejects_expired_and_wrong_credentials(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.legacy_resource_service.register(
        ResourceProfile(
            resourceId="edge-auth-api",
            resourceType=ResourceType.WORKER,
            deploymentTier="edge",
            capabilities=["vision.infer"],
            ownerScope="tenant-a",
            executionEndpoint={"protocol": "https", "address": "https://edge-auth-api.example.test/execute"},
        ),
        ResourceSnapshot(resourceId="edge-auth-api", availableSlots=1, utilization=0.0),
    )
    credential = runtime.legacy_resource_service.issue_credential("edge-auth-api")
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    path = "/agentos/v2/resources/edge-auth-api/observation"
    body = b'{"availableSlots":1,"observationSequence":1,"utilization":0.0}'
    old_timestamp = int((datetime.now(timezone.utc) - timedelta(minutes=6)).timestamp())
    old_nonce = "expired-api"
    old_signature = build_resource_signature(
        credential.secret,
        method="POST",
        path=path,
        timestamp=old_timestamp,
        nonce=old_nonce,
        body=body,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        expired = await client.post(path, content=body, headers={
            "content-type": "application/json",
            "X-Resource-Credential": credential.credential_id,
            "X-Resource-Timestamp": str(old_timestamp),
            "X-Resource-Nonce": old_nonce,
            "X-Resource-Signature": old_signature,
        })
        wrong = await client.post(path, content=body, headers={
            "content-type": "application/json",
            "X-Resource-Credential": "wrong",
            "X-Resource-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "X-Resource-Nonce": "wrong-credential-api",
            "X-Resource-Signature": "0" * 64,
        })

    assert expired.status_code == 401
    assert wrong.status_code == 401


async def test_v2_remote_resource_auth_distinguishes_unknown_resource_and_owner_scope(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    unknown_path = "/agentos/v2/resources/does-not-exist/observation"
    unknown_headers = {
        "content-type": "application/json",
        "X-Resource-Credential": "missing",
        "X-Resource-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        "X-Resource-Nonce": "unknown-resource",
        "X-Resource-Signature": "0" * 64,
    }
    owner_mismatch = _remote_registration_payload()
    owner_mismatch["profile"]["ownerScope"] = "tenant-b"
    owner_body = json.dumps(owner_mismatch, separators=(",", ":")).encode()
    token = _operator_context()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unknown = await client.post(
                unknown_path,
                content=b'{"availableSlots":1,"observationSequence":1,"utilization":0.0}',
                headers=unknown_headers,
            )
            forbidden = await client.post(
                "/agentos/v2/resources/register",
                content=owner_body,
                headers={"content-type": "application/json"},
            )
    finally:
        _trusted_user_context.reset(token)

    assert unknown.status_code == 404
    assert forbidden.status_code == 403


async def test_v2_remote_resource_credential_rotation_is_scoped_atomic_and_invalidates_old_secret(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.legacy_resource_service.register(
        ResourceProfile(
            resourceId="edge-rotation",
            resourceType=ResourceType.WORKER,
            deploymentTier="edge",
            capabilities=["vision.infer"],
            ownerScope="tenant-a",
            executionEndpoint={"protocol": "https", "address": "https://edge-rotation.example.test/execute"},
        ),
        ResourceSnapshot(resourceId="edge-rotation", availableSlots=1, utilization=0.0),
    )
    previous = runtime.legacy_resource_service.issue_credential("edge-rotation")
    before_profile = runtime.legacy_resource_service.profile("edge-rotation")
    before_snapshot = runtime.legacy_resource_service.snapshot("edge-rotation")
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    path = "/agentos/v2/resources/edge-rotation/credential/rotate"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post(path)
        viewer_token = _trusted_user_context.set(
            TrustedUserContext(user_id="viewer-1", subject="viewer-1", role="viewer", tenant_id="tenant-a")
        )
        try:
            viewer = await client.post(path)
        finally:
            _trusted_user_context.reset(viewer_token)
        wrong_tenant_token = _trusted_user_context.set(
            TrustedUserContext(user_id="operator-2", subject="operator-2", role="operator", tenant_id="tenant-b")
        )
        try:
            wrong_tenant = await client.post(path)
        finally:
            _trusted_user_context.reset(wrong_tenant_token)
        operator_token = _operator_context()
        try:
            rotated_response = await client.post(path)
            rotated_again_response = await client.post(path)
            projection = await client.get("/agentos/v2/resources")
        finally:
            _trusted_user_context.reset(operator_token)

        assert denied.status_code == 401
        assert viewer.status_code == 403
        assert wrong_tenant.status_code == 403

        first_rotated = rotated_response.json()
        second_rotated = rotated_again_response.json()
        assert rotated_response.status_code == 200
        assert rotated_again_response.status_code == 200
        assert first_rotated["credentialId"] != previous.credential_id
        assert first_rotated["secret"] != previous.secret
        assert second_rotated["credentialId"] != first_rotated["credentialId"]
        assert second_rotated["secret"] != first_rotated["secret"]

        body = b'{"availableSlots":1,"observationSequence":1,"utilization":0.0}'
        observation_path = "/agentos/v2/resources/edge-rotation/observation"
        old_nonce = "rotation-old-secret"
        old_timestamp = int(datetime.now(timezone.utc).timestamp())
        old_observation = await client.post(
            observation_path,
            content=body,
            headers={
                "content-type": "application/json",
                "X-Resource-Credential": previous.credential_id,
                "X-Resource-Timestamp": str(old_timestamp),
                "X-Resource-Nonce": old_nonce,
                "X-Resource-Signature": build_resource_signature(
                    previous.secret,
                    method="POST",
                    path=observation_path,
                    timestamp=old_timestamp,
                    nonce=old_nonce,
                    body=body,
                ),
            },
        )
        new_nonce = "rotation-new-secret"
        new_timestamp = int(datetime.now(timezone.utc).timestamp())
        new_observation = await client.post(
            observation_path,
            content=body,
            headers={
                "content-type": "application/json",
                "X-Resource-Credential": second_rotated["credentialId"],
                "X-Resource-Timestamp": str(new_timestamp),
                "X-Resource-Nonce": new_nonce,
                "X-Resource-Signature": build_resource_signature(
                    second_rotated["secret"],
                    method="POST",
                    path=observation_path,
                    timestamp=new_timestamp,
                    nonce=new_nonce,
                    body=body,
                ),
            },
        )

    assert old_observation.status_code == 401
    assert new_observation.status_code == 200
    assert runtime.legacy_resource_service.profile("edge-rotation") == before_profile
    after_snapshot = runtime.legacy_resource_service.snapshot("edge-rotation")
    assert after_snapshot.version == before_snapshot.version + 1
    assert after_snapshot.snapshot.observation_sequence == 1
    item = next(item for item in projection.json()["items"] if item["profile"]["resourceId"] == "edge-rotation")
    assert item["profile"] == before_profile.model_dump(by_alias=True, mode="json")


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


async def test_attachment_api_upload_get_delete_and_limits(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    _attach_input_service(runtime, tmp_path, max_file_bytes=16)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/agentos/v2/attachments",
            files={"file": ("contract.txt", b"payment is 30 percent", "text/plain")},
        )
        assert uploaded.status_code == 413
        unsupported = await client.post(
            "/agentos/v2/attachments",
            files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"

    runtime.attachment_service.limits = AttachmentLimits(
        max_file_bytes=1024,
        max_total_bytes=2048,
        max_context_characters=4096,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/agentos/v2/attachments",
            files={"file": ("contract.txt", b"payment is 30 percent", "text/plain")},
        )
        assert uploaded.status_code == 201
        body = uploaded.json()
        assert body["status"] == "READY"
        assert body["filename"] == "contract.txt"
        assert "storageKey" not in body
        detail = await client.get(f'/agentos/v2/attachments/{body["attachmentId"]}')
        assert detail.status_code == 200
        deleted = await client.delete(f'/agentos/v2/attachments/{body["attachmentId"]}')
        assert deleted.status_code == 204
        assert (await client.get(f'/agentos/v2/attachments/{body["attachmentId"]}')).status_code == 404


async def test_mission_and_run_snapshot_own_ready_attachment_references(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    _attach_input_service(runtime, tmp_path)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            ids = []
            for name, content in (("contract.txt", b"amount 800000"), ("terms.md", b"acceptance after 7 days")):
                response = await client.post(
                    "/agentos/v2/attachments",
                    files={"file": (name, content, "text/plain")},
                )
                assert response.status_code == 201
                ids.append(response.json()["attachmentId"])
            created = await client.post(
                "/agentos/v2/missions",
                json={"title": "Review contract", "workflowId": "api-workflow", "attachmentIds": ids},
            )
            assert created.status_code == 202
            mission_id = created.json()["missionId"]
            run_id = created.json()["runId"]
            repositories = runtime.identity_lifecycle.repositories
            assert [item.attachment_id for item in repositories.input_attachments.list_for_mission(mission_id)] == ids
            for _ in range(100):
                if repositories.input_attachments.list_for_run(run_id):
                    break
                await asyncio.sleep(0.05)
            assert [item.attachment_id for item in repositories.input_attachments.list_for_run(run_id)] == ids
            run = runtime.get_status(run_id)
            assert run.input["attachmentIds"] == ids
            assert len(run.input["materialRefs"]) == 2
            assert "amount 800000" not in json.dumps(run.input)
    finally:
        await coordinator.shutdown()


async def test_mission_fails_closed_for_missing_or_failed_attachment(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    _attach_input_service(runtime, tmp_path)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            missing = await client.post(
                "/agentos/v2/missions",
                json={"title": "Missing", "workflowId": "api-workflow", "attachmentIds": ["att_missing"]},
            )
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "ATTACHMENT_NOT_FOUND"
            parsing = await client.post(
                "/agentos/v2/attachments",
                files={"file": ("parsing.txt", b"still parsing", "text/plain")},
            )
            parsing_id = parsing.json()["attachmentId"]
            runtime.identity_lifecycle.repositories.input_attachments.update_status(
                parsing_id, InputAttachmentStatus.PARSING
            )
            not_ready = await client.post(
                "/agentos/v2/missions",
                json={"title": "Parsing", "workflowId": "api-workflow", "attachmentIds": [parsing_id]},
            )
            assert not_ready.status_code == 409
            assert not_ready.json()["detail"]["code"] == "ATTACHMENT_NOT_READY"
            failed = await client.post(
                "/agentos/v2/attachments",
                files={"file": ("broken.txt", b"text\x00binary", "text/plain")},
            )
            assert failed.status_code == 201
            assert failed.json()["status"] == "FAILED"
            rejected = await client.post(
                "/agentos/v2/missions",
                json={
                    "title": "Failed parse",
                    "workflowId": "api-workflow",
                    "attachmentIds": [failed.json()["attachmentId"]],
                },
            )
            assert rejected.status_code == 422
            assert rejected.json()["detail"]["code"] == "PARSING_FAILED"
    finally:
        await coordinator.shutdown()


async def test_contract_txt_attachment_runs_through_planner_acg_runtime_and_deliverable(tmp_path) -> None:
    agent = _ContractE2EAgent()
    planner_llm = _ContractPlanningLLM()
    runtime = _runtime(tmp_path, with_identity=True, agent=agent)
    _attach_input_service(runtime, tmp_path, max_file_bytes=64 * 1024)
    runtime.set_intent_llm(planner_llm)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    contract = """甲方：星河科技
乙方：知弈软件工作室

合同金额：800000 元。

付款：
签约后支付 30%，验收后支付 70%。

交付：
合同签订后 60 日内完成。

验收：
甲方收到成果后 7 日内未提出书面异议，
视为验收通过。

知识产权：
项目成果由甲乙双方共同所有。
"""
    user_task = """请审查上传的软件合同。

要求：
1. 提取核心条款；
2. 分析甲方风险；
3. 分析乙方风险；
4. 检查条款冲突；
5. 给出高/中/低风险评级；
6. 给出修改建议；
7. 生成最终合同审查报告。"""
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            uploaded = await client.post(
                "/agentos/v2/attachments",
                files={"file": ("contract.txt", contract.encode("utf-8"), "text/plain")},
            )
            assert uploaded.status_code == 201
            attachment_id = uploaded.json()["attachmentId"]
            created = await client.post(
                "/agentos/v2/missions",
                json={
                    "title": "合同审查 E2E",
                    "workflowId": "api-workflow",
                    "attachmentIds": [attachment_id],
                    "input": {
                        "userIntent": user_task,
                        "planningMode": "dynamic",
                        "capabilityProfile": "standard",
                    },
                },
            )
            assert created.status_code == 202
            run_id = created.json()["runId"]
            for _ in range(200):
                run = runtime.get_status(run_id)
                if run.status.value in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.05)
            assert run.status.value == "completed", run.error

        assert any("800000" in prompt and "contract.txt" in prompt for prompt in planner_llm.prompts)
        task_plan = run.execution_state["taskPlan"]
        assert [node["key"] for node in task_plan["nodes"]] == [
            "extract-contract-terms", "analyze-contract-risks", "generate-contract-report"
        ]
        assert run.execution_state["graphId"]
        assert run.execution_state["compiledACGPackage"]["packageId"]
        assert agent.seen_contract_text is True
        assert agent.seen_attachment_ids == [attachment_id]

        repositories = runtime.identity_lifecycle.repositories
        assert [item.attachment_id for item in repositories.input_attachments.list_for_run(run_id)] == [attachment_id]
        deliverable_binding = next(
            item for item in repositories.run_artifact_bindings.list_for_run(run_id)
            if item.artifact_key == "final"
        )
        deliverable = repositories.artifacts.get(deliverable_binding.artifact_id)
        assert deliverable is not None and deliverable.artifact_type == "run_deliverable"
        assert deliverable.metadata["sourceAttachmentIds"] == [attachment_id]
        manifest = runtime.content_manifest_store.get_manifest(deliverable.content_ref)
        assert runtime.content_manifest_store.assemble(manifest.manifest_id).decode("utf-8").startswith("# 软件合同审查报告")
    finally:
        await coordinator.shutdown()


async def test_v2_material_and_resource_projections_preserve_unknown_capacity(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("Resource projection", workflow_id="api-workflow")
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    runtime.trace_store.append(
        run,
        TraceEventType.MODEL_CALLED,
        step_id="report",
        payload={
            "provider": "test-provider",
            "model": "test-model",
            "latencyMs": 125,
            "finishReason": "stop",
            "outputPolicy": "API_CONTROLLED",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 40,
                "reasoning_tokens": 10,
                "cache_read_tokens": 25,
            },
            "capability": {
                "provider": "test-provider",
                "model": "test-model",
                "source": "unknown",
                "features": {},
            },
        },
    )
    runtime.workflow_store.save_run(run)
    artifact = runtime.content_manifest_store.create_manifest(
        kind=ContentKind.ARTIFACT,
        owner_type="run",
        owner_id=run.run_id,
        media_type="text/markdown",
    )
    runtime.content_manifest_store.append_fragment(
        manifest_id=artifact.manifest_id, sequence=0, content=b"# title\n"
    )
    runtime.content_manifest_store.append_fragment(
        manifest_id=artifact.manifest_id, sequence=1, content=b"\n## section\ncomplete"
    )
    artifact = runtime.content_manifest_store.seal_manifest(artifact.manifest_id)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    material_text = "完整材料" * 10000

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/agentos/v2/materials",
            json={"content": material_text, "mediaType": "text/plain"},
        )
        usage = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage")
        calls = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage/calls")
        invalid_cursor = await client.get(
            f"/agentos/v2/runs/{run.run_id}/resource-usage/calls", params={"cursor": "bad"}
        )
        artifacts = await client.get(f"/agentos/v2/runs/{run.run_id}/artifacts")
        fragments = await client.get(
            f"/agentos/v2/runs/{run.run_id}/artifacts/{artifact.manifest_id}/fragments",
            params={"pageSize": 1},
        )
        invalid_fragment_cursor = await client.get(
            f"/agentos/v2/runs/{run.run_id}/artifacts/{artifact.manifest_id}/fragments",
            params={"cursor": "bad"},
        )
        downloaded = await client.get(
            f"/agentos/v2/runs/{run.run_id}/artifacts/{artifact.manifest_id}/download"
        )

    assert created.status_code == 201
    manifest_id = created.json()["manifestId"]
    assert runtime.content_manifest_store.assemble(manifest_id).decode("utf-8") == material_text
    assert usage.status_code == 200
    body = usage.json()
    assert body["capability"].get("contextWindowTokens") is None
    assert body["capability"].get("maxOutputTokens") is None
    assert body["contextPressure"]["peak"] is None
    assert body["contextPressure"]["currentInputTokens"] == 100
    assert body["contextPressure"]["peakInputTokens"] == 100
    assert body["contextPressure"]["contextWindowTokens"] is None
    assert body["contextPressure"]["source"] == "unknown"
    assert body["usage"]["totalTokens"] == 140
    assert body["usage"]["reasoningTokens"] == 10
    assert calls.json()["items"][0]["outputPolicy"] == "api_controlled"
    assert invalid_cursor.status_code == 422
    assert artifacts.json()["items"][0]["checksum"] == artifact.checksum
    assert fragments.json()["nextCursor"] == "1"
    assert invalid_fragment_cursor.status_code == 422
    assert downloaded.content == b"# title\n\n## section\ncomplete"


async def test_v2_resource_projection_returns_context_pressure_details(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("Context pressure projection", workflow_id="api-workflow")
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    for index, input_tokens in enumerate((100, 150)):
        runtime.trace_store.append(
            run,
            TraceEventType.MODEL_CALLED,
            step_id=f"report-{index}",
            payload={
                "provider": "test-provider",
                "model": "test-model",
                "latencyMs": 125,
                "finishReason": "stop",
                "usage": {"input_tokens": input_tokens, "output_tokens": 40},
                "capability": {
                    "provider": "test-provider",
                    "model": "test-model",
                    "source": "adapter_declared",
                    "contextWindowTokens": 200,
                    "features": {},
                },
            },
        )
    runtime.workflow_store.save_run(run)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage")

    assert response.status_code == 200
    pressure = response.json()["contextPressure"]
    assert pressure["current"] == 0.75
    assert pressure["peak"] == 0.75
    assert pressure["currentInputTokens"] == 150
    assert pressure["peakInputTokens"] == 150
    assert pressure["contextWindowTokens"] == 200
    assert pressure["source"] == "usage_derived"


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


async def test_v2_workspace_includes_runtime_only_deferred_runs(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    task = runtime.create_mission("Workspace Run history", workflow_id="api-workflow")
    materialized = await runtime.start(task.mission_id, workflow_id="api-workflow")
    _, deferred = runtime.prepare_run(
        task.mission_id,
        workflow_id="api-workflow",
        defer_acg_planning=True,
    )
    deferred.status = WorkflowStatus.FAILED
    deferred.lifecycle_phase = WorkflowProgressPhase.FAILED
    deferred.error = {
        "code": "interrupted_after_restart",
        "message": "任务因服务重启而中断。",
    }
    runtime.workflow_store.save_run(deferred)

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            projected = await client.get(
                f"/agentos/v2/missions/{task.mission_id}/workspace",
                params={"runId": materialized.run_id},
            )
            runtime_only = await client.get(
                f"/agentos/v2/missions/{task.mission_id}/workspace",
                params={"runId": deferred.run_id},
            )

        assert projected.status_code == 200
        assert {item["runId"] for item in projected.json()["runs"]} == {
            materialized.run_id,
            deferred.run_id,
        }
        deferred_summary = next(
            item for item in projected.json()["runs"] if item["runId"] == deferred.run_id
        )
        assert deferred_summary["status"] == "failed"

        assert runtime_only.status_code == 200
        assert {item["runId"] for item in runtime_only.json()["runs"]} == {
            materialized.run_id,
            deferred.run_id,
        }
        assert any(
            item["code"] == "PLANNING_PROJECTION_PENDING"
            for item in runtime_only.json()["diagnostics"]
        )
    finally:
        runtime.identity_lifecycle.lifecycle_service.close()


async def test_workspace_file_listing_rejects_parent_paths_and_never_falls_back_to_process_cwd(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    mission = runtime.create_mission("Workspace file access")
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            traversal = await client.get(
                f"/agentos/v2/missions/{mission.mission_id}/workspace/files",
                params={"path": "../outside"},
            )
            unavailable = await client.get(
                f"/agentos/v2/missions/{mission.mission_id}/workspace/files",
                params={"path": "."},
            )
        assert traversal.status_code == 400
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "workspace file capability unavailable"
    finally:
        runtime.identity_lifecycle.lifecycle_service.close()


async def test_v2_rerun_creates_another_run_under_same_mission(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    task = runtime.create_mission(
        "Same Mission rerun",
        input={"taskGoal": "original goal", "planningDiversity": "stable"},
        workflow_id="api-workflow",
    )
    source = await runtime.start(task.mission_id, workflow_id="api-workflow")
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    payload = {
        "workflowId": "api-workflow",
        "input": {"taskGoal": "updated run configuration", "planningDiversity": "stable"},
        "clientRequestId": "rerun-request-1",
        "sourceRunId": source.run_id,
        "rerunReason": "current_configuration",
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/agentos/v2/missions/{task.mission_id}/runs",
                json=payload,
            )
            repeated = await client.post(
                f"/agentos/v2/missions/{task.mission_id}/runs",
                json=payload,
            )

        assert created.status_code == 202
        assert repeated.status_code == 202
        body = created.json()
        assert body["missionId"] == task.mission_id
        assert body["runId"] != source.run_id
        assert body["sourceRunId"] == source.run_id
        assert "executionState" not in body
        assert repeated.json()["runId"] == body["runId"]
        rerun = runtime.get_status(body["runId"])
        assert rerun.input["taskGoal"] == "updated run configuration"
        assert rerun.execution_state["parentRunId"] == source.run_id
        assert rerun.execution_state["sourceRunId"] == source.run_id
        assert rerun.execution_state["rerunReason"] == "current_configuration"
        assert len(runtime.workflow_store.list_runs(mission_id=task.mission_id, page_size=20).items) == 2
    finally:
        await coordinator.shutdown()
        runtime.identity_lifecycle.lifecycle_service.close()


async def test_v2_single_step_retry_is_idempotent_and_enqueues_child_run(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("Single failed step retry", workflow_id="api-workflow")
    _, source = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    source.status = WorkflowStatus.FAILED
    source.current_step_id = "report"
    source.steps[0].status = StepStatus.FAILED
    source.steps[0].error = "final node failed"
    runtime.workflow_store.save_run(source)

    coordinator = RunExecutionCoordinator(runtime)
    submitted: list[str] = []
    prepared: list[dict[str, object]] = []

    async def submit(run_id: str) -> None:
        submitted.append(run_id)

    def prepare_retry(**kwargs):
        prepared.append(dict(kwargs))
        child = source.model_copy(deep=True)
        child.run_id = "run_single_step_retry"
        child.status = WorkflowStatus.PENDING
        child.current_step_id = "report"
        child.idempotency_key = kwargs["idempotency_key"]
        child.idempotency_fingerprint = kwargs["idempotency_fingerprint"]
        child.execution_state = {
            "singleStepRetry": {
                "sourceRunId": source.run_id,
                "targetStepId": "report",
                "reusedStepIds": [],
            },
        }
        runtime.workflow_store.save_run(child)
        return child

    monkeypatch.setattr(coordinator, "submit", submit)
    monkeypatch.setattr(runtime, "prepare_single_step_retry", prepare_retry)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    payload = {
        "clientRequestId": "single-step-retry-request",
        "reason": "retry final node",
        "expectedRuntimeRevision": source.runtime_revision,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/agentos/v2/runs/{source.run_id}/steps/report/retry",
            json=payload,
        )
        repeated = await client.post(
            f"/agentos/v2/runs/{source.run_id}/steps/report/retry",
            json=payload,
        )
        current_run_retry = await client.post(
            f"/agentos/v2/runs/{source.run_id}/steps/report/retry",
            json={
                **payload,
                "clientRequestId": "same-run-step-retry-request",
                "mode": "current_run",
            },
        )

    assert created.status_code == 202
    assert repeated.status_code == 202
    assert current_run_retry.status_code == 202
    assert created.json()["runId"] == "run_single_step_retry"
    assert repeated.json()["runId"] == created.json()["runId"]
    assert len(prepared) == 2
    assert prepared[0]["reuse_source_run"] is False
    assert prepared[1]["reuse_source_run"] is True
    assert submitted == ["run_single_step_retry", "run_single_step_retry"]


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
        assert tasks.json()["items"][0]["missionId"] == task.mission_id
        assert tasks.json()["items"][0]["latestRunId"] == run.run_id
        assert tasks.json()["items"][0]["runCount"] == 1
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


async def test_v2_failed_mission_can_be_deleted_and_stale_deleted_rows_are_hidden(tmp_path) -> None:
    runtime = _runtime(tmp_path, with_identity=True)
    task = runtime.create_mission("Failed mission can be deleted", workflow_id="api-workflow")
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    run.status = WorkflowStatus.FAILED
    runtime.workflow_store.save_run(run)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listed = await client.get("/agentos/v2/missions")
            deleted = await client.delete(f"/agentos/v2/missions/{task.mission_id}")
            listed_after_delete = await client.get("/agentos/v2/missions")
            repeated = await client.delete(f"/agentos/v2/missions/{task.mission_id}")

        assert listed.status_code == 200
        assert listed.json()["items"][0]["missionId"] == task.mission_id
        assert listed.json()["items"][0]["latestRunId"] == run.run_id
        assert listed.json()["items"][0]["latestRunStatus"] == "failed"
        assert listed.json()["items"][0]["runCount"] == 1
        assert deleted.status_code == 200
        assert deleted.json()["recordState"] == MissionRecordState.DELETED.value
        assert listed_after_delete.status_code == 200
        assert task.mission_id not in {
            item["missionId"] for item in listed_after_delete.json()["items"]
        }
        assert repeated.status_code == 200
        assert repeated.json()["recordState"] == MissionRecordState.DELETED.value
    finally:
        runtime.identity_lifecycle.lifecycle_service.close()


async def test_v2_cancel_endpoint_stops_active_run_cleanly_and_is_idempotent(tmp_path) -> None:
    """取消端点必须真正终止活跃运行：终态干净收敛，且重复取消保持幂等。"""
    gated = _GatedApiAgent(AgentProfile(agentName="api-agent", domain="general"))
    runtime = _runtime(tmp_path, agent=gated)
    task = runtime.create_mission("cancel endpoint probe", workflow_id="api-workflow")
    _, prepared = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")

    exec_task = asyncio.create_task(runtime.execute_prepared_run(prepared.run_id))
    await asyncio.wait_for(gated.arrived.wait(), timeout=5)

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post("/agentos/v2/runs/run_does_not_exist/cancel")
        assert missing.status_code == 404

        cancelled = await client.post(f"/agentos/v2/runs/{prepared.run_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        # 执行体必须在闸门打开后干净收敛为 CANCELLED，而不是崩溃或继续跑完。
        gated.gate.set()
        result = await asyncio.wait_for(exec_task, timeout=10)
        assert result.status is WorkflowStatus.CANCELLED

        again = await client.post(f"/agentos/v2/runs/{prepared.run_id}/cancel")
        assert again.status_code == 200
        assert again.json()["status"] == "cancelled"

        detail = await client.get(f"/agentos/v2/runs/{prepared.run_id}")
        assert detail.json()["status"] == "cancelled"


async def test_v2_cancel_endpoint_rejects_completed_run_as_conflict(tmp_path) -> None:
    """已完成/被取代的运行不可再取消：端点返回安全的固定冲突提示。"""
    runtime = _runtime(tmp_path)
    task = runtime.create_mission("cancel conflict probe", workflow_id="api-workflow")
    run = await runtime.start(task.mission_id, workflow_id="api-workflow")
    assert run.status is WorkflowStatus.COMPLETED

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/agentos/v2/runs/{run.run_id}/cancel")
        assert response.status_code == 409
        assert response.json()["detail"] == "run cannot be cancelled"

        detail = await client.get(f"/agentos/v2/runs/{run.run_id}")
        assert detail.json()["status"] == "completed"


async def test_resource_usage_declares_model_before_first_call(tmp_path) -> None:
    """零调用阶段资源详情也必须能声明模型与策略（不再显示 API 未声明）。

    历史缺陷：capability 仅从已完成调用的审计投影推导，任务开始时整条资源
    横幅只剩占位符，用户要等到第一个节点跑完才知道用的是什么模型。
    """
    from types import SimpleNamespace

    from contracts.capability import ModelCapabilityEnvelope

    runtime = _runtime(tmp_path)
    envelope = ModelCapabilityEnvelope.unknown(
        provider="deepseek", model="deepseek-v4-flash"
    ).model_copy(update={"max_output_tokens": 384000, "context_window_tokens": 1000000})
    runtime.set_model_runtime(SimpleNamespace(describe_model=lambda: envelope))

    task = runtime.create_mission("declared probe", workflow_id="api-workflow")
    _, run = runtime.prepare_run(task.mission_id, workflow_id="api-workflow")
    assert run.status is WorkflowStatus.PENDING

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage")

    assert response.status_code == 200
    body = response.json()
    assert body["usage"]["callCount"] == 0
    assert body["capability"]["model"] == "deepseek-v4-flash"
    assert body["capability"]["maxOutputTokens"] == 384000
    assert body["capabilitySource"] == "declared"
    assert body["outputPolicy"] == "catalog_default"
