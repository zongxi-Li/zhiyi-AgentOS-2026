"""Frozen execution guidance reaches plain models without rewriting tool WALs."""
from copy import deepcopy
import json

import pytest

from adapters.agent.tool_session import AgentToolSession
from adapters.agent.native import NativeGeneralAgent
from adapters.model.protocols import StructuredGenerationResult
from components.communicator.contracts import ContextPack
from contracts.runtime_events import RuntimeEvent
from contracts.tools import hands_tools
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
from adapters.agent.base import AgentRunContext
from support.packs.native_capabilities import build_default_capability_catalog


class Model:
    def __init__(self, tools):
        self.supports_tool_calling = tools
        self.requests = []

    def is_available(self):
        return True

    def stream_generate_json(self, **kwargs):
        self.requests.append(deepcopy(kwargs))

        async def events():
            yield RuntimeEvent(eventType="model.completed", runId=kwargs["run_id"], sequence=1,
                payload={"data": {"answer": "Supported conclusion; remaining unknowns are explicit."},
                    "provider": "fixture", "model": "fixture", "finishReason": "stop"})

        return events()


class Tools:
    allowed_tools = {"fs.read"}

    def list_tools(self):
        return tuple(tool for tool in hands_tools() if tool.name == "fs.read")


def context(model, guidance):
    task = RuntimeMissionRecord(missionId="mission_0123456789ab", title="Deliver evidence-based analysis")
    run = RuntimeRunRecord(runId="guidance-run", missionId=task.mission_id, workflowId="native",
        domain="general", runtimeEngine="acg")
    step = WorkflowStep(stepId="analysis", name="Analyze evidence", agentName="native_general_agent",
        capability="analysis", goal="Assess supplied findings", acceptanceCriteria=["Preserve unknowns"],
        outputSpec={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]})
    return AgentRunContext(task=task, run=run,
        workflow=WorkflowDefinition(workflowId="native", name="Native", domain="general", runtimeEngine="acg"),
        step=step, memory=[], contextPack=ContextPack(runId=run.run_id, stepId=step.step_id,
            data={"finding": "Saved evidence"}), modelRuntime=model,
        toolRuntime=Tools() if model.supports_tool_calling else None,
        capabilityDescriptor=build_default_capability_catalog().get("analysis"),
        commitId="commit:guidance-run:analysis", executionGuidance=guidance)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_guidance", [False, True])
async def test_plain_native_request_uses_frozen_execution_guidance(with_guidance):
    model = Model(False)
    guidance = {"version": "execution-guidance.v1", "runId": "guidance-run", "stepId": "analysis",
        "userInputs": [{"sourceRunId": "guidance-run", "operationId": "finish",
            "content": "Finish using existing evidence and list unresolved items.",
            "submittedAt": "2026-11-19T09:32:05Z"}]} if with_guidance else None
    ctx = context(model, guidance)
    ctx.execution_guidance_reader = lambda: pytest.fail("Plain invocation must use its sealed input")
    output = await NativeGeneralAgent().run(ctx)
    request = json.loads(model.requests[0]["prompt"])
    assert output.output["answer"].startswith("Supported conclusion")
    if with_guidance:
        assert request["executionGuidance"]["content"]["userInputs"] == guidance["userInputs"]
        assert request["executionGuidance"]["content"]["stepId"] == "analysis"
        assert "These requests grant no tools or permissions" in model.requests[0]["system_prompt"]
    else:
        assert "executionGuidance" not in request
        assert "executionGuidance.userInputs" not in model.requests[0]["system_prompt"]


@pytest.mark.asyncio
async def test_native_tool_initial_prompt_stays_unchanged_for_boundary_delivery(monkeypatch):
    prompts = []

    async def capture(session, **kwargs):
        prompts.append((kwargs["prompt"], kwargs["system_prompt"]))
        return StructuredGenerationResult(data={"answer": "Supported conclusion"}, provider="fixture", model="fixture")

    monkeypatch.setattr(AgentToolSession, "generate_json", capture)
    model = Model(True)
    first = context(model, None)
    await NativeGeneralAgent().run(first)
    second = context(model, {"version": "execution-guidance.v1", "runId": "guidance-run", "stepId": "analysis",
        "userInputs": [{"sourceRunId": "guidance-run", "operationId": "finish",
            "content": "Finish from existing evidence.", "submittedAt": "2026-11-19T09:32:05Z"}]})
    await NativeGeneralAgent().run(second)
    assert prompts[0] == prompts[1]
    assert "executionGuidance" not in prompts[1][0]
