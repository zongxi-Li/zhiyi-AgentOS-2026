"""Bounded, body-free diagnostics of the messages actually sent to a provider."""
from __future__ import annotations

from typing import Any

from adapters.prompt_runtime import canonical_hash


def request_diagnostics(payload: dict[str, Any], schema_index: int | None) -> dict[str, Any]:
    messages = payload.get("messages", [])
    shared = schema_index == 2 and len(messages) >= 4
    lengths = [len(message.get("content", "")) if isinstance(message.get("content", ""), str)
               else len(str(message.get("content", ""))) for message in messages]
    segments = []
    for index, message in enumerate(messages[:32]):
        segment = (
            ("sharedPolicy", "sharedTask", "capabilityAndSchema", "nodeInput")[index]
            if shared and index < 4 else "continuation" if shared else "message"
        )
        segments.append({
            "index": index,
            "role": message.get("role") if message.get("role") in {"system", "user", "assistant", "tool", "developer"} else "other",
            "segment": segment, "characters": lengths[index], "hash": canonical_hash(message),
        })
    return {
        "layoutVersion": "shared-execution.v1" if shared else "messages.v1",
        "lengthUnit": "characters",
        "messageCount": len(messages),
        "totalCharacters": sum(lengths),
        "omittedSegmentCount": max(0, len(messages) - len(segments)),
        "sharedPrefixHash": canonical_hash(messages[:2]) if shared else None,
        "sharedPrefixCharacters": sum(item["characters"] for item in segments[:2]) if shared else None,
        "segments": segments,
    }
