"""Only a completed root delimiter can be recovered from a normal model stop."""

import json

import pytest

from adapters.json_output import decode_json_object_value
from adapters.openai_runtime import ModelInvocationError, decode_json_object


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
