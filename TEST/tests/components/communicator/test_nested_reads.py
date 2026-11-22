"""Authorized nested reads reuse the same paging and operation ledger."""
from __future__ import annotations

import asyncio
import json

import pytest

from components.communicator import CommunicationBroker, CommunicationManifest, CommunicationRule
from components.communicator.broker import CommunicationAccessError, EntropyBudgetExceededError
from components.communicator.contracts import input_revision
from components.executor.value_store import InMemoryExecutionValueStore


def broker_for(value, *, fields=("details",)):
    store = InMemoryExecutionValueStore()
    reference = store.put_output(run_id="run", step_id="producer", payload={"details": value, "private": "not authorized"})
    broker = CommunicationBroker(value_store=store, manifest=CommunicationManifest(run_id="run", rules=(
        CommunicationRule(producer_step_id="producer", consumer_step_id="consumer",
            allowed_fields=fields, channel="producer:consumer"),)))
    return broker, reference


def read(broker, reference, **kwargs):
    return asyncio.run(broker.read_reference_page(run_id="run", consumer_step_id="consumer", output_ref=reference,
        requested_fields=kwargs.pop("fields", ["details"]), cursor=kwargs.pop("cursor", None),
        page_tokens=kwargs.pop("page_tokens", 80), reason="inspect nested evidence", **kwargs))


def describe(broker, reference, **kwargs):
    return broker.describe_reference_path(run_id="run", consumer_step_id="consumer", output_ref=reference,
        requested_fields=kwargs.pop("fields", ["details"]), **kwargs)


def test_describe_guides_reconstruction_of_an_oversized_nested_leaf():
    text = 'source "quoted"\n证据😀' * 200
    broker, reference = broker_for({"facts": [{"body": text, "flag": True}], "unknowns": []})
    with pytest.raises(EntropyBudgetExceededError):
        read(broker, reference)
    shape = describe(broker, reference)
    assert [item["key"] for item in shape["children"]] == ["facts", "unknowns"]
    assert text not in json.dumps(shape)
    array = describe(broker, reference, value_path=("facts",))
    assert array["indices"] == {"start": 0, "stop": 1}
    record = describe(broker, reference, value_path=("facts", 0))
    assert record["children"][0]["path"] == ["facts", 0, "body"]
    cursor, chunks = None, []
    while True:
        pack, cursor = read(broker, reference, value_path=("facts", 0, "body"), cursor=cursor)
        assert pack.value_path == ("facts", 0, "body")
        assert pack.model_dump(by_alias=True, mode="json")["path"] == ["facts", 0, "body"]
        assert pack.tokens_delivered <= 80
        chunks.append(pack.data["details"])
        if cursor is None:
            break
        assert cursor.startswith("path.v1:")
    assert "".join(chunks) == text
    assert all(event.get("path") == ["facts", 0, "body"] for event in broker.drain_events())


@pytest.mark.parametrize("path,value", [
    (("numbers",), list(range(100))),
    (("record",), {str(index): index for index in range(100)}),
    (("record", "1"), 1),
    (("flag",), True),
    (("none",), None),
])
def test_nested_pages_preserve_json_value_types(path, value):
    root = {"numbers": list(range(100)), "record": {str(index): index for index in range(100)}, "flag": True, "none": None}
    broker, reference = broker_for(root)
    cursor, pages = None, []
    while True:
        pack, cursor = read(broker, reference, value_path=path, cursor=cursor)
        pages.append(pack.data["details"])
        if cursor is None:
            break
    actual = ([item for page in pages for item in page] if isinstance(value, list) else
        {key: item for page in pages for key, item in page.items()} if isinstance(value, dict) else pages[0])
    assert actual == value and type(actual) is type(value)


@pytest.mark.parametrize("path", [(True,), (-1,), (1.0,), (None,), ({"key": "body"},), "body"])
def test_path_rejects_non_json_path_components_before_reading(path):
    broker, reference = broker_for({"body": "authorized"})
    for operation in (lambda: read(broker, reference, value_path=path),
                      lambda: describe(broker, reference, value_path=path)):
        with pytest.raises(CommunicationAccessError) as captured:
            operation()
        assert captured.value.code == "PATH_INVALID"
    assert broker.usage_snapshot()["run"] == 0


@pytest.mark.parametrize("fields,path,code", [
    (["private"], (), "FIELD_DENIED"),
    (["details"], ("..", "private"), "PATH_NOT_FOUND"),
    (["details"], ("array", "0"), "PATH_NOT_FOUND"),
    (["details"], ("array", 1), "PATH_NOT_FOUND"),
    (["details", "private"], ("array", 0), "FIELD_DENIED"),
])
def test_path_cannot_escape_the_authorized_top_level_field(fields, path, code):
    broker, reference = broker_for({"array": ["authorized"]})
    for operation in (lambda: read(broker, reference, fields=fields, value_path=path),
                      lambda: describe(broker, reference, fields=fields, value_path=path)):
        with pytest.raises(CommunicationAccessError) as captured:
            operation()
        assert captured.value.code == code
    assert broker.usage_snapshot()["run"] == 0


def test_nested_path_is_bound_to_cursor_and_operation_identity():
    broker, reference = broker_for({"first": "X" * 1000, "second": "X" * 1000})
    first, cursor = read(broker, reference, value_path=("first",), operation_id="page:1")
    assert cursor
    usage = broker.usage_snapshot()
    repeated, repeated_cursor = read(broker, reference, value_path=("first",), operation_id="page:1")
    assert repeated == first and repeated_cursor == cursor and broker.usage_snapshot() == usage
    with pytest.raises(CommunicationAccessError) as captured:
        read(broker, reference, value_path=("second",), cursor=cursor)
    assert captured.value.code == "CURSOR_INVALID"
    with pytest.raises(CommunicationAccessError) as captured:
        read(broker, reference, value_path=("second",), operation_id="page:1")
    assert captured.value.code == "READ_OPERATION_CONFLICT"


def test_flat_paging_retains_its_historical_fingerprint_cursor_and_pack_shape():
    broker, reference = broker_for("X" * 1000)
    pack, cursor = read(broker, reference, operation_id="legacy")
    assert cursor and cursor.startswith("0:")
    assert "path" not in pack.model_dump(by_alias=True)
    expected = input_revision([reference, ["details"], None, 80, pack.data, None])
    assert broker.usage_snapshot()["readOperations"]["legacy"] == {"fingerprint": expected}


def test_structure_index_keeps_all_child_keys_and_never_contains_leaf_values():
    broker, reference = broker_for({f"key-{index}": "private-leaf-value" for index in range(1000)})
    shape = describe(broker, reference)
    assert len(shape["children"]) == 1000
    assert "private-leaf-value" not in json.dumps(shape)
    assert shape["scope"] == "structure" and shape["itemCount"] == 1000
