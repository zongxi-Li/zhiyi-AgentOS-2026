"""Plan conservative field repairs without changing a validated sibling value."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from contracts.communication import validate_contract_payload


@dataclass(frozen=True)
class FieldRepairPlan:
    paths: tuple[tuple[str, ...], ...]
    schema: dict[str, Any]

    def merge(self, original: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
        validate_contract_payload(response, self.schema, step_id="field_repair", direction="output")
        merged = deepcopy(original)
        for path in self.paths:
            target, replacement = merged, response["patch"]
            for key in path[:-1]:
                target, replacement = target[key], replacement[key]
            target[path[-1]] = deepcopy(replacement[path[-1]])
        return merged


def plan_field_repair(payload: dict[str, Any], schema: dict[str, Any]) -> FieldRepairPlan | None:
    """Only repair simple, explicitly declared object fields; otherwise fall back.

    Array index edits, references, combinators and object-wide constraints require
    whole-result reasoning. Do not infer pointers by parsing an error message.
    """
    try:
        from jsonschema.validators import validator_for
    except ImportError:
        return None
    unsupported = {"$ref", "$dynamicRef", "allOf", "anyOf", "oneOf", "if", "then", "else", "not",
                   "dependentSchemas", "dependentRequired", "patternProperties", "unevaluatedProperties"}
    def complex_schema(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(unsupported.intersection(value)) or any(complex_schema(v) for v in value.values())
        return isinstance(value, list) and any(complex_schema(v) for v in value)
    if complex_schema(schema):
        return None
    errors = list(validator_for(schema)(schema).iter_errors(payload))
    paths: set[tuple[str, ...]] = set()
    supported = {"required", "type", "enum", "const", "minLength", "maxLength", "pattern",
                 "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                 "minItems", "maxItems", "uniqueItems"}
    for error in errors:
        path = tuple(error.absolute_path)
        if error.validator not in supported or any(not isinstance(k, str) for k in path):
            return None
        if error.validator == "required":
            if not isinstance(error.instance, dict):
                return None
            paths.update(path + (name,) for name in error.validator_value if name not in error.instance)
        else:
            if not path:
                return None
            paths.add(path)
    if not paths or len(paths) > 16:
        return None
    # A failed parent type owns its entire subtree; avoid overlapping edits.
    selected = tuple(sorted(p for p in paths if not any(p[:len(q)] == q for q in paths if len(q) < len(p))))
    patch: dict[str, Any] = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    for path in selected:
        node, target, instance = schema, patch, payload
        for index, key in enumerate(path):
            properties = node.get("properties", {})
            if key not in properties or not isinstance(properties[key], dict):
                return None
            node = properties[key]
            if key not in target["required"]:
                target["required"].append(key)
            if index == len(path) - 1:
                target["properties"][key] = deepcopy(node)
            else:
                if not isinstance(instance, dict) or not isinstance(instance.get(key), dict):
                    return None
                instance = instance[key]
                target = target["properties"].setdefault(key, {
                    "type": "object", "properties": {}, "required": [], "additionalProperties": False,
                })
    return FieldRepairPlan(selected, {
        "type": "object", "properties": {"patch": patch}, "required": ["patch"], "additionalProperties": False,
    })
