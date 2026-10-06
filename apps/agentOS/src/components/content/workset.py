"""Cursor-backed worksets executed inside one semantic ACG step."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Iterator

from contracts.content import ContentKind, WorksetSpec

from .store import ContentManifestStore


class MaterialSourceError(ValueError):
    """An executable workset cannot read its declared input material."""

    def __init__(self, manifest_id: str, reason: str, step_id: str) -> None:
        self.manifest_id = manifest_id
        self.step_id = step_id
        super().__init__(f"Workset material {manifest_id}: {reason}")


class ContentWorksetSession:
    """Restrict a node to declared sources and persist map results idempotently."""

    def __init__(
        self, *, store: ContentManifestStore, spec: WorksetSpec,
        run_id: str, step_id: str, commit_id: str,
    ) -> None:
        self.store = store
        self.spec = spec
        self.step_id = step_id
        # Preflight the whole set before creating results or executing a unit,
        # including restored Runs. Never partially process an invalid set.
        for manifest_id in spec.source_manifest_refs:
            self._material(manifest_id)
        stable = sha256(f"workset:{run_id}:{step_id}:{commit_id}".encode("utf-8")).hexdigest()[:32]
        self.result_manifest = store.create_manifest(
            manifest_id=f"manifest_{stable}", kind=ContentKind.INTERMEDIATE,
            owner_type="run", owner_id=run_id, media_type="application/json",
            chunking_version="workset-map.v1",
        )

    def mapped_results(self) -> list[dict[str, Any]]:
        return [
            json.loads(payload.decode("utf-8"))
            for _ref, payload in self.store.iterate_fragments(self.result_manifest.manifest_id)
        ]

    def _material(self, manifest_id: str):
        try:
            manifest = self.store.get_manifest(manifest_id)
        except KeyError as exc:
            raise MaterialSourceError(manifest_id, "not found", self.step_id) from exc
        if manifest.kind is not ContentKind.MATERIAL or not manifest.sealed:
            raise MaterialSourceError(manifest_id, "must be a sealed material manifest", self.step_id)
        return manifest

    def pending_units(self) -> Iterator[dict[str, Any]]:
        completed = self.result_manifest.fragment_count
        global_sequence = 0
        for manifest_id in self.spec.source_manifest_refs:
            self._material(manifest_id)
            for ref, payload in self.store.iterate_fragments(manifest_id):
                if global_sequence >= completed:
                    yield {
                        "sequence": global_sequence,
                        "manifestId": manifest_id,
                        "fragmentRef": ref.model_dump(by_alias=True, mode="json"),
                        "content": payload.decode("utf-8", errors="strict"),
                    }
                global_sequence += 1

    def persist_map_result(self, sequence: int, value: dict[str, Any]) -> None:
        self.store.append_fragment(
            manifest_id=self.result_manifest.manifest_id, sequence=sequence,
            content=json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            source_refs=self.spec.source_manifest_refs,
        )
        self.result_manifest = self.store.get_manifest(self.result_manifest.manifest_id)

    def seal(self):
        self.result_manifest = self.store.seal_manifest(self.result_manifest.manifest_id)
        return self.result_manifest


__all__ = ["ContentWorksetSession"]
