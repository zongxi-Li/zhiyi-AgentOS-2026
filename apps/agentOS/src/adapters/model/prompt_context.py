"""Lossless, request-local projection of an already authorized ContextPack.

Storage and communication/provenance ledgers retain their original payloads.
Only the model request is projected; references always address inline content,
never a database, a tool, or another run.
"""

from __future__ import annotations

import json
from typing import Any


def _wire(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def project_prompt_context(
    context_data: dict[str, Any],
    source_data: dict[str, Any],
    context_fields: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, str]]]:
    """Select declared fields, then replace large exact mirrors with inline aliases.

    Producer records remain separate, including conflicting identically named
    fields. A flattened field is omitted only when its complete wire value is
    present in an inline producer record. Small values stay inline when a
    reference would cost more. No summarization, token cap, or source mutation.
    """
    selected: dict[str, Any] = {}
    excluded: dict[str, set[str]] = {}
    retained: dict[str, dict[str, str]] = {}
    for producer, values in sorted(source_data.items()):
        if not isinstance(values, dict):
            selected[producer] = values
            continue
        requested = (context_fields or {}).get(producer)
        if requested is not None and not isinstance(requested, list):
            raise ValueError("prompt context fields must be a list")
        # Empty field lists retain Broker's 'all authorized fields' semantics.
        fields = set(requested) if requested else set(values)
        selected[producer] = {key: value for key, value in values.items() if key in fields}
        for key, value in values.items():
            if key in fields:
                retained.setdefault(key, {}).setdefault(_wire(value), producer)
            else:
                excluded.setdefault(key, set()).add(_wire(value))

    remaining: dict[str, Any] = {}
    aliases: dict[str, dict[str, str]] = {}
    for field, value in sorted(context_data.items()):
        encoded = _wire(value)
        if encoded in excluded.get(field, set()) and encoded not in retained.get(field, set()):
            continue
        producer = retained.get(field, {}).get(encoded)
        if producer is not None:
            reference = {"sourceId": producer, "field": field}
            # Include the alias-channel envelope overhead in the decision so
            # even a request with one alias becomes smaller.
            if len(encoded) > len(_wire(reference)) + 100:
                aliases[field] = reference
        if field not in aliases:
            remaining[field] = value
    return remaining, selected, aliases


__all__ = ["project_prompt_context"]
