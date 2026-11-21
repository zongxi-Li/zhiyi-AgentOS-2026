"""Root delimiters can normalize only after a confirmed normal model stop."""

import json

import pytest

from adapters.json_output import decode_json_object_result, decode_json_object_value
from adapters.openai_runtime import ModelInvocationError, decode_json_object
from contracts.communication import validate_contract_payload
from support.acg.native_capabilities import _output_schema


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "Model answer follows:\n{}"])
def test_completed_nested_field_preserves_all_values_when_only_root_close_is_missing(wrapper):
    value = {"verification": {"summary": "literal brace } and escaped quote \"",
        "checks": [{"passed": False, "evidence": ["read:1", "read:2"]}], "remaining": None}}
    wire = json.dumps(value, ensure_ascii=False)[:-1]
    content = wrapper.format(wire)
    parsed, completed = decode_json_object_value(content, finish_reason="stop")
    assert parsed == value and completed
    assert decode_json_object(content, finish_reason="stop") == value


@pytest.mark.parametrize("finish_reason", [None, "", "length", "max_tokens", "content_filter", "tool_calls"])
def test_missing_close_never_recovers_an_unconfirmed_or_abnormal_end(finish_reason):
    assert decode_json_object_value('{"answer":"complete value"', finish_reason=finish_reason) == (None, False)


@pytest.mark.parametrize("wire", [
    "{", '{"answer":', '{"answer":"unfinished', '{"answer":"trailing escape\\',
    '{"answer":true,', '{"answer":tru', '{"answer":1e', '{"answer":-',
    '{"answer":[1,2', '{"answer":{"nested":1', '{"answer":[1,2}',
    '{"answer":{},"unfinished":[1', '{"answer":{},"unfinished":',
    'Answer: {"answer":{},"unfinished":[1', '{"answer":{} trailing text',
    '{"answer":"text" "missingComma":true', '{"answer":"text\u0000"',
])
def test_incomplete_values_nested_containers_and_invalid_fields_remain_errors(wire):
    assert decode_json_object_value(wire, finish_reason="stop") == (None, False)
    with pytest.raises(ModelInvocationError):
        decode_json_object(wire, finish_reason="stop")


def test_valid_object_and_tolerated_whitespace_do_not_require_any_recovery():
    assert decode_json_object_value('{"answer":"text"}') == ({"answer": "text"}, False)
    assert decode_json_object_value('{"answer":"line\nnext"}') == ({"answer": "line\nnext"}, False)


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "Model answer follows:\n{}"])
def test_duplicate_root_close_normalizes_without_changing_any_value_or_root_completed_flag(wrapper):
    value = {"answer": {"literal": '} and escaped quote "', "evidence": [False, None, 1.5, {"path": "a"}]}}
    wire = wrapper.format(json.dumps(value, ensure_ascii=False) + "}")
    assert decode_json_object_value(wire, finish_reason="stop") == (value, False)
    assert decode_json_object_result(wire, finish_reason="stop") == (value, "duplicate_root_close_removed")
    assert decode_json_object(wire, finish_reason="stop") == value


@pytest.mark.parametrize("finish_reason", [None, "", "length", "max_tokens", "content_filter", "tool_calls"])
def test_duplicate_root_close_requires_an_explicit_normal_stop(finish_reason):
    assert decode_json_object_value('{"answer":"complete"}}', finish_reason=finish_reason) == (None, False)


@pytest.mark.parametrize("wire", [
    '{"answer":"complete"}}}', '{"answer":"complete"}]', '{"answer":"complete"}}[]',
    '{"answer":"complete"}{"second":true}}', '{"answer":"complete"}} trailing text',
    '{"answer":"complete"} trailing text', '{"answer":"complete"}{"second":true}',
    '{"answer":"complete"} trailing text}', '{"answer":"unfinished}',
    '{"answer":[1,2}', '{"answer":{"nested":1} trailing}', '[]}',
])
def test_duplicate_root_close_never_discards_a_second_value_arbitrary_text_or_incomplete_fields(wire):
    assert decode_json_object_value(wire, finish_reason="stop") == (None, False)


@pytest.mark.parametrize(("facts", "metrics", "entities", "unknowns"), [
    (18, 14, 22, 17), (18, 20, 22, 17), (18, 20, 22, 17), (18, 20, 22, 17), (18, 20, 22, 17),
    (17, 12, 22, 17), (17, 12, 21, 17), (15, 12, 22, 17), (17, 12, 22, 17), (17, 12, 22, 17),
    (17, 12, 22, 17), (17, 12, 22, 17), (17, 12, 22, 17), (38, 18, 31, 15),
])
def test_repository_extraction_candidate_shapes_keep_all_fields_and_satisfy_existing_contract(
        facts, metrics, entities, unknowns):
    # Reproduce the rejected public candidate shapes without copying user data.
    value = {"extracted_information": {
        "facts": [{"name": f"fact-{index}", "value": {"imports": ["module"], "required": False},
                   "source": f"src/{index}.py"} for index in range(facts)],
        "metrics": [{"name": f"metric-{index}", "value": index, "unit": "files", "source": "manifest"}
                    for index in range(metrics)],
        "entities": [f"entity-{index}" for index in range(entities)],
        "unknowns": [f"unread-{index}" for index in range(unknowns)],
    }}
    wire = json.dumps(value, ensure_ascii=False) + "}"
    recovered, normalization = decode_json_object_result(wire, finish_reason="stop")
    assert recovered == value and normalization == "duplicate_root_close_removed"
    validate_contract_payload(recovered, _output_schema("information_extraction"),
                              step_id="extract", direction="output")
