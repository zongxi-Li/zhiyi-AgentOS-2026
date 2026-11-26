from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adapters.agent.tool_session import AgentToolSession, agent_tool_definitions, supports_agent_tools
from adapters.tool.audited_runtime import AuditedToolRuntime
from adapters.tool.context_read import ContextReadTools
from adapters.tool.hands_http import receipt_checksum
from adapters.model.compatibility import ModelCompatibilityRegistry
from adapters.model.registered_runtime import RegisteredModelRuntime
from adapters.model.openai_runtime import OpenAICompatibleRuntime
from components.communicator.broker import CommunicationBroker, CommunicationAccessError, EntropyBudgetExceededError
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from components.communicator.reader import CommunicationReader
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.capability import CapabilityKind, CapabilityManifest
from contracts.request_budget import ModelRequestBudget, SupplementalReadBudget
from contracts.tools import hands_tools


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
        step=SimpleNamespace(input={}, step_id="consumer", name="consumer", capability="analysis"),
        run=SimpleNamespace(run_id="run", input={}, execution_state={}), commit_id="commit", attempt_id="attempt")


@pytest.mark.asyncio
async def test_receipt_pages_share_the_frozen_context_budget_and_require_admitted_references(tmp_path):
    store, broker, reader = setup_reader(tmp_path, budget=SupplementalReadBudget(
        maxReadTokens=40, pageTokens=40, totalTokens=60))

    def save_receipt(step_id):
        receipt = {"identity": {"runId": "run", "stepId": step_id, "attemptId": "attempt", "commitId": "commit"},
                   "capabilityId": "fs.read", "status": "completed",
                   "output": {"path": "note.txt", "text": "Bound evidence. " * 80}}
        receipt["checksum"] = receipt_checksum(receipt)
        return store.put_tool_value(run_id="run", step_id=step_id, key=step_id + ":receipt", payload=receipt)

    reference, private = save_receipt("producer"), save_receipt("unrelated")
    output_ref = reader._output_refs["producer"]
    store.prepare_node_commit(run_id="run", commit_id="commit")
    store.complete_node_commit(run_id="run", commit_id="commit",
        payload={"outputRef": output_ref, "auditOutcome": "allow",
                 "toolCalls": [{"runId": "run", "stepId": "producer", "receiptRef": reference}]})
    ctx = context(reader)
    ctx.context_pack = SimpleNamespace(evidence_refs=[], source_data={"producer": {"extracted_information": {
        "facts": [{"source": reference}, {"source": private}]}}})
    tools = ContextReadTools(ctx)
    tools.evidence_enabled = True
    tools.admit_context_pack_evidence()
    args = {"producerStepId": reference, "fields": ["content"]}
    listed = await tools.execute("context.list_sources", {}, operation_key="list")
    assert reference in listed.model_dump_json() and private not in listed.model_dump_json()
    assert "Bound evidence." not in listed.model_dump_json()
    with pytest.raises(CommunicationAccessError):
        await tools.execute("context.read_page", {**args, "producerStepId": private}, operation_key="private")
    with pytest.raises(CommunicationAccessError):
        await tools.execute("context.read_page", {**args, "cursor": "0:100"}, operation_key="bad-cursor")
    first = await tools.execute("context.read_page", args, operation_key="page")
    assert first.output["estimatedTokens"] <= 40
    assert first.output["evidenceRefs"] == [reference] and first.output["nextCursor"]
    usage = broker.usage_snapshot()
    assert await tools.execute("context.read_page", args, operation_key="page") == first
    assert broker.usage_snapshot() == usage
    with pytest.raises(EntropyBudgetExceededError):
        await tools.execute("context.read_page", {**args, "cursor": first.output["nextCursor"]}, operation_key="page2")
    assert "Bound evidence." not in json.dumps(broker.usage_snapshot())


def test_rolling_request_defers_old_page_bodies_and_keeps_reference_and_cursor():
    def message(ref, marker):
        output = {"scope": "evidence_page", "receiptRef": ref, "nextCursor": "next",
                  "complete": False, "data": {"content": marker * 490}}
        return {"role": "tool", "tool_call_id": ref,
                "content": json.dumps({"name": "context.read_page", "output": output})}

    protected = {"role": "system", "content": "Preserve the frozen acceptance contract"}
    latest_call = {"role": "assistant", "tool_calls": [{"id": "second"}]}
    original = [protected, message("first", "a"), latest_call, message("second", "b")]
    budget = ModelRequestBudget(totalTokens=1000, outputReserveTokens=100,
        workingSetTriggerTokens=400, workingSetTargetTokens=350)
    projected = AgentToolSession._bound_receipt_pages(original, [], {}, budget)
    assert projected[0] == protected and projected[-1] == original[-1]
    output = json.loads(projected[1]["content"])["output"]
    assert output["receiptRef"] == "first" and output["nextCursor"] == "next"
    assert output["dataDeferred"] is True and "data" not in output
    assert "data" in json.loads(original[1]["content"])["output"]


def test_directory_is_permission_scoped_and_contains_no_body_or_reference(tmp_path):
    _, _, reader = setup_reader(tmp_path)
    result = asyncio.run(ContextReadTools(context(reader)).execute("context.list_sources", {}, operation_key="list"))
    wire = result.model_dump_json()
    assert "never authorized" not in wire and "secret" not in wire and "Sensitive source" not in wire
    assert "outputRef" not in wire and "details" in wire and "estimatedTokens" in wire


def test_read_only_workspace_scope_preserves_authorized_context_reading(tmp_path):
    _, _, reader = setup_reader(tmp_path)
    bound = context(reader)
    native = SimpleNamespace(list_tools=hands_tools)
    bound.tool_runtime = AuditedToolRuntime(delegate=native, allowed_tools=()).scoped({"fs.read", "fs.list"})
    assert {tool.name for tool in agent_tool_definitions(bound)} == {
        "fs.read", "fs.list", "context.list_sources", "context.read", "context.read_page"}
    observed = asyncio.run(ContextReadTools(bound).execute("context.read",
        {"producerStepId": "producer", "fields": ["title"]}, operation_key="readonly-context"))
    assert observed.output["data"] == {"title": "brief"}


@pytest.mark.parametrize('budget', [SupplementalReadBudget(),
    SupplementalReadBudget(maxReadTokens=4096, pageTokens=1024, totalTokens=16384)])
def test_replay_charges_once_after_restoring_checkpoint_and_conflicts_fail_closed(tmp_path, budget):
    store, broker, reader = setup_reader(tmp_path, budget=budget)
    asyncio.run(reader.read("producer", ["title"], operation_id="read:1"))
    usage = deepcopy(broker.usage_snapshot())
    asyncio.run(reader.read("producer", ["title"], operation_id="read:1"))
    assert broker.usage_snapshot() == usage
    restored = CommunicationBroker(manifest=broker.manifest, value_store=store, usage=usage)
    reader2 = CommunicationReader(broker=restored, run_id="run", consumer_step_id="consumer",
        output_refs=reader._output_refs, max_tokens=None, model_budget=budget)
    asyncio.run(reader2.read("producer", ["title"], operation_id="read:1"))
    assert restored.usage_snapshot() == usage
    with pytest.raises(CommunicationAccessError, match="changed"):
        asyncio.run(reader2.read("producer", ["details"], operation_id="read:1"))
    assert "Sensitive source" not in json.dumps(usage)


def test_new_default_reads_have_no_fixed_single_read_or_cumulative_ceiling(tmp_path):
    text = 'source finding ' * 3000
    _, broker, reader = setup_reader(tmp_path, data={'details': text})
    assert reader.model_budget.max_read_tokens is None
    assert reader.model_budget.total_tokens is None
    tools = ContextReadTools(context(reader))
    page_schema = next(tool.parameters['properties']['pageTokens'] for tool in tools.list_tools()
                       if tool.name == 'context.read_page')
    assert 'maximum' not in page_schema
    for index in range(3):
        result = asyncio.run(tools.execute('context.read', {'producerStepId': 'producer', 'fields': ['details']},
            operation_key=f'large:{index}'))
        assert result.output['data']['details'] == text
    assert broker.usage_snapshot()['supplemental']['consumer'] > 16384
    assert all(event['readPhase'] == 'supplemental' for event in broker.drain_events())


def test_default_page_size_is_a_work_unit_without_a_fixed_maximum(tmp_path):
    _, broker, reader = setup_reader(tmp_path, data={'details': 'source ' * 5000})
    assert reader.model_budget.page_tokens == 1024
    result = asyncio.run(ContextReadTools(context(reader)).execute('context.read_page',
        {'producerStepId': 'producer', 'fields': ['details'], 'pageTokens': 5000}, operation_key='large-page'))
    assert result.output['estimatedTokens'] > 4096
    assert broker.usage_snapshot()['supplemental']['consumer'] == result.output['estimatedTokens']
    assert broker.drain_events()[0]['readPhase'] == 'supplemental'


def test_explicit_frozen_budget_and_host_read_limit_remain_effective(tmp_path):
    frozen = {'version': 'supplemental-read.v1', 'maxReadTokens': 4096, 'pageTokens': 1024, 'totalTokens': 16384}
    assert SupplementalReadBudget.model_validate(frozen).model_dump(by_alias=True) == frozen
    _, broker, reader = setup_reader(tmp_path)
    reader._max_tokens = 20
    with pytest.raises(EntropyBudgetExceededError):
        asyncio.run(reader.read('producer', ['details'], operation_id='host-denied'))
    with pytest.raises(EntropyBudgetExceededError):
        asyncio.run(reader.read_page('producer', ['details'], page_tokens=40, operation_id='host-page-denied'))
    assert broker.usage_snapshot()['run'] == 0


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


def test_nested_read_protocol_is_enabled_for_new_steps_without_changing_legacy_tool_schemas(tmp_path):
    _, _, reader = setup_reader(tmp_path)
    ctx = context(reader)
    legacy = ContextReadTools(ctx)
    legacy_page = next(tool for tool in legacy.list_tools() if tool.name == "context.read_page")
    assert "path" not in legacy_page.parameters["properties"]
    assert "describe" not in legacy_page.parameters["properties"]
    ctx.step.input = {"contextPolicy": {"nestedReadVersion": 1}}
    current_page = next(tool for tool in ContextReadTools(ctx).list_tools() if tool.name == "context.read_page")
    assert {"path", "describe"} <= set(current_page.parameters["properties"])
    assert legacy.list_tools() == ContextReadTools(context(reader)).list_tools()


def test_context_tools_can_describe_and_page_nested_values_without_claiming_field_completion(tmp_path):
    text = 'nested evidence "quoted"\n' * 100
    _, broker, reader = setup_reader(tmp_path, data={"details": [{"body": text, "other": "not selected"}]})
    ctx = context(reader)
    ctx.step.input = {"contextPolicy": {"nestedReadVersion": 1}}
    tools = ContextReadTools(ctx)
    structure = asyncio.run(tools.execute("context.read_page", {"producerStepId": "producer",
        "fields": ["details"], "describe": True}, operation_key="shape"))
    assert structure.output["scope"] == "structure" and structure.output["complete"] is False
    assert structure.output["structure"]["indices"] == {"start": 0, "stop": 1}
    assert text not in structure.model_dump_json()
    cursor, chunks = None, []
    while True:
        result = asyncio.run(tools.execute("context.read_page", {"producerStepId": "producer", "fields": ["details"],
            "path": [0, "body"], "pageTokens": 80, "cursor": cursor}, operation_key="nested:" + str(cursor)))
        output = result.output
        assert output["scope"] == "subtree_page" and output["complete"] is False
        assert output["path"] == [0, "body"]
        chunks.append(output["data"]["details"])
        cursor = output["nextCursor"]
        if cursor is None:
            break
    assert "".join(chunks) == text
    assert broker.usage_snapshot()["supplemental"]["consumer"] > 0


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


def test_tool_session_preserves_unversioned_wal_prompt_on_replay(tmp_path, monkeypatch):
    _, _, reader = setup_reader(tmp_path)
    transport = Transport([{"answer": "legacy"}])
    ctx = context(reader, model(transport))
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    with monkeypatch.context() as legacy:
        legacy.setattr(AgentToolSession, "uses_evidence_pages", lambda *args: False)
        first = asyncio.run(AgentToolSession(ctx).generate_json(prompt="Inspect source", schema=schema))
    second = asyncio.run(AgentToolSession(ctx).generate_json(prompt="Inspect source", schema=schema))
    assert second.data == first.data == {"answer": "legacy"}
    assert len(transport.requests) == 1


def test_native_agent_and_node_runner_record_supplemental_provenance_without_body(tmp_path):
    from adapters.agent.native import NativeGeneralAgent
    from components.communicator import CommunicatorService
    from components.executor.graph import ACGExecutionState
    from components.executor.node_runner import ACGNodeRunner
    from components.memory import MemoryService
    from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
    from support.packs.native_capabilities import build_default_capability_catalog

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
    from adapters.model.protocols import StructuredGenerationError

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
