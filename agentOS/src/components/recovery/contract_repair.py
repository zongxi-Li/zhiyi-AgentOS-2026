"""Deterministic, lossless repair for JSON contract payloads.

This component performs no semantic generation. It may only apply an
unambiguous object-to-array envelope and defaults explicitly declared by the
schema; otherwise the caller must regenerate the payload.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from contracts.communication import (
    ContextContractError,
    apply_contract_defaults,
    validate_contract_payload,
)

VALIDATED_LOSSLESS = "validated_lossless"
REGENERATION_REQUIRED = "regeneration_required"
UNREPAIRABLE = "unrepairable"


def payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_payload_shape(payload: Any, schema: dict[str, Any]) -> Any:
    """Wrap one complete item in the schema's sole required array envelope."""
    if not isinstance(payload, dict):
        return deepcopy(payload)
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return deepcopy(payload)
    envelopes = [
        field for field in required
        if isinstance(properties.get(field), dict) and properties[field].get("type") == "array"
    ]
    if len(required) != 1 or len(envelopes) != 1:
        return deepcopy(payload)
    envelope = envelopes[0]
    if envelope in payload:
        return deepcopy(payload)
    item_schema = properties[envelope].get("items")
    if not isinstance(item_schema, dict) or item_schema.get("type") != "object":
        return deepcopy(payload)
    item_required = item_schema.get("required")
    if not isinstance(item_required, list) or not item_required or not set(item_required).issubset(payload):
        return deepcopy(payload)
    return {envelope: [deepcopy(payload)]}


def repair_payload(payload: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable repair decision without inventing semantic values."""
    original = deepcopy(payload)
    original_hash = payload_hash(original)
    operations: list[dict[str, str]] = []
    try:
        shaped = normalize_payload_shape(original, schema)
        if shaped != original:
            operations.append({"operation": "wrap_single_required_array"})
        candidate = apply_contract_defaults(shaped, schema)
        if candidate != shaped:
            operations.append({"operation": "apply_explicit_schema_defaults"})
        validate_contract_payload(candidate, schema, step_id="contract_repair", direction="payload")
    except ContextContractError as exc:
        return {
            "adapter_status": REGENERATION_REQUIRED,
            "adapter_operations": operations,
            "adapter_issues": [str(exc)],
            "original_payload_hash": original_hash,
        }
    except Exception as exc:
        return {
            "adapter_status": UNREPAIRABLE,
            "adapter_operations": operations,
            "adapter_issues": [f"{type(exc).__name__}: {exc}"],
            "original_payload_hash": original_hash,
        }
    if candidate == original:
        return {
            "adapter_status": REGENERATION_REQUIRED,
            "adapter_operations": [],
            "adapter_issues": ["payload already satisfies the schema; no lossless repair applies"],
            "original_payload_hash": original_hash,
        }
    return {
        "adapter_status": VALIDATED_LOSSLESS,
        "repair_kind": "shape_only",
        "adapter_operations": operations,
        "adapter_issues": [],
        "original_payload_hash": original_hash,
        "adapted_payload_hash": payload_hash(candidate),
        "adapted_payload": candidate,
    }


__all__ = [
    "REGENERATION_REQUIRED", "UNREPAIRABLE", "VALIDATED_LOSSLESS",
    "normalize_payload_shape", "payload_hash", "repair_payload",
]
