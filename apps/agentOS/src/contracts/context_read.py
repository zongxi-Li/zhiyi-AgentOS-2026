"""Frozen model-tool parameter schemas shared by execution and recovery."""
from __future__ import annotations

from contracts.communication import ContextContractError


def context_read_parameters(name, *, nested_read_version=None, max_read_tokens=None):
    common = {"producerStepId": {"type": "string", "minLength": 1},
        "fields": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}}
    if name == "context.list_sources":
        properties, required = {}, []
    elif name == "context.read":
        properties, required = common, ["producerStepId", "fields"]
    elif name == "context.read_page":
        page_tokens = {"type": "integer", "minimum": 1}
        if max_read_tokens is not None:
            page_tokens["maximum"] = max_read_tokens
        nested = {"path": {"type": "array", "items": {"anyOf": [
            {"type": "string"}, {"type": "integer", "minimum": 0}]}},
            "describe": {"type": "boolean"}} if type(nested_read_version) is int and nested_read_version == 1 else {}
        properties = {**common, "cursor": {"type": ["string", "null"]}, "pageTokens": page_tokens, **nested}
        required = ["producerStepId", "fields"]
    else:
        raise ValueError("unknown context-read tool")
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def validate_context_read_arguments(name, arguments, *, nested_read_version=None, max_read_tokens=None):
    # Recovery must enforce every keyword of the advertised protocol. The
    # generic optional fallback does not implement nested unions or bounds.
    try:
        from jsonschema import Draft202012Validator, ValidationError
    except ModuleNotFoundError as exc:
        raise ValueError("context-read schema validation requires jsonschema") from exc
    schema = context_read_parameters(name, nested_read_version=nested_read_version, max_read_tokens=max_read_tokens)
    try:
        Draft202012Validator(schema).validate(arguments)
    except ValidationError as exc:
        raise ContextContractError(step_id=name, direction="input", message=exc.message,
            path=".".join(str(item) for item in exc.absolute_path)) from exc


__all__ = ["context_read_parameters", "validate_context_read_arguments"]
