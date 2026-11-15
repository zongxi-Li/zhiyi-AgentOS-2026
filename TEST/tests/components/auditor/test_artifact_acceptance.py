"""Independent checks use real manifests, including corruption beyond previews."""

import sqlite3

import pytest

from components.auditor.artifact_acceptance import inspect_artifact, JSON_CHECK_BYTES
from components.content import SQLiteContentManifestStore
from contracts.content import ContentKind


def inspect(tmp_path, body, media="text/markdown", *, budget=8192, reviewed=True):
    store = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    manifest = store.create_from_bytes(content=body, kind=ContentKind.ARTIFACT,
        owner_type="run", owner_id="source", media_type=media,
        max_fragment_bytes=17 if len(body) < 16384 else 65536)
    evidence, used = inspect_artifact(store=store,
        artifact={"manifestId": manifest.manifest_id, "checksum": manifest.checksum},
        owner_id="source", commit_id="commit:source:A:1", excerpt_budget=budget,
        review_resolved=reviewed)
    store.close()
    return evidence, used


@pytest.mark.parametrize("body,media,failed", [
    (b" \n\t", "text/plain", "nonempty_content"),
    (b"okay\xff", "text/plain", "utf8_text"),
    (b'{"score": }', "application/json", "json_syntax"),
    (b'{"score": NaN}', "application/json", "json_syntax"),
])
def test_independent_checks_reject_false_success(tmp_path, body, media, failed):
    evidence, _ = inspect(tmp_path, body, media)
    assert any(c.check == failed and c.outcome == "failed" for c in evidence.checks)
    assert evidence.business_acceptance == "unverified"


def test_utf8_preview_is_bounded_without_replacement_characters(tmp_path):
    evidence, used = inspect(tmp_path, ("证据" * 1000).encode())
    assert used <= 2048 and used == len(evidence.excerpt.encode())
    assert evidence.excerpt_truncated and "\ufffd" not in evidence.excerpt
    assert all(c.outcome == "passed" for c in evidence.checks)
    assert evidence.source_run_id == "source" and evidence.commit_id == "commit:source:A:1"


@pytest.mark.parametrize("media,budget,reviewed,status", [
    ("application/octet-stream", 8192, True, "not_text"),
    ("text/plain", 0, True, "budget_exhausted"),
    ("text/plain", 8192, False, "review_pending"),
])
def test_unapproved_or_unavailable_preview_never_releases_text(tmp_path, media, budget, reviewed, status):
    evidence, used = inspect(tmp_path, b"private content", media, budget=budget, reviewed=reviewed)
    assert evidence.excerpt == "" and used == 0 and evidence.excerpt_status == status


def test_large_json_is_not_reported_as_valid_when_parser_budget_is_exceeded(tmp_path):
    evidence, _ = inspect(tmp_path, b'"' + b"a" * JSON_CHECK_BYTES + b'"', "application/json")
    assert next(c.outcome for c in evidence.checks if c.check == "json_syntax") == "unverified"
    assert evidence.excerpt_truncated


def test_json_validation_reads_content_beyond_the_excerpt(tmp_path):
    evidence, _ = inspect(tmp_path, b" " * 2200 + b'{"ok":true}', "application/json")
    assert not evidence.excerpt.strip() and evidence.excerpt_truncated
    assert all(c.outcome == "passed" for c in evidence.checks)


def test_reader_rejects_cross_run_and_corrupt_tail_before_exposing_preview(tmp_path):
    path = tmp_path / "content.sqlite3"
    store = SQLiteContentManifestStore(path)
    manifest = store.create_from_bytes(content=b"safe prefix" + b"a" * 3000,
        kind=ContentKind.ARTIFACT, owner_type="run", owner_id="source", max_fragment_bytes=1000)
    request = dict(store=store, artifact={"manifestId": manifest.manifest_id, "checksum": manifest.checksum},
        commit_id="commit:source:A:1", excerpt_budget=2048, review_resolved=True)
    with pytest.raises(ValueError, match="ownership"):
        inspect_artifact(**request, owner_id="another-run")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE content_fragments SET content = ? WHERE manifest_id = ? AND sequence = 3",
            (b"corrupt tail", manifest.manifest_id))
    with pytest.raises(ValueError, match="checksum"):
        inspect_artifact(**request, owner_id="source")
    store.close()
