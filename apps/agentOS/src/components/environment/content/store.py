"""SQLite manifest/fragment persistence with exact deterministic assembly."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from hashlib import sha256
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Protocol
from uuid import uuid4

from contracts.content import (
    ContentFragmentRef,
    ContentKind,
    ContentManifest,
    VerificationStatus,
)


def _estimated_tokens(byte_length: int) -> int:
    # Display-only estimate. It never controls model input or output.
    return (byte_length + 3) // 4


class ContentManifestStore(Protocol):
    def create_manifest(
        self, *, kind: ContentKind, owner_type: str, owner_id: str,
        media_type: str = "text/plain", chunking_version: str = "content-bytes.v1",
        manifest_id: str | None = None,
    ) -> ContentManifest: ...

    def append_fragment(
        self, *, manifest_id: str, content: bytes, sequence: int | None = None,
        source_refs: Iterable[str] = (), constraint_refs: Iterable[str] = (),
        verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
    ) -> ContentFragmentRef: ...

    def seal_manifest(self, manifest_id: str) -> ContentManifest: ...
    def get_manifest(self, manifest_id: str) -> ContentManifest: ...
    def read_fragment(self, manifest_id: str, sequence: int) -> tuple[ContentFragmentRef, bytes]: ...
    def create_from_bytes(
        self, *, content: bytes, kind: ContentKind, owner_type: str, owner_id: str,
        media_type: str = "text/plain", max_fragment_bytes: int = 65536,
        chunking_version: str = "content-bytes.v1",
    ) -> ContentManifest: ...
    def list_manifests(
        self, *, owner_type: str, owner_id: str, kind: ContentKind | None = None,
    ) -> list[ContentManifest]: ...
    def read_page(
        self, manifest_id: str, *, cursor: str | None = None, page_size: int = 20,
    ) -> tuple[list[tuple[ContentFragmentRef, bytes]], str | None]: ...
    def iterate_fragments(
        self, manifest_id: str, *, cursor: str | None = None,
    ) -> Iterator[tuple[ContentFragmentRef, bytes]]: ...
    def stream_assembly(self, manifest_id: str) -> Iterator[bytes]: ...
    def assemble(self, manifest_id: str) -> bytes: ...
    def close(self) -> None: ...


class SQLiteContentManifestStore:
    """Append-only content store; referenced fragments are never silently pruned."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._db:
            self._db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS content_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    checksum TEXT,
                    byte_length INTEGER NOT NULL DEFAULT 0,
                    fragment_count INTEGER NOT NULL DEFAULT 0,
                    estimated_tokens INTEGER,
                    chunking_version TEXT NOT NULL,
                    sealed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_content_manifest_owner
                    ON content_manifests(owner_type, owner_id, kind);
                CREATE TABLE IF NOT EXISTS content_fragments (
                    manifest_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    fragment_id TEXT NOT NULL UNIQUE,
                    checksum TEXT NOT NULL,
                    byte_length INTEGER NOT NULL,
                    estimated_tokens INTEGER,
                    source_refs TEXT NOT NULL DEFAULT '',
                    constraint_refs TEXT NOT NULL DEFAULT '',
                    verification_status TEXT NOT NULL,
                    content BLOB NOT NULL,
                    PRIMARY KEY(manifest_id, sequence),
                    FOREIGN KEY(manifest_id) REFERENCES content_manifests(manifest_id)
                );
                """
            )

    def close(self) -> None:
        self._db.close()

    def create_manifest(
        self, *, kind: ContentKind, owner_type: str, owner_id: str,
        media_type: str = "text/plain", chunking_version: str = "content-bytes.v1",
        manifest_id: str | None = None,
    ) -> ContentManifest:
        manifest_id = manifest_id or f"manifest_{uuid4().hex}"
        with self._lock, self._db:
            existing = self._db.execute(
                "SELECT * FROM content_manifests WHERE manifest_id = ?", (manifest_id,)
            ).fetchone()
            if existing is not None:
                current = self._manifest(existing)
                if (
                    current.kind is not kind
                    or current.owner_type != owner_type
                    or current.owner_id != owner_id
                    or current.media_type != media_type
                    or current.chunking_version != chunking_version
                ):
                    raise ValueError("content manifest identity conflict")
                return current
            self._db.execute(
                """INSERT INTO content_manifests
                (manifest_id, kind, owner_type, owner_id, media_type, chunking_version)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (manifest_id, kind.value, owner_type, owner_id, media_type, chunking_version),
            )
        return self.get_manifest(manifest_id)

    def create_from_bytes(
        self, *, content: bytes, kind: ContentKind, owner_type: str, owner_id: str,
        media_type: str = "text/plain", max_fragment_bytes: int = 65536,
        chunking_version: str = "content-bytes.v1",
    ) -> ContentManifest:
        if max_fragment_bytes < 1:
            raise ValueError("max_fragment_bytes must be positive")
        manifest = self.create_manifest(
            kind=kind, owner_type=owner_type, owner_id=owner_id,
            media_type=media_type, chunking_version=chunking_version,
        )
        if content:
            for sequence, offset in enumerate(range(0, len(content), max_fragment_bytes)):
                self.append_fragment(
                    manifest_id=manifest.manifest_id,
                    sequence=sequence,
                    content=content[offset:offset + max_fragment_bytes],
                )
        return self.seal_manifest(manifest.manifest_id)

    def append_fragment(
        self, *, manifest_id: str, content: bytes, sequence: int | None = None,
        source_refs: Iterable[str] = (), constraint_refs: Iterable[str] = (),
        verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
    ) -> ContentFragmentRef:
        payload = bytes(content)
        checksum = sha256(payload).hexdigest()
        with self._lock, self._db:
            manifest = self._manifest_row(manifest_id)
            if manifest["sealed"]:
                raise ValueError("cannot append to a sealed ContentManifest")
            count = self._db.execute(
                "SELECT COUNT(*) FROM content_fragments WHERE manifest_id = ?", (manifest_id,)
            ).fetchone()[0]
            target = count if sequence is None else sequence
            if target < 0:
                raise ValueError("fragment sequence must not be negative")
            existing = self._db.execute(
                "SELECT * FROM content_fragments WHERE manifest_id = ? AND sequence = ?",
                (manifest_id, target),
            ).fetchone()
            if existing is not None:
                if existing["checksum"] != checksum:
                    raise ValueError("fragment idempotency conflict")
                return self._fragment_ref(existing)
            if target != count:
                raise ValueError("fragments must be appended in sequence")
            fragment_id = "fragment_" + sha256(
                f"{manifest_id}:{target}:{checksum}".encode("utf-8")
            ).hexdigest()[:32]
            self._db.execute(
                """INSERT INTO content_fragments
                (manifest_id, sequence, fragment_id, checksum, byte_length,
                 estimated_tokens, source_refs, constraint_refs, verification_status, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    manifest_id, target, fragment_id, checksum, len(payload),
                    _estimated_tokens(len(payload)), "\n".join(source_refs),
                    "\n".join(constraint_refs), verification_status.value, payload,
                ),
            )
            new_total = int(manifest["byte_length"]) + len(payload)
            self._db.execute(
                """UPDATE content_manifests SET byte_length = ?, fragment_count = ?,
                estimated_tokens = ? WHERE manifest_id = ?""",
                (new_total, count + 1, _estimated_tokens(new_total), manifest_id),
            )
        return self.read_fragment(manifest_id, target)[0]

    def seal_manifest(self, manifest_id: str) -> ContentManifest:
        digest = sha256()
        total = 0
        count = 0
        with self._lock, self._db:
            manifest = self._manifest_row(manifest_id)
            if manifest["sealed"]:
                return self._manifest(manifest)
            rows = self._db.execute(
                "SELECT content FROM content_fragments WHERE manifest_id = ? ORDER BY sequence",
                (manifest_id,),
            ).fetchall()
            for row in rows:
                payload = bytes(row["content"])
                digest.update(payload)
                total += len(payload)
                count += 1
            self._db.execute(
                """UPDATE content_manifests SET checksum = ?, byte_length = ?,
                fragment_count = ?, estimated_tokens = ?, sealed = 1 WHERE manifest_id = ?""",
                (digest.hexdigest(), total, count, _estimated_tokens(total), manifest_id),
            )
        return self.get_manifest(manifest_id)

    def get_manifest(self, manifest_id: str) -> ContentManifest:
        with self._lock:
            return self._manifest(self._manifest_row(manifest_id))

    def list_manifests(
        self, *, owner_type: str, owner_id: str, kind: ContentKind | None = None,
    ) -> list[ContentManifest]:
        sql = "SELECT * FROM content_manifests WHERE owner_type = ? AND owner_id = ?"
        params: list[object] = [owner_type, owner_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        sql += " ORDER BY created_at, manifest_id"
        with self._lock:
            return [self._manifest(row) for row in self._db.execute(sql, params).fetchall()]

    def read_fragment(self, manifest_id: str, sequence: int) -> tuple[ContentFragmentRef, bytes]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM content_fragments WHERE manifest_id = ? AND sequence = ?",
                (manifest_id, sequence),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown content fragment: {manifest_id}/{sequence}")
            return self._fragment_ref(row), bytes(row["content"])

    def read_page(
        self, manifest_id: str, *, cursor: str | None = None, page_size: int = 20,
    ) -> tuple[list[tuple[ContentFragmentRef, bytes]], str | None]:
        if page_size < 1 or page_size > 200:
            raise ValueError("page_size must be between 1 and 200")
        try:
            start = int(cursor or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("cursor must be a non-negative fragment sequence") from exc
        if start < 0:
            raise ValueError("cursor must not be negative")
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM content_fragments WHERE manifest_id = ? AND sequence >= ?
                ORDER BY sequence LIMIT ?""",
                (manifest_id, start, page_size + 1),
            ).fetchall()
        page_rows = rows[:page_size]
        page = [(self._fragment_ref(row), bytes(row["content"])) for row in page_rows]
        next_cursor = str(page_rows[-1]["sequence"] + 1) if len(rows) > page_size else None
        return page, next_cursor

    def iterate_fragments(self, manifest_id: str, *, cursor: str | None = None) -> Iterator[tuple[ContentFragmentRef, bytes]]:
        next_cursor = cursor
        while True:
            page, following = self.read_page(manifest_id, cursor=next_cursor, page_size=100)
            yield from page
            if following is None:
                return
            next_cursor = following

    def stream_assembly(self, manifest_id: str) -> Iterator[bytes]:
        manifest = self.get_manifest(manifest_id)
        if not manifest.sealed:
            raise ValueError("cannot assemble an unsealed ContentManifest")
        digest = sha256()
        for _ref, payload in self.iterate_fragments(manifest_id):
            digest.update(payload)
            yield payload
        if digest.hexdigest() != manifest.checksum:
            raise ValueError("assembled content checksum mismatch")

    def assemble(self, manifest_id: str) -> bytes:
        return b"".join(self.stream_assembly(manifest_id))

    def _manifest_row(self, manifest_id: str) -> sqlite3.Row:
        row = self._db.execute(
            "SELECT * FROM content_manifests WHERE manifest_id = ?", (manifest_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown content manifest: {manifest_id}")
        return row

    @staticmethod
    def _manifest(row: sqlite3.Row) -> ContentManifest:
        return ContentManifest(
            manifestId=row["manifest_id"], kind=row["kind"], ownerType=row["owner_type"],
            ownerId=row["owner_id"], mediaType=row["media_type"], checksum=row["checksum"],
            byteLength=row["byte_length"], fragmentCount=row["fragment_count"],
            estimatedTokens=row["estimated_tokens"], chunkingVersion=row["chunking_version"],
            sealed=bool(row["sealed"]), createdAt=row["created_at"],
        )

    @staticmethod
    def _fragment_ref(row: sqlite3.Row) -> ContentFragmentRef:
        return ContentFragmentRef(
            fragmentId=row["fragment_id"], manifestId=row["manifest_id"],
            sequence=row["sequence"], checksum=row["checksum"], byteLength=row["byte_length"],
            estimatedTokens=row["estimated_tokens"],
            sourceRefs=tuple(filter(None, row["source_refs"].split("\n"))),
            constraintRefs=tuple(filter(None, row["constraint_refs"].split("\n"))),
            verificationStatus=row["verification_status"], complete=True,
        )


__all__ = ["ContentManifestStore", "SQLiteContentManifestStore"]
