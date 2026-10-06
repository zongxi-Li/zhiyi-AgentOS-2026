from components.recovery.contract_repair import REGENERATION_REQUIRED, VALIDATED_LOSSLESS, repair_payload


def test_contract_repair_wraps_only_unambiguous_array_and_applies_defaults() -> None:
    schema = {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "severity": {"type": "string", "default": "medium"},
                    },
                },
            }
        },
    }

    result = repair_payload({"name": "late-payment"}, schema)

    assert result["adapter_status"] == VALIDATED_LOSSLESS
    assert result["adapted_payload"] == {"items": [{"name": "late-payment", "severity": "medium"}]}
    assert [item["operation"] for item in result["adapter_operations"]] == [
        "wrap_single_required_array",
        "apply_explicit_schema_defaults",
    ]
    assert result["original_payload_hash"] != result["adapted_payload_hash"]


def test_contract_repair_never_invents_missing_required_values() -> None:
    schema = {
        "type": "object",
        "required": ["name", "risk"],
        "properties": {"name": {"type": "string"}, "risk": {"type": "string"}},
    }

    result = repair_payload({"name": "late-payment"}, schema)

    assert result["adapter_status"] == REGENERATION_REQUIRED
    assert "adapted_payload" not in result
