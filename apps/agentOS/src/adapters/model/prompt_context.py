"""Lossless, request-local projection of an already authorized ContextPack.

Storage and communication/provenance ledgers retain their original payloads.
Only the model request is projected; references always address inline content,
never a database, a tool, or another run.
"""

from __future__ import annotations

import json
from copy import deepcopy
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


def project_inline_content(pack: dict[str, Any]) -> dict[str, Any]:
    """Share exact JSON subtrees, retaining the smaller lossless representation.

    v2 also shares objects and arrays, including repeated structured deliverables.
    References are emitted in dependency order: a target's nested aliases always
    precede an alias to that target. No references load content outside this input.
    The string-only projection remains a fallback when container aliases cost more.
    """
    candidate = _project_inline_content(pack, containers=True)
    if candidate.get("inlineContentRefs", {}).get("content", {}).get("version") != "inline-content.v2":
        return candidate
    baseline = _project_inline_content(pack, containers=False)
    return candidate if len(_wire(candidate)) < len(_wire(baseline)) else baseline


def _project_inline_content(pack: dict[str, Any], *, containers: bool) -> dict[str, Any]:
    """Build deterministic aliases without changing source or control channels.

    Paths address this ContextPack only. Null placeholders preserve array indices
    and object keys; a sidecar authored here (never parsed from source data)
    identifies every replacement. JSON encoding distinguishes bools, numbers and
    strings, preserves array order, and normalizes only mapping key order.
    """
    projected = deepcopy(pack)
    seen: dict[str, list[str | int]] = {}
    refs: list[dict[str, Any]] = []
    shared_containers = False

    def visit(value: Any, path: list[str | int]) -> Any:
        nonlocal shared_containers
        shareable = isinstance(value, str) and len(value) >= 256
        # The final size comparison may select either strategy per node. Keep
        # task material identical in both so that choice cannot perturb the
        # shared provider prefix between nodes.
        task_source = path[:3] == ["sourceData", "content", "taskSources"]
        shareable = shareable or (containers and not task_source and isinstance(value, (dict, list)))
        encoded = _wire(value) if shareable else ""
        shareable = shareable and len(encoded) >= 256
        if shareable:
            target = seen.get(encoded)
            if target is not None:
                ref = {"path": path, "targetPath": target}
                # Pay for the sidecar and its trust envelope even for one ref.
                if len(encoded) > len(_wire(ref)) + 160:
                    refs.append(ref)
                    shared_containers |= isinstance(value, (dict, list))
                    return None
        if isinstance(value, dict):
            value = {key: visit(item, [*path, key]) for key, item in sorted(value.items())}
        elif isinstance(value, list):
            value = [visit(item, [*path, index]) for index, item in enumerate(value)]
        if shareable:
            # Children precede their containing target in restoration order.
            seen.setdefault(encoded, path)
        return value

    # Only content is visited. Never rewrite trust labels, output contracts,
    # mission controls, or pre-existing sourceId/field aliases.
    source = projected.get("sourceData", {}).get("content")
    if isinstance(source, dict):
        # Mission material must stay stable even if another node happens to
        # repeat it. Always choose taskSources as a target before node sources.
        keys = [key for key in ("taskSources", "contextSources") if key in source]
        keys.extend(key for key in sorted(source) if key not in keys)
        for key in keys:
            source[key] = visit(source[key], ["sourceData", "content", key])
    for channel in ("upstreamOutputs", "memory", "toolObservations"):
        envelope = projected.get(channel)
        if isinstance(envelope, dict) and "content" in envelope:
            envelope["content"] = visit(envelope["content"], [channel, "content"])
    if refs:
        projected["inlineContentRefs"] = {
            "trustClass": "agent_generated",
            "content": {"version": "inline-content.v2" if shared_containers else "inline-content.v1", "references": refs},
        }
    return projected


__all__ = ["project_prompt_context", "project_inline_content"]
