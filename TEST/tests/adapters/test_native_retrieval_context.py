"""Retrieval Agents share admitted input without rewriting legacy model WALs."""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adapters.agent.tool_session import AgentToolSession
from adapters.agent.native import NativeGeneralAgent
from components.communicator.contracts import ContextPack
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.capability import ModelInvocationResponse
from contracts.execution_context import project_execution_context
from contracts.memory import MemoryRecord
from contracts.task_acceptance import frozen_task_acceptance
from contracts.tools import hands_tools
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
from adapters.agent.base import AgentRunContext
from support.packs.native_capabilities import build_default_capability_catalog


class Tools:
    def __init__(self, store):
        self.runtime = SimpleNamespace(execution_value_store=store)

    def list_tools(self):
        return tuple(tool for tool in hands_tools() if tool.name == "fs.read")

    async def execute(self, name, arguments, **kwargs):
        assert name == "knowledge_search", "fixture should never execute workspace tools"
        source = {"citationId": "source:search", "title": "Search", "content": "verified retrieved evidence"}
        return SimpleNamespace(text=json.dumps({"ok": True, "data": {"results": [{"snippet": source["content"]}]}}),
            sources=[SimpleNamespace(citation_id="source:search", public_dict=lambda: source)], tool_executions=[])


class Model:
    supports_tool_calling = True

    def __init__(self):
        self.requests = []

    def describe_model(self):
        return SimpleNamespace(provider="offline", model="fixture")

    async def generate_tool_turn(self, *, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        return ModelInvocationResponse(requestId=kwargs["commit_id"], provider="offline", model="fixture",
            content={"answer": "retrieval complete"}, metadata={"finishReason": "stop"})


def context(store, model, *, version=None, reader_version=None):
    policy = {**({"executionContextVersion": version} if version is not None else {}),
              **({"nestedReadVersion": reader_version} if reader_version is not None else {})}
    acceptance = {"version": 1, "criteria": [{"criterionId": "report", "pointer": "/answer", "operator": "exists"}]}
    task = RuntimeMissionRecord(missionId="mission_0123456789ab", title="Inspect repository evidence",
                                input={"webSearchEnabled": False})
    run = RuntimeRunRecord(runId="run_retrieval", missionId=task.mission_id,
        workflowId="native", domain="general", runtimeEngine="acg",
        input={"taskAcceptance": acceptance}, executionState={"taskAcceptance": acceptance, "private": "RUNTIME-PRIVATE"})
    step = WorkflowStep(stepId="retrieve", name="Retrieve evidence", agentName="native_general_agent",
        capability="information_retrieval", goal="Resolve the current evidence gap",
        acceptanceCriteria=["Preserve every established finding"], sourceRefs=["task:previous"],
        input={"contextPolicy": policy}, resolvedInput={"mustNotAppear": "UNDISPATCHED-INPUT"},
        outputSpec={"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}})
    pack = ContextPack(runId=run.run_id, stepId=step.step_id, data={"finding": "source B conclusion"},
        sourceData={"source-a": {"finding": "source A original\n" * 10_000},
                    "source-b": {"finding": "source B conclusion"}}, evidenceRefs=["evidence:a", "evidence:b"])
    return AgentRunContext(task=task, run=run,
        workflow=WorkflowDefinition(workflowId="native", name="Native", domain="general", runtimeEngine="acg"),
        step=step, contextPack=pack, memory=[MemoryRecord(memoryId="frozen-memory", memoryType="episodic",
            scope="run:" + run.run_id, content={"finding": "accepted remembered conclusion"})],
        toolRuntime=Tools(store), modelRuntime=model,
        capabilityDescriptor=build_default_capability_catalog().get("information_retrieval"),
        commitId="commit:run_retrieval:retrieve:0", attemptId="attempt:retrieve")


@pytest.mark.asyncio
async def test_versioned_retrieval_receives_same_authorized_sources_memory_and_acceptance(tmp_path, monkeypatch):
    store, model = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3"), Model()
    ctx = context(store, model, version=1)
    requests = []
    generate = AgentToolSession.generate_json

    async def capture(session, **kwargs):
        requests.append(json.loads(kwargs["prompt"]))
        return await generate(session, **kwargs)

    monkeypatch.setattr(AgentToolSession, "generate_json", capture)
    try:
        output = await NativeGeneralAgent().run(ctx)
        request = requests[0]
        assert output.output == {"answer": "retrieval complete"}
        assert request["context"] == project_execution_context(ctx)
        assert request["acceptanceCriteria"] == ctx.step.acceptance_criteria
        assert request["sourceRefs"] == ctx.step.source_refs
        assert request["taskAcceptance"] == frozen_task_acceptance(ctx.run).model_dump(by_alias=True, mode="json")
        assert request["retrievalEvidence"]["retrieved_information"] == ["verified retrieved evidence"]
        assert "RUNTIME-PRIVATE" not in json.dumps(request) and "UNDISPATCHED-INPUT" not in json.dumps(request)
        assert model.requests and "accepted remembered conclusion" in json.dumps(model.requests[0])
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_version", [None, 1])
async def test_legacy_retrieval_keeps_exact_prompt_and_existing_model_wal_after_restart(tmp_path, monkeypatch, reader_version):
    database = tmp_path / "values.sqlite3"
    store, model = SQLiteExecutionValueStore(db_path=database), Model()
    prompts = []
    generate = AgentToolSession.generate_json

    async def capture(session, **kwargs):
        prompts.append(kwargs["prompt"])
        return await generate(session, **kwargs)

    monkeypatch.setattr(AgentToolSession, "generate_json", capture)
    ctx = context(store, model, reader_version=reader_version)
    try:
        first = await NativeGeneralAgent().run(ctx)
        payload = json.loads(prompts[0])
        assert set(payload) == {"objective", "stepGoal", "retrievalEvidence"}
        assert prompts[0] == json.dumps({"objective": ctx.task.title, "stepGoal": ctx.step.goal,
            "retrievalEvidence": payload["retrievalEvidence"]}, ensure_ascii=False)
        wal = store.get_tool_value(run_id=ctx.run.run_id, key=ctx.commit_id + ":tools:0:model-turn")
        assert len(model.requests) == 1
    finally:
        store.close()
    reopened = SQLiteExecutionValueStore(db_path=database)
    try:
        restored = context(reopened, model, reader_version=reader_version)
        second = await NativeGeneralAgent().run(restored)
        assert prompts[-1] == prompts[0]
        assert second.output == first.output and len(model.requests) == 1
        assert reopened.get_tool_value(run_id=ctx.run.run_id, key=ctx.commit_id + ":tools:0:model-turn") == wal
    finally:
        reopened.close()
