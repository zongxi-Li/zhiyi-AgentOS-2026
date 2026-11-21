"""Identity of derived Planner context snapshots in the legacy tool-value store.

Snapshots may contain copies of execution WAL fields. Their sealed address and
ledger owner distinguish this diagnostic view from a new external operation.
"""
from __future__ import annotations

import hashlib

from contracts import stable_checksum


PLANNING_CONTEXT_OWNER = "__planner_context__"
PLANNING_CONTEXT_KEY_PREFIX = "planning-context:"
PLANNING_CONTEXT_METADATA_FIELD = "__planning_context__"
_METADATA_FIELDS = frozenset({"version", "runId", "contextKind", "sourceRunId", "stepId",
    "attemptId", "operationId", "originalRef", "status", "trust"})


def planning_context_key(payload):
    return PLANNING_CONTEXT_KEY_PREFIX + stable_checksum(payload)


def planning_context_reference(run_id, payload):
    return "tool:" + hashlib.sha256((run_id + ":" + planning_context_key(payload)).encode()).hexdigest()


def is_planning_context_snapshot(*, run_id, reference, step_id, kind, operation_id, payload):
    """Recognize only the exact reserved ledger slot and its sealed envelope.

    A payload marker alone grants no exemption from execution reconciliation.
    Invalid or transplanted diagnostic rows remain unexplained activity.
    """
    if (step_id != PLANNING_CONTEXT_OWNER or kind != "output" or operation_id is not None
            or not isinstance(payload, dict)):
        return False
    metadata = payload.get(PLANNING_CONTEXT_METADATA_FIELD)
    if (not isinstance(metadata, dict) or set(metadata) != _METADATA_FIELDS
            or type(metadata.get("version")) is not int or metadata["version"] != 1
            or metadata.get("runId") != run_id or metadata.get("sourceRunId") != run_id
            or any(not isinstance(metadata.get(key), str) or not metadata[key]
                for key in ("contextKind", "status", "trust"))
            or any(metadata.get(key) is not None and (
                not isinstance(metadata[key], str) or not metadata[key])
                for key in ("stepId", "attemptId", "operationId", "originalRef"))):
        return False
    return reference == planning_context_reference(run_id, payload)
