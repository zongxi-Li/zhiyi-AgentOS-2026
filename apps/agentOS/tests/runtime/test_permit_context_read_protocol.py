"""Context declarations use the exact frozen execution schema during recovery."""
import json
from types import SimpleNamespace

import pytest

from adapters.context_tools import ContextReadTools
from components.executor.value_store import SQLiteExecutionValueStore
from contracts.context_read import context_read_parameters
from runtime.permit_recovery import assert_native_readonly_retry_safe
from test_permit_readonly_recovery import _native_attempt, _replace_payload


@pytest.fixture
def context_attempt(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "context-protocol.sqlite3")
    services, run, node, *_ = _native_attempt(store, missing_receipt=False)
    try:
        yield services, run, node, store
    finally:
        store.close()


def append_context_call(attempt, *, version=None, tool="context.read_page", arguments=None):
    services, run, node, store = attempt
    policy = {"supplementalReadBudget": {"maxReadTokens": 80, "pageTokens": 40}}
    if version is not None:
        policy["nestedReadVersion"] = version
    run.get_step(node.step_id).input["contextPolicy"] = policy
    key = node.operation_id + ":tools:0:model-turn"
    turn = store.get_tool_value(run_id=run.run_id, key=key)
    turn["response"]["toolCalls"].append({"id": "context-call", "type": "function", "function": {
        "name": tool.replace(".", "__"), "arguments": json.dumps(arguments)}})
    _replace_payload(store, run.run_id, key, turn)
    return services, run, node


@pytest.mark.parametrize("version,tool,arguments", [
    (None, "context.list_sources", {}),
    (None, "context.read", {"producerStepId": "upstream", "fields": ["facts"]}),
    (None, "context.read_page", {"producerStepId": "upstream", "fields": ["facts"], "cursor": None, "pageTokens": 40}),
    (1, "context.read_page", {"producerStepId": "upstream", "fields": ["facts"], "path": [0, "body"], "pageTokens": 40}),
    (1, "context.read_page", {"producerStepId": "upstream", "fields": ["facts"], "describe": True, "path": []}),
    (2, "context.read_page", {"producerStepId": "upstream", "fields": ["facts"]}),
])
def test_recovery_accepts_mixed_fs_and_context_reads_under_the_frozen_protocol(context_attempt, version, tool, arguments):
    services, run, node = append_context_call(context_attempt, version=version, tool=tool, arguments=arguments)
    before = list(context_attempt[3]._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert proof["toolDeclarationCount"] == 2 and proof["confirmedReadCount"] == 1
    assert list(context_attempt[3]._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == before


@pytest.mark.parametrize("version,override", [
    (None, {"path": [0]}), (None, {"describe": False}), (2, {"path": []}),
    (True, {"path": []}), (1, {"path": [True]}), (1, {"path": [-1]}),
    (1, {"path": [1.5]}), (1, {"describe": "true"}), (1, {"pageTokens": True}),
    (1, {"pageTokens": 0}), (1, {"pageTokens": 81}), (1, {"cursor": False}),
    (1, {"unknown": "value"}), (1, {"fields": []}), (1, {"producerStepId": ""}),
])
def test_recovery_rejects_fields_or_types_outside_the_same_frozen_schema(context_attempt, version, override):
    arguments = {"producerStepId": "upstream", "fields": ["facts"], **override}
    services, run, node = append_context_call(context_attempt, version=version, arguments=arguments)
    with pytest.raises(ValueError, match="contract violation"):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("version", [None, 1, 2])
def test_live_tool_definitions_use_the_same_parameter_schema_as_recovery(version):
    reader = SimpleNamespace(model_budget=SimpleNamespace(max_read_tokens=80), available_sources=("upstream",))
    context = SimpleNamespace(communication_reader=reader,
        step=SimpleNamespace(input={"contextPolicy": {"nestedReadVersion": version}}))
    for definition in ContextReadTools(context).list_tools():
        assert definition.parameters == context_read_parameters(definition.name,
            nested_read_version=version, max_read_tokens=80)


@pytest.mark.parametrize("frozen_version", [None, 1])
def test_historical_recovery_uses_the_attempts_frozen_protocol_instead_of_the_current_step(
    context_attempt, monkeypatch, frozen_version,
):
    import runtime.permit_recovery as recovery

    services, run, node = append_context_call(context_attempt, version=1 if frozen_version is None else None,
        arguments={"producerStepId": "upstream", "fields": ["facts"], "path": [0]})
    current = run.get_step(node.step_id)
    frozen = current.model_copy(deep=True)
    frozen.input["contextPolicy"]["nestedReadVersion"] = frozen_version
    original = recovery._retry_step_contract

    def historical_contract(*args, **kwargs):
        _, memory_manifest, graph_metadata = original(*args, **kwargs)
        return frozen, memory_manifest, graph_metadata

    monkeypatch.setattr(recovery, "_retry_step_contract", historical_contract)
    if frozen_version == 1:
        assert assert_native_readonly_retry_safe(services, run, node)["toolDeclarationCount"] == 2
    else:
        with pytest.raises(ValueError, match="contract violation"):
            assert_native_readonly_retry_safe(services, run, node)
