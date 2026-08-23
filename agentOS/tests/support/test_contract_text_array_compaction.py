"""模型输出在严格合同边界内的无损文本数组归一化测试。"""

from __future__ import annotations

import pytest

from contracts.communication import (
    ContextContractError,
    compact_contract_text_arrays,
    validate_contract_payload,
)


def test_compacts_oversized_text_array_without_dropping_content() -> None:
    schema = {
        "type": "object",
        "properties": {
            "assumptions": {
                "type": "array",
                "items": {"type": "string", "maxLength": 64},
                "maxItems": 3,
            }
        },
        "required": ["assumptions"],
    }
    original = {"assumptions": ["事实一", "事实二", "事实三", "事实四", "事实五"]}

    compacted = compact_contract_text_arrays(original, schema)

    assert len(compacted["assumptions"]) == 3
    assert "\n".join(compacted["assumptions"]) == "\n".join(original["assumptions"])
    assert original["assumptions"] == ["事实一", "事实二", "事实三", "事实四", "事实五"]
    validate_contract_payload(compacted, schema, step_id="understand", direction="output")


def test_keeps_invalid_array_when_lossless_compaction_cannot_fit_contract() -> None:
    schema = {
        "type": "array",
        "items": {"type": "string", "maxLength": 3},
        "maxItems": 2,
    }
    original = ["aa", "bb", "cc"]

    compacted = compact_contract_text_arrays(original, schema)

    assert compacted == original
    with pytest.raises(ContextContractError):
        validate_contract_payload(compacted, schema, step_id="understand", direction="output")


def test_does_not_coerce_non_text_arrays() -> None:
    schema = {
        "type": "array",
        "items": {"type": "object"},
        "maxItems": 1,
    }
    original = [{"value": 1}, {"value": 2}]

    assert compact_contract_text_arrays(original, schema) == original
