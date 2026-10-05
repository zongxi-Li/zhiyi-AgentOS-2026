from copy import deepcopy

import pytest

from adapters.model.contract_repair import plan_field_repair
from contracts.communication import ContextContractError, validate_contract_payload


SCHEMA = {
    "type": "object", "properties": {
        "deliverable": {"type": "object", "properties": {
            "body": {"type": "string"},
            "sourceRefs": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        }, "required": ["body", "sourceRefs"]},
    }, "required": ["deliverable"],
}


def test_missing_reference_repair_preserves_body_and_original():
    original = {"deliverable": {"body": "valid long document"}}
    snapshot = deepcopy(original)
    plan = plan_field_repair(original, SCHEMA)
    assert plan.paths == (("deliverable", "sourceRefs"),)
    merged = plan.merge(original, {"patch": {"deliverable": {"sourceRefs": ["attachment:original"]}}})
    validate_contract_payload(merged, SCHEMA, step_id="final", direction="output")
    assert merged["deliverable"]["body"] == original["deliverable"]["body"]
    assert original == snapshot


@pytest.mark.parametrize("response", [
    {"patch": {"deliverable": {"sourceRefs": [], "body": "rewritten"}}},
    {"patch": {"deliverable": {"sourceRefs": []}}},
    {"patch": {"deliverable": {"sourceRefs": "invented type"}}},
    {"patch": {}},
])
def test_reject_extra_edits_missing_fields_and_invalid_replacements(response):
    original = {"deliverable": {"body": "keep"}}
    plan = plan_field_repair(original, SCHEMA)
    with pytest.raises(ContextContractError):
        plan.merge(original, response)
    assert original == {"deliverable": {"body": "keep"}}


def test_collect_multiple_failures_without_replacing_siblings():
    original = {"deliverable": {"body": 7, "sourceRefs": []}, "other": "keep"}
    plan = plan_field_repair(original, SCHEMA)
    assert set(plan.paths) == {("deliverable", "body"), ("deliverable", "sourceRefs")}
    merged = plan.merge(original, {"patch": {"deliverable": {"body": "fixed", "sourceRefs": ["source"]}}})
    assert merged["other"] == "keep"


@pytest.mark.parametrize("payload,schema", [
    ({"deliverable": {"body": "ok", "sourceRefs": [5]}}, SCHEMA),
    ({"deliverable": {"body": "ok", "sourceRefs": []}}, {**SCHEMA, "allOf": [{"type": "object"}]}),
    ({"unexpected": True}, {"type": "object", "additionalProperties": False}),
    ({}, {"type": "object", "required": ["notDeclared"]}),
])
def test_complex_or_undeclared_failure_falls_back(payload, schema):
    assert plan_field_repair(payload, schema) is None


def test_literal_property_names_are_not_parsed_as_paths():
    schema = {"type": "object", "properties": {"a.b/c": {"type": "string"}}, "required": ["a.b/c"]}
    plan = plan_field_repair({}, schema)
    assert plan.paths == (("a.b/c",),)
    assert plan.merge({}, {"patch": {"a.b/c": "value"}}) == {"a.b/c": "value"}
