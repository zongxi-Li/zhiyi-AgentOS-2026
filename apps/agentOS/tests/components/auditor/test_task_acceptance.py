"""Caller requirements are checked independently of executor success statements."""

import pytest
import json
import sys
from types import SimpleNamespace
from pydantic import ValidationError

from components.auditor.artifact_acceptance import inspect_artifact, JSON_CHECK_BYTES
from components.auditor.task_acceptance import evaluate_task_acceptance
from components.content import SQLiteContentManifestStore
from contracts.content import ContentKind
from contracts.task_acceptance import TaskAcceptanceSpec, frozen_task_acceptance


def spec(*criteria):
    return TaskAcceptanceSpec(criteria=criteria)


def candidate(store, body, *, media="application/json", reviewed=True):
    manifest = store.create_from_bytes(content=body, kind=ContentKind.ARTIFACT,
        owner_type="run", owner_id="source", media_type=media)
    evidence, _ = inspect_artifact(store=store,
        artifact={"manifestId": manifest.manifest_id, "checksum": manifest.checksum},
        owner_id="source", commit_id="commit:source:B:1", excerpt_budget=0,
        review_resolved=reviewed)
    return {"artifactKey": "final", "taskKey": "deliver", "evidence": evidence, "reviewResolved": reviewed}


@pytest.mark.parametrize("criterion", [
    {"pointer": "status", "operator": "exists"},
    {"pointer": "/a~2", "operator": "exists"},
    {"pointer": "/status", "operator": "equals"},
    {"pointer": "/cost", "operator": "at_most", "expected": True},
    {"pointer": "/cost", "operator": "at_most", "expected": "100"},
    {"pointer": "/cost", "operator": "at_most", "expected": float("inf")},
    {"pointer": "/cost", "operator": "execute", "expected": "code"},
])
def test_invalid_or_executable_predicates_are_rejected(criterion):
    with pytest.raises(ValidationError):
        spec({"criterionId": "requirement", **criterion})


def test_duplicate_requirement_ids_are_rejected():
    c = {"criterionId": "same", "pointer": "/status", "operator": "exists"}
    with pytest.raises(ValidationError, match="unique"):
        spec(c, c)


def test_frozen_predicate_rejects_boolean_numeric_substitution():
    admitted = spec({"criterionId": "enabled", "pointer": "/enabled", "operator": "equals", "expected": True})
    changed = spec({"criterionId": "enabled", "pointer": "/enabled", "operator": "equals", "expected": 1})
    run = SimpleNamespace(execution_state={"taskAcceptance": admitted.model_dump(by_alias=True, mode="json")},
        input={"taskAcceptance": changed.model_dump(by_alias=True, mode="json")})
    with pytest.raises(ValueError, match="changed after Run admission"):
        frozen_task_acceptance(run)


def test_pointer_types_ranges_and_null_presence_use_full_committed_document(tmp_path):
    store = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    criteria = [
        ("status", "/status", "equals", "ready", "passed"),
        ("range", "/cost", "at_most", 100, "failed"),
        ("boolean", "/enabled", "equals", 1, "failed"),
        ("escape", "/a~1b/~0/0", "equals", "evidence", "passed"),
        ("null", "/present", "exists", None, "passed"),
        ("null-equality", "/present", "equals", None, "passed"),
        ("missing", "/absent", "exists", None, "failed"),
        ("array-index", "/a~1b/~0/00", "exists", None, "failed"),
        ("minimum", "/cost", "at_least", 100, "passed"),
    ]
    requirements = spec(*({"criterionId": name, "pointer": pointer, "operator": op,
        **({"expected": expected} if op != "exists" else {})} for name, pointer, op, expected, _ in criteria))
    item = candidate(store, b" " * 2200 + b'{"status":"ready","cost":101,"enabled":true,"a/b":{"~":["evidence"]},"present":null}')
    results = evaluate_task_acceptance(store=store, spec=requirements, candidates=[item])
    assert [r.outcome for r in results] == [c[-1] for c in criteria]
    assert all(r.source_run_id == "source" and r.commit_id == "commit:source:B:1" and r.checksum for r in results)
    assert all(r.scope == "document_requirement" for r in results)
    assert item["evidence"].excerpt == ""
    store.close()


@pytest.mark.parametrize("body,media,reviewed,outcome,reason", [
    (b'{"status":"ready","status":"wrong"}', "application/json", True, "failed", "invalid_json"),
    (b'{"status":NaN}', "application/json", True, "failed", "invalid_json"),
    (b'{"status":"ready"}', "text/plain", True, "unverified", "unsupported_media_type"),
    (b'{"status":"ready"}', "application/json", False, "unverified", "review_pending"),
    (b'"' + b"a" * JSON_CHECK_BYTES + b'"', "application/json", True, "unverified", "size_limit"),
    (b"[" * 1200 + b"0" + b"]" * 1200, "application/json", True, "unverified", "parser_limit"),
], ids=["duplicate-key", "nan", "wrong-media", "review-pending", "size-limit", "depth-limit"])
def test_ambiguous_unsupported_or_unapproved_evidence_cannot_pass(tmp_path, body, media, reviewed, outcome, reason):
    store = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    item = candidate(store, body, media=media, reviewed=reviewed)
    requirement = spec({"criterionId": "status", "pointer": "/status", "operator": "equals", "expected": "ready"})
    result, = evaluate_task_acceptance(store=store, spec=requirement, candidates=[item])
    assert (result.outcome, result.reason) == (outcome, reason)
    store.close()


def test_missing_or_ambiguous_target_is_unverified_and_semantic_key_disambiguates(tmp_path):
    store = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    item = candidate(store, b'{"status":"ready"}')
    other = {**item, "taskKey": "other"}
    c = {"criterionId": "status", "pointer": "/status", "operator": "exists"}
    missing, = evaluate_task_acceptance(store=store, spec=spec(c), candidates=[])
    ambiguous, = evaluate_task_acceptance(store=store, spec=spec(c), candidates=[item, other])
    scoped, = evaluate_task_acceptance(store=store, spec=spec({**c, "taskKey": "deliver"}), candidates=[item, other])
    assert missing.reason == "artifact_missing" and ambiguous.reason == "artifact_ambiguous"
    assert scoped.outcome == "passed"
    store.close()


def test_document_depth_limit_is_independent_of_process_recursion_and_ignores_strings(tmp_path):
    store = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    requirement = spec({"criterionId": "status", "pointer": "/status", "operator": "exists"})
    previous = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(max(previous, 5000))
        nested = candidate(store, b"[" * 1200 + b"0" + b"]" * 1200)
        result, = evaluate_task_acceptance(store=store, spec=requirement, candidates=[nested])
        assert (result.outcome, result.reason) == ("unverified", "parser_limit")
        quoted = candidate(store, json.dumps({"status": '[\\"' * 1200}).encode())
        result, = evaluate_task_acceptance(store=store, spec=requirement, candidates=[quoted])
        assert result.outcome == "passed"
    finally:
        sys.setrecursionlimit(previous)
        store.close()
