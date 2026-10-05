from __future__ import annotations

import json
import sqlite3

import pytest

from components.content import ContentWorksetSession, SQLiteContentManifestStore
from contracts.content import ContentKind, WorksetSpec


@pytest.mark.parametrize("stored, expected", [
    ("2026-10-04 14:49:39", "2026-10-04T14:49:39Z"),
    ("2026-10-04T22:49:39+08:00", "2026-10-04T14:49:39Z"),
])
def test_manifest_timestamp_is_utc_when_reading_existing_rows(tmp_path, stored, expected):
    path = tmp_path / "content.sqlite3"
    store = SQLiteContentManifestStore(path)
    try:
        manifest = store.create_manifest(kind=ContentKind.ARTIFACT, owner_type="run", owner_id="run-1")
        assert manifest.created_at.utcoffset().total_seconds() == 0
        with sqlite3.connect(path) as db:
            db.execute("UPDATE content_manifests SET created_at = ? WHERE manifest_id = ?",
                       (stored, manifest.manifest_id))
        restored = store.get_manifest(manifest.manifest_id)
        assert restored.model_dump(by_alias=True, mode="json")["createdAt"] == expected
    finally:
        store.close()


def test_large_material_reassembles_exactly_across_cursor_pages(tmp_path) -> None:
    store = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    payload = ("第一段。\n第二段。\n" * 20000).encode("utf-8")
    manifest = store.create_from_bytes(
        content=payload, kind=ContentKind.MATERIAL, owner_type="user", owner_id="u1",
        max_fragment_bytes=1024,
    )

    cursor = None
    rebuilt = bytearray()
    seen = 0
    while True:
        page, cursor = store.read_page(manifest.manifest_id, cursor=cursor, page_size=7)
        for ref, content in page:
            assert ref.sequence == seen
            rebuilt.extend(content)
            seen += 1
        if cursor is None:
            break

    assert bytes(rebuilt) == payload
    assert store.assemble(manifest.manifest_id) == payload
    assert seen == manifest.fragment_count


def test_workset_resumes_from_last_persisted_fragment_without_duplicates(tmp_path) -> None:
    store = SQLiteContentManifestStore(tmp_path / "workset.sqlite3")
    material = store.create_from_bytes(
        content=b"abcdefghij", kind=ContentKind.MATERIAL,
        owner_type="user", owner_id="u1", max_fragment_bytes=2,
    )
    spec = WorksetSpec(sourceManifestRefs=[material.manifest_id])
    first = ContentWorksetSession(
        store=store, spec=spec, run_id="run-1", step_id="extract", commit_id="commit-1"
    )
    units = list(first.pending_units())
    first.persist_map_result(0, {"output": {"part": units[0]["content"]}})
    first.persist_map_result(1, {"output": {"part": units[1]["content"]}})

    resumed = ContentWorksetSession(
        store=store, spec=spec, run_id="run-1", step_id="extract", commit_id="commit-1"
    )
    pending = list(resumed.pending_units())

    assert [item["sequence"] for item in pending] == [2, 3, 4]
    assert len(resumed.mapped_results()) == 2
    with pytest.raises(ValueError, match="idempotency conflict"):
        resumed.store.append_fragment(
            manifest_id=resumed.result_manifest.manifest_id,
            sequence=0,
            content=json.dumps({"different": True}).encode(),
        )


def test_thousand_fragment_workset_restart_has_no_gap_or_duplicate(tmp_path) -> None:
    store = SQLiteContentManifestStore(tmp_path / "thousand.sqlite3")
    material = store.create_from_bytes(
        content=b"x" * 1000,
        kind=ContentKind.MATERIAL,
        owner_type="user",
        owner_id="u1",
        max_fragment_bytes=1,
    )
    spec = WorksetSpec(sourceManifestRefs=[material.manifest_id])
    first = ContentWorksetSession(
        store=store, spec=spec, run_id="run-large", step_id="map", commit_id="commit-large"
    )
    for unit in list(first.pending_units())[:437]:
        first.persist_map_result(unit["sequence"], {"output": {"sequence": unit["sequence"]}})

    resumed = ContentWorksetSession(
        store=store, spec=spec, run_id="run-large", step_id="map", commit_id="commit-large"
    )
    assert [item["sequence"] for item in resumed.pending_units()][:2] == [437, 438]
    for unit in resumed.pending_units():
        resumed.persist_map_result(unit["sequence"], {"output": {"sequence": unit["sequence"]}})
    sealed = resumed.seal()

    results = resumed.mapped_results()
    assert sealed.fragment_count == 1000
    assert [item["output"]["sequence"] for item in results] == list(range(1000))
