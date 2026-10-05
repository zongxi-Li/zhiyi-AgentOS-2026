"""Evaluate frozen document requirements against authorized committed artifacts."""

import json
import math
import re

from components.auditor.artifact_acceptance import JSON_CHECK_BYTES, _reject_json_constant
from contracts.content import ContentKind
from contracts.task_acceptance import TaskAcceptanceSpec, TaskAcceptanceResult

_MISSING = object()
_JSON_CHECK_DEPTH = 128


def _bounded_json_depth(text):
    """Bound nesting before parsing, independently of process recursion settings."""
    depth, in_string, escaped = 0, False, False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > _JSON_CHECK_DEPTH:
                raise RecursionError("task acceptance JSON nesting exceeds its bounded depth")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("invalid JSON nesting")


def _resolve(document, pointer):
    value = document
    for segment in pointer.split("/")[1:] if pointer else ():
        key = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value.get(key, _MISSING)
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            # Reject huge indices without converting arbitrarily long integers.
            value = value[int(key)] if len(key) < 10 and int(key) < len(value) else _MISSING
        else:
            return _MISSING
        if value is _MISSING:
            return value
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous duplicate JSON key")
        result[key] = value
    return result


def evaluate_task_acceptance(*, store, spec: TaskAcceptanceSpec, candidates: list[dict]) -> tuple[TaskAcceptanceResult, ...]:
    """Candidates originate only from the Runtime's validated node commits.

    A candidate carries task/key identity, ArtifactEvidence and review status.
    No executable expression, filesystem path or tool call is accepted here.
    """
    results, documents = [], {}
    for criterion in spec.criteria:
        matches = [c for c in candidates if c["artifactKey"] == criterion.artifact_key
            and (criterion.task_key is None or c["taskKey"] == criterion.task_key)]
        identity = dict(criterionId=criterion.criterion_id)
        if len(matches) != 1:
            results.append(TaskAcceptanceResult(**identity, outcome="unverified",
                reason="artifact_ambiguous" if matches else "artifact_missing"))
            continue
        candidate = matches[0]
        evidence = candidate["evidence"]
        identity.update(sourceRunId=evidence.source_run_id, commitId=evidence.commit_id,
            manifestId=evidence.manifest_id, checksum=evidence.checksum)
        if not candidate["reviewResolved"]:
            results.append(TaskAcceptanceResult(**identity, outcome="unverified", reason="review_pending"))
            continue
        media = evidence.media_type.split(";", 1)[0].strip().lower()
        if media != "application/json" and not media.endswith("+json"):
            results.append(TaskAcceptanceResult(**identity, outcome="unverified", reason="unsupported_media_type"))
            continue
        if evidence.byte_length > JSON_CHECK_BYTES:
            results.append(TaskAcceptanceResult(**identity, outcome="unverified", reason="size_limit"))
            continue
        key = (evidence.manifest_id, evidence.checksum)
        if key not in documents:
            manifest = store.get_manifest(evidence.manifest_id)
            if (manifest.kind != ContentKind.ARTIFACT or not manifest.sealed
                    or manifest.owner_type != "run" or manifest.owner_id != evidence.source_run_id
                    or manifest.checksum != evidence.checksum or manifest.byte_length != evidence.byte_length):
                raise ValueError("task acceptance artifact identity does not match its evidence")
            body = bytearray()
            for chunk in store.stream_assembly(manifest.manifest_id):
                if len(body) + len(chunk) > JSON_CHECK_BYTES:
                    raise ValueError("task acceptance content exceeds its declared bounded size")
                body.extend(chunk)
            if len(body) != evidence.byte_length:
                raise ValueError("task acceptance content size differs from its manifest")
            try:
                text = body.decode("utf-8")
                _bounded_json_depth(text)
                documents[key] = (json.loads(text, parse_constant=_reject_json_constant,
                    object_pairs_hook=_unique_object), None)
            except (ValueError, UnicodeDecodeError):
                documents[key] = (None, "invalid_json")
            except RecursionError:
                documents[key] = (None, "parser_limit")
        document, error = documents[key]
        if error:
            results.append(TaskAcceptanceResult(**identity,
                outcome="unverified" if error == "parser_limit" else "failed", reason=error))
            continue
        value = _resolve(document, criterion.pointer)
        numeric = type(value) in {int, float} and (not isinstance(value, float) or math.isfinite(value))
        if value is _MISSING:
            reason, outcome = "pointer_missing", "failed"
        elif criterion.operator == "exists":
            reason, outcome = "matched", "passed"
        elif criterion.operator == "equals":
            same_type = type(value) is type(criterion.expected) or (numeric and type(criterion.expected) in {int, float})
            passed = same_type and value == criterion.expected
            reason, outcome = ("matched", "passed") if passed else ("predicate_false" if same_type else "type_mismatch", "failed")
        elif not numeric:
            reason, outcome = "type_mismatch", "failed"
        else:
            passed = value <= criterion.expected if criterion.operator == "at_most" else value >= criterion.expected
            reason, outcome = ("matched", "passed") if passed else ("predicate_false", "failed")
        results.append(TaskAcceptanceResult(**identity, reason=reason, outcome=outcome))
    return tuple(results)
