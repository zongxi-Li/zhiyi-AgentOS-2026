from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adapters.agent_tools import AgentToolSession, supports_agent_tools
from adapters.context_tools import ContextReadTools
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.openai_runtime import OpenAICompatibleRuntime
from components.communicator.broker import CommunicationBroker, CommunicationAccessError, EntropyBudgetExceededError
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from components.communicator.reader import CommunicationReader
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.capability import CapabilityKind, CapabilityManifest
from contracts.request_budget import SupplementalReadBudget


def setup_reader(tmp_path, *, data=None, budget=None, usage=None, store=None):
    store = store or SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    ref = store.put_output(run_id="run", step_id="producer", payload=data or {
        "title": "brief", "details": "Sensitive source, keep the unresolved condition. " * 30,
        "secret": "never authorized"})
    broker = CommunicationBroker(manifest=CommunicationManifest(run_id="run", rules=(
        CommunicationRule(producer_step_id="producer", consumer_step_id="consumer",
                          allowed_fields=("title", "details"), channel="p:c"),)), value_store=store, usage=usage)
    reader = CommunicationReader(broker=broker, run_id="run", consumer_step_id="consumer",
        output_refs={"producer": ref}, max_tokens=None, model_budget=budget or SupplementalReadBudget())
    return store, broker, reader


def context(reader, model=None):
    return SimpleNamespace(communication_reader=reader, tool_runtime=None, model_runtime=model,
        step=SimpleNamespace(input={}, step_id="consumer", name="consumer"),
        run=SimpleNamespace(run_id="run"), commit_id="commit", attempt_id="attempt")


def test_directory_is_permission_scoped_and_contains_no_body_or_reference(tmp_path):
    _, _, reader = setup_reader(tmp_path)
    result = asyncio.run(ContextReadTools(context(reader)).execute("context.list_sources", {}, operation_key="list"))
    wire = result.model_dump_json()
    assert "never authorized" not in wire and "secret" not in wire and "Sensitive source" not in wire
    assert "outputRef" not in wire and "details" in wire and "estimatedTokens" in wire


def test_replay_charges_once_after_restoring_checkpoint_and_conflicts_fail_closed(tmp_path):
    store, broker, reader = setup_reader(tmp_path)
    asyncio.run(reader.read("producer", ["title"], operation_id="read:1"))
    usage = deepcopy(broker.usage_snapshot())
    asyncio.run(reader.read("producer", ["title"], operation_id="read:1"))
    assert broker.usage_snapshot() == usage
    restored = CommunicationBroker(manifest=broker.manifest, value_store=store, usage=usage)
    reader2 = CommunicationReader(broker=restored, run_id="run", consumer_step_id="consumer",
        output_refs=reader._output_refs, max_tokens=None, model_budget=SupplementalReadBudget())
    asyncio.run(reader2.read("producer", ["title"], operation_id="read:1"))
    assert restored.usage_snapshot() == usage
    with pytest.raises(CommunicationAccessError, match="changed"):
        asyncio.run(reader2.read("producer", ["details"], operation_id="read:1"))
    assert "Sensitive source" not in json.dumps(usage)


def test_page_reconstructs_escaped_unicode_text_with_hard_cap(tmp_path):
    text = ('引号"换行\n\\禁止写入😀' * 90)
    _, broker, reader = setup_reader(tmp_path, data={"details": text},
        budget=SupplementalReadBudget(maxReadTokens=80, pageTokens=40, totalTokens=5000))
    async def read_all():
        cursor, pieces = None, []
        for i in range(200):
            pack, cursor = await reader.read_page("producer", ["details"], cursor=cursor,
                page_tokens=40, operation_id=f"page:{i}")
            assert pack.tokens_delivered <= 40
            assert pack.tokens_available == pack.tokens_delivered and pack.saving_ratio == 0
            pieces.append(pack.data["details"])
            if cursor is None:
                return "".join(pieces)
        pytest.fail("pagination did not terminate")
    assert asyncio.run(read_all()) == text
    assert len(reader.drain_packs()) > 1
    assert broker.usage_snapshot()["supplemental"]["consumer"] > 0


def test_budget_denial_and_permission_denial_do_not_charge(tmp_path):
    _, broker, reader = setup_reader(tmp_path,
        budget=SupplementalReadBudget(maxReadTokens=20, pageTokens=10, totalTokens=20))
    for source, fields, error in [("other", ["title"], CommunicationAccessError),
                                  ("producer", ["secret"], CommunicationAccessError),
                                  ("producer", ["details"], EntropyBudgetExceededError)]:
        with pytest.raises(error):
            asyncio.run(reader.read(source, fields, operation_id="denied"))
    assert broker.usage_snapshot()["run"] == 0
    asyncio.run(reader.read("producer", ["title"], operation_id="first"))
    while broker.usage_snapshot()["supplemental"]["consumer"] < 20:
        before = broker.usage_snapshot()
        try:
            asyncio.run(reader.read("producer", ["title"], operation_id=str(before["run"])))
        except EntropyBudgetExceededError:
            assert broker.usage_snapshot() == before
            break


def test_oversized_nested_item_never_escapes_page_budget(tmp_path):
    _, broker, reader = setup_reader(tmp_path, data={"details": [{"body": "X" * 5000}]})
    with pytest.raises(EntropyBudgetExceededError):
        asyncio.run(reader.read_page("producer", ["details"], page_tokens=20))
    assert broker.usage_snapshot()["run"] == 0


def test_legacy_reader_does_not_enable_model_tools(tmp_path):
    _, _, reader = setup_reader(tmp_path)
    reader.model_budget = None
    assert ContextReadTools(context(reader)).list_tools() == ()


class Transport:
    def __init__(self, turns):
        self.turns, self.requests = iter(turns), []

    async def post_json(self, *, payload, **kwargs):
        self.requests.append(deepcopy(payload))
        turn = next(self.turns)
        message = {"role": "assistant", "content": json.dumps(turn)}
        reason = "stop"
        if isinstance(turn, tuple):
            name, args = turn
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call:{len(self.requests)}", "type": "function", "function": {
                    "name": name.replace(".", "__"), "arguments": json.dumps(args)}}]}
            reason = "tool_calls"
        return {"choices": [{"finish_reason": reason, "message": message}]}


def model(transport):
    registry = ModelCompatibilityRegistry()
    registry.register(OpenAICompatibleRuntime(manifest=CapabilityManifest(
        capabilityId="model", kind=CapabilityKind.MODEL, displayName="model", provider="test", capabilities=["mock"],
        metadata={"modelCapabilities": {"mock": {"features": {"tools": True}}}}), transport=transport))
    return RegisteredModelRuntime(registry=registry, provider="test", model="mock")


def test_real_model_tool_loop_reads_without_hands_and_replays_decisions(tmp_path):
    store, broker, reader = setup_reader(tmp_path)
    transport = Transport([("context.list_sources", {}),
                           ("context.read", {"producerStepId": "producer", "fields": ["details"]}), {"answer": "ok"}])
    ctx = context(reader, model(transport))
    assert supports_agent_tools(ctx)
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    first = asyncio.run(AgentToolSession(ctx).generate_json(prompt="Inspect source", schema=schema))
    assert first.data == {"answer": "ok"}
    assert "Sensitive source" not in json.dumps(transport.requests[0])
    assert "Sensitive source" in json.dumps(transport.requests[-1])
    before = broker.usage_snapshot()
    second = asyncio.run(AgentToolSession(ctx).generate_json(prompt="Inspect source", schema=schema))
    assert second.data == first.data and len(transport.requests) == 3
    assert broker.usage_snapshot() == before
    assert len(reader.drain_packs()) == 1


def test_native_agent_and_node_runner_record_supplemental_provenance_without_body(tmp_path):
    from adapters.model.native import NativeGeneralAgent
    from components.communicator import CommunicatorService
    from components.executor.graph import ACGExecutionState
    from components.executor.node_runner import ACGNodeRunner
    from components.memory import MemoryService
    from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
    from support.acg.models import build_default_capability_catalog

    store, broker, reader = setup_reader(tmp_path)
    descriptor = build_default_capability_catalog().get("analysis")
    answer = {"analysis": {"findings": ["Condition remains unresolved"], "assumptions": [], "gaps": ["needs evidence"]}}
    transport = Transport([("context.list_sources", {}),
        ("context.read", {"producerStepId": "producer", "fields": ["details"]}), answer])
    task = RuntimeMissionRecord(missionId="mission_context_tools", title="Assess supplied sources")
    run = RuntimeRunRecord(runId="run", missionId=task.mission_id, workflowId="context", domain="general", runtimeEngine="acg")
    step = WorkflowStep(stepId="consumer", name="Consumer", agentName="native_general_agent", capability="analysis",
        input={"from": {"producer": ["title", "details"]}, "prefetch": {"producer": ["title"]},
               "contextPolicy": {"supplementalReadBudget": SupplementalReadBudget().model_dump(by_alias=True)}},
        outputSpec=descriptor.output_contract)
    communicator = CommunicatorService(run_id="run", mission_id=task.mission_id)
    runner = ACGNodeRunner(task=task, run=run,
        workflow=WorkflowDefinition(workflowId="context", name="context", domain="general", runtimeEngine="acg"),
        steps={"consumer": step}, agents={"consumer": NativeGeneralAgent()}, communicator=communicator,
        memory=MemoryService(), value_store=store, communication_broker=broker,
        upstream_step_ids={"consumer": ("producer",)}, model_runtime=model(transport),
        capability_descriptors={"analysis": descriptor})
    state = ACGExecutionState(run_id="run", output_refs=reader._output_refs)
    result = asyncio.run(runner("consumer", state))
    assert result["outputRef"]
    assert state.communication_usage["supplemental"]["consumer"] > 0
    assert "Sensitive source" not in json.dumps(state.communication_usage)
    assert "Sensitive source" not in json.dumps(result)
    reads = result["communicationReads"]
    assert [item["fields"] for item in reads] == [["title"], ["details"]]
    assert [item["readPhase"] for item in reads] == ["prefetch", "supplemental"]
    before = deepcopy(state.communication_usage)
    asyncio.run(runner("consumer", state))
    assert state.communication_usage == before and len(transport.requests) == 3


def test_tool_result_is_included_in_complete_model_request_budget(tmp_path):
    from adapters.model_adapter import StructuredGenerationError

    _, broker, reader = setup_reader(tmp_path, data={"details": "private material " * 1800},
        budget=SupplementalReadBudget(maxReadTokens=12000, pageTokens=1000, totalTokens=16000))
    transport = Transport([("context.read", {"producerStepId": "producer", "fields": ["details"]})])
    ctx = context(reader, model(transport))
    ctx.step.input = {"contextPolicy": {"requestBudget": {"totalTokens": 2200, "outputReserveTokens": 100}}}
    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(AgentToolSession(ctx).generate_json(prompt="Inspect", schema={"type": "object"}))
    assert caught.value.code == "MODEL_INPUT_BUDGET_EXCEEDED"
    assert caught.value.audit["toolActionsExecuted"] == 1
    assert len(transport.requests) == 1
    assert "private material" not in json.dumps(caught.value.audit)


def test_model_read_replay_survives_reopening_value_store(tmp_path):
    store, broker, reader = setup_reader(tmp_path)
    transport = Transport([("context.read", {"producerStepId": "producer", "fields": ["title"]}), {"answer": "ok"}])
    schema = {"type": "object"}
    asyncio.run(AgentToolSession(context(reader, model(transport))).generate_json(prompt="Inspect", schema=schema))
    usage = deepcopy(broker.usage_snapshot())
    references = dict(reader._output_refs)
    store.close()
    reopened = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    restored = CommunicationBroker(manifest=broker.manifest, value_store=reopened, usage=usage)
    reader2 = CommunicationReader(broker=restored, run_id="run", consumer_step_id="consumer",
        output_refs=references, max_tokens=None, model_budget=SupplementalReadBudget())
    no_calls = Transport([])
    result = asyncio.run(AgentToolSession(context(reader2, model(no_calls))).generate_json(prompt="Inspect", schema=schema))
    assert result.data == {"answer": "ok"} and no_calls.requests == []
    assert restored.usage_snapshot() == usage


@pytest.mark.parametrize("budget", [
    {"maxReadTokens": True}, {"maxReadTokens": 10, "pageTokens": 20},
    {"maxReadTokens": 20000, "totalTokens": 10000}, {"totalTokens": 0},
])
def test_invalid_supplemental_budgets_are_rejected(budget):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SupplementalReadBudget.model_validate(budget)
