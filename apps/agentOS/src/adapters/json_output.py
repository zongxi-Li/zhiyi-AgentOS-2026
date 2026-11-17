"""Decode model JSON without changing fields or incomplete field values."""

from collections.abc import Mapping
import json
import re


def _object(candidate):
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        if not exc.msg.startswith("Invalid control character") or any(
                ord(char) < 32 and char not in "\n\r\t" for char in candidate):
            return None
        try:
            parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _complete_root(candidate):
    """Close one root only; a JSON parser still checks every complete value."""
    if not candidate.startswith("{"):
        return None
    stack = []
    in_string = escaped = False
    for char in candidate:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or stack.pop() != {"}": "{", "]": "["}[char]:
                return None
    if in_string or stack != ["{"]:
        return None
    parsed = _object(candidate + "}")
    # An opening brace alone supplies no completed field to preserve.
    return parsed if parsed else None


def decode_json_object_value(content, *, finish_reason=None):
    """Return (object or None, root_completed), preserving wrapper tolerance.

    Root completion is available only after the provider explicitly reports a
    normal stop. EOF, length exhaustion and unknown termination never qualify.
    """
    if isinstance(content, Mapping):
        return dict(content), False
    if not isinstance(content, str):
        return None, False
    stripped = content.strip().lstrip("\ufeff")
    candidates = [stripped]
    recovery_candidates = [stripped]
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
        recovery_candidates.append(fenced.group(1).strip())
    first, last = stripped.find("{"), stripped.rfind("}")
    if first >= 0 and last > first:
        candidates.append(stripped[first:last + 1])
        # Leading explanation is an existing tolerated wrapper. A recovery may
        # never discard a later unfinished field or arbitrary trailing text.
        if last == len(stripped) - 1:
            recovery_candidates.append(stripped[first:last + 1])
    candidates = list(dict.fromkeys(candidates))
    for candidate in candidates:
        parsed = _object(candidate)
        if parsed is not None:
            return parsed, False
    if finish_reason == "stop":
        for candidate in dict.fromkeys(recovery_candidates):
            parsed = _complete_root(candidate)
            if parsed is not None:
                return parsed, True
    return None, False
