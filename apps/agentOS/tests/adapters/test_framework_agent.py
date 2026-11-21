"""外部 Agent 框架的受控 ACG 节点桥接测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.agent_architecture import AgentArchitectureRegistry, FrameworkAgent
from components.communicator.contracts import ContextPack
from contracts.capability import (
    AgentFramework,
    CapabilityInvocation,
    CapabilityInvocationResult,
    CapabilityKind,
    CapabilityManifest,
)
from contracts.mission_semantic import intent_basis_fingerprint
from contracts.memory import MemoryRecord
from adapters.resource_execution import build_remote_execution_payload
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from service.agents.base import AgentProfile, AgentRunContext


class _FrameworkAdapter:
    def __init__(self) -> None:
        self.invocations: list[CapabilityInvocation] = []

    @property
    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            capabilityId="agent.framework.writer",
            kind=CapabilityKind.AGENT,
            displayName="Framework writer",
            framework=AgentFramework.LANGCHAIN,
            capabilities=["writing"],
        )

    async def execute(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
        self.invocations.append(invocation)
        return CapabilityInvocationResult(
            invocationId=invocation.invocation_id,
            success=True,
            output={"answer": "ok"},
            metadata={"summary": "framework result"},
        )


def _context(*, semantic_basis: bool = False) -> AgentRunContext:
    task = RuntimeMissionRecord(
        missionId="mission_000000000001",
        title="framework",
        intent="write",
        input={"topic": "x"},
    )
    run = RuntimeRunRecord(
        missionId="mission_000000000001",
        workflowId="workflow-1",
        domain="general",
        runtimeEngine="acg",
    )
    workflow = WorkflowDefinition(
        workflowId="workflow-1",
        name="workflow",
        domain="general",
        intent="write",
        runtimeEngine="acg",
    )
    step = WorkflowStep(
        stepId="step-1",
        name="write",
        agentName="framework-writer",
        resolvedInput={"style": "brief"},
    )
    if semantic_basis:
        basis = {
            "basisSchemaVersion": 1,
            "missionId": task.mission_id,
            "sourceType": "SEMANTIC",
            "sourceRevision": 1,
            "commitId": "semantic-commit",
            "objective": "write",
            "constraints": [],
            "sourceReferences": [],
            "sourceStatus": "NOT_APPLICABLE",
            "fingerprintVersion": 1,
        }
        basis["fingerprint"] = intent_basis_fingerprint(basis)
        run.execution_state["missionIntentBasis"] = basis
    return AgentRunContext(
        task=task,
        run=run,
        workflow=workflow,
        step=step,
        memory=[],
        contextPack=ContextPack(
            runId=run.run_id,
            stepId=step.step_id,
            data={"source": "allowed"},
        ),
        commitId="commit:run-1:step-1:0",
    )


def test_framework_agent_remains_a_controlled_acg_node() -> None:
    adapter = _FrameworkAdapter()
    registry = AgentArchitectureRegistry()
    registry.register(adapter)
    agent = FrameworkAgent(
        profile=AgentProfile(
            agentName="framework-writer",
            domain="general",
            capabilities=["writing"],
        ),
        capability_id="agent.framework.writer",
        registry=registry,
    )

    context = _context()
    output = asyncio.run(agent.run(context))

    assert output.output == {"answer": "ok"}
    assert output.summary == "framework result"
    invocation = adapter.invocations[0]
    assert invocation.invocation_id == "commit:run-1:step-1:0"
    assert invocation.input["step"] == {
        "stepId": "step-1",
        "input": {"style": "brief"},
    }
    assert invocation.context == {
        "runId": context.run.run_id,
        "workflowId": "workflow-1",
        "stepId": "step-1",
        "attemptId": "commit:run-1:step-1:0",
        "commitId": "commit:run-1:step-1:0",
    }
    assert "checkpoint" not in invocation.input
    assert "memoryStore" not in invocation.input


@pytest.mark.parametrize("semantic_basis", [False, True])
def test_framework_agent_delivers_each_source_with_conflicting_fields(semantic_basis: bool) -> None:
    adapter = _FrameworkAdapter()
    registry = AgentArchitectureRegistry()
    registry.register(adapter)
    agent = FrameworkAgent(
        profile=AgentProfile(agentName="framework-writer", domain="general"),
        capability_id="agent.framework.writer",
        registry=registry,
    )
    context = _context(semantic_basis=semantic_basis)
    context.attempt_id = "scheduler-attempt"
    context.memory = [MemoryRecord(memoryId="frozen-memory", memoryType="episodic",
        scope="run:" + context.run.run_id, content={"finding": "accepted upstream conclusion"})]
    first_analysis = "仓库原始证据\n" * 10_000
    source_data = {
        "reader-1": {"analysis": first_analysis, "flag": True},
        "reader-2": {"analysis": {"finding": "different conclusion"}, "flag": 1},
    }
    context.context_pack = ContextPack(
        runId=context.run.run_id,
        stepId=context.step.step_id,
        data=source_data["reader-2"],
        sourceData=source_data,
        evidenceRefs=["evidence:reader-1", "evidence:reader-2"],
    )
    context.execution_guidance = {"version": "execution-guidance.v1", "runId": context.run.run_id,
        "stepId": context.step.step_id, "userInputs": [{"sourceRunId": context.run.run_id,
            "operationId": "finalize", "content": "Use existing evidence and submit the deliverable.",
            "submittedAt": "2026-11-19T09:32:05Z"}]}

    asyncio.run(agent.run(context))

    delivered = adapter.invocations[0].input["context"]
    assert delivered["data"] == source_data["reader-2"]
    assert delivered["sourceData"] == source_data
    assert delivered["sourceData"]["reader-1"]["analysis"] == first_analysis
    assert delivered["sourceData"]["reader-1"]["flag"] is True
    assert type(delivered["sourceData"]["reader-2"]["flag"]) is int
    assert delivered["evidenceRefs"] == ["evidence:reader-1", "evidence:reader-2"]
    assert delivered["memory"] == [context.memory[0].model_dump(by_alias=True, mode="json")]
    remote = build_remote_execution_payload(context)
    assert remote["sourceData"] == delivered["sourceData"]
    assert remote["memory"] == delivered["memory"]
    assert remote["executionGuidance"] == delivered["executionGuidance"]
    assert delivered["executionGuidance"]["userInputs"] == context.execution_guidance["userInputs"]
    assert delivered["executionGuidance"]["runId"] == context.run.run_id
    assert delivered["executionGuidance"]["stepId"] == context.step.step_id
    delivered["executionGuidance"]["userInputs"][0]["content"] = "adapter-local change"
    assert context.execution_guidance["userInputs"][0]["content"] == "Use existing evidence and submit the deliverable."
    assert adapter.invocations[0].context["attemptId"] == remote["attemptId"] == "scheduler-attempt"
    delivered["sourceData"]["reader-1"]["flag"] = "changed by framework"
    delivered["memory"][0]["content"]["finding"] = "changed by framework"
    assert context.context_pack.source_data["reader-1"]["flag"] is True
    assert context.memory[0].content["finding"] == "accepted upstream conclusion"


def test_framework_agent_propagates_cancellation() -> None:
    class _CancelledAdapter(_FrameworkAdapter):
        async def execute(self, invocation: CapabilityInvocation) -> CapabilityInvocationResult:
            raise asyncio.CancelledError()

    registry = AgentArchitectureRegistry()
    registry.register(_CancelledAdapter())
    agent = FrameworkAgent(
        profile=AgentProfile(agentName="framework-writer", domain="general"),
        capability_id="agent.framework.writer",
        registry=registry,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.run(_context()))
