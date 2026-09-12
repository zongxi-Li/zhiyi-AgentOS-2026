"""Replaceable storage port for uploaded attachment bytes."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AttachmentStorage(Protocol):
    def put(self, storage_key: str, content: bytes) -> None: ...
    def read(self, storage_key: str) -> bytes: ...
    def delete(self, storage_key: str) -> None: ...
    def exists(self, storage_key: str) -> bool: ...


class LocalAttachmentStorage:
    """Local durable storage constrained to one configured root directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        normalized = storage_key.replace("\\", "/").strip("/")
        if not normalized or any(part in {"", ".", ".."} for part in normalized.split("/")):
            raise ValueError("invalid attachment storage key")
        target = (self.root / normalized).resolve()
        if target == self.root or self.root not in target.parents:
            raise ValueError("attachment storage key escapes configured root")
        return target

    def put(self, storage_key: str, content: bytes) -> None:
        target = self._path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".uploading")
        temporary.write_bytes(bytes(content))
        temporary.replace(target)

    def read(self, storage_key: str) -> bytes:
        return self._path(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        target = self._path(storage_key)
        try:
            target.unlink()
        except FileNotFoundError:
            return

    def exists(self, storage_key: str) -> bool:
        return self._path(storage_key).is_file()


__all__ = ["AttachmentStorage", "LocalAttachmentStorage"]
