"""Direct filesystem capabilities; no shell or git subprocesses are used."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from runtime.errors import FileOperationError, PatchConflictError
from workspace import CanonicalWorkspaceResolver


@dataclass(frozen=True)
class FileSystemPolicy:
    max_read_bytes: int = 4 * 1024 * 1024
    max_write_bytes: int = 4 * 1024 * 1024
    max_list_entries: int = 10_000

    def __post_init__(self) -> None:
        if self.max_read_bytes < 1 or self.max_write_bytes < 1 or self.max_list_entries < 1:
            raise ValueError("filesystem limits must be positive")


class FilesystemCapabilities:
    def __init__(
        self,
        resolver: CanonicalWorkspaceResolver,
        *,
        policy: FileSystemPolicy | None = None,
    ) -> None:
        self.resolver = resolver
        self.policy = policy or FileSystemPolicy()

    def read(self, root: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, self._path(arguments), must_exist=True)
        if not resolved.target.is_file():
            raise FileOperationError("FILE_NOT_REGULAR", "requested path is not a regular file")
        data = self._read_bounded(resolved.target, self.policy.max_read_bytes)
        binary = bool(arguments.get("binary", False))
        if binary:
            content = base64.b64encode(data).decode("ascii")
            encoding = "base64"
        else:
            encoding = str(arguments.get("encoding") or "utf-8")
            try:
                content = data.decode(encoding)
            except (LookupError, UnicodeDecodeError) as exc:
                raise FileOperationError("FILE_ENCODING_INVALID", "file encoding is invalid") from exc
        return {
            "path": resolved.relative_path,
            "encoding": encoding,
            "content": content,
            "sizeBytes": len(data),
        }

    def list(self, root: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, self._path(arguments), must_exist=True)
        if not resolved.target.is_dir():
            raise FileOperationError("DIRECTORY_REQUIRED", "requested path is not a directory")
        requested_limit = int(arguments.get("maxEntries") or self.policy.max_list_entries)
        if requested_limit < 1 or requested_limit > self.policy.max_list_entries:
            raise FileOperationError("LIST_LIMIT_EXCEEDED", "directory entry limit is invalid")
        children = sorted(resolved.target.iterdir(), key=lambda item: item.name.casefold())
        if len(children) > requested_limit:
            raise FileOperationError("LIST_LIMIT_EXCEEDED", "directory contains too many entries")
        entries: list[dict[str, Any]] = []
        for child in children:
            checked = self.resolver.resolve(root, child, must_exist=True)
            entries.append({
                "path": checked.relative_path,
                "name": child.name,
                "type": "directory" if checked.target.is_dir() else "file",
            })
        return {"path": resolved.relative_path, "entries": entries, "count": len(entries)}

    def write(self, root: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, self._path(arguments), must_exist=False)
        overwrite = self._required_bool(arguments, "overwrite")
        create_parents = bool(arguments.get("createParents", False))
        existed_before = resolved.target.exists()
        if existed_before and not overwrite:
            raise FileOperationError("FILE_EXISTS", "target file already exists")
        if existed_before and not resolved.target.is_file():
            raise FileOperationError("FILE_NOT_REGULAR", "target path is not a regular file")
        data = self._decode_content(arguments)
        if len(data) > self.policy.max_write_bytes:
            raise FileOperationError("FILE_SIZE_LIMIT_EXCEEDED", "file exceeds the write limit")
        if not resolved.target.parent.exists():
            if not create_parents:
                raise FileOperationError("PARENT_NOT_FOUND", "target parent does not exist")
            resolved.target.parent.mkdir(parents=True, exist_ok=True)
        parent = resolved.target.parent.resolve(strict=True)
        if not self.resolver._contained(resolved.root, parent):
            raise FileOperationError("PATH_OUTSIDE_WORKSPACE", "target parent is outside workspace")
        # Re-resolve after creating parents to catch a symlink/reparse escape.
        checked = self.resolver.resolve(root, self._path(arguments), must_exist=False)
        self._atomic_write(checked.target, data)
        return {"path": checked.relative_path, "sizeBytes": len(data), "overwritten": existed_before}

    def patch(self, root: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, self._path(arguments), must_exist=True)
        if not resolved.target.is_file():
            raise FileOperationError("FILE_NOT_REGULAR", "patch target is not a regular file")
        original = self._read_bounded(resolved.target, self.policy.max_read_bytes)
        expected = str(arguments.get("expectedSha256") or "").strip()
        if expected and hashlib.sha256(original).hexdigest() != expected:
            raise PatchConflictError()
        encoding = str(arguments.get("encoding") or "utf-8")
        try:
            source = original.decode(encoding)
            patch_text = str(arguments.get("patch") or "")
            updated = apply_unified_patch(source, patch_text).encode(encoding)
        except PatchConflictError:
            raise
        except (LookupError, UnicodeError) as exc:
            raise FileOperationError("PATCH_ENCODING_INVALID", "patch encoding is invalid") from exc
        if len(updated) > self.policy.max_write_bytes:
            raise FileOperationError("FILE_SIZE_LIMIT_EXCEEDED", "patched file exceeds the write limit")
        # The target is canonicalized again immediately before mutation.
        checked = self.resolver.resolve(root, self._path(arguments), must_exist=True)
        if checked.target != resolved.target:
            raise PatchConflictError()
        self._atomic_write(checked.target, updated)
        return {
            "path": checked.relative_path,
            "sizeBytes": len(updated),
            "sha256": hashlib.sha256(updated).hexdigest(),
        }

    @staticmethod
    def _path(arguments: Mapping[str, Any]) -> str:
        value = str(arguments.get("path") or "").strip()
        if not value:
            raise FileOperationError("PATH_INVALID", "path is required")
        return value

    @staticmethod
    def _required_bool(arguments: Mapping[str, Any], name: str) -> bool:
        value = arguments.get(name)
        if not isinstance(value, bool):
            raise FileOperationError("INPUT_INVALID", f"{name} must be explicit")
        return value

    def _decode_content(self, arguments: Mapping[str, Any]) -> bytes:
        content = arguments.get("content")
        if not isinstance(content, str):
            raise FileOperationError("INPUT_INVALID", "content must be a string")
        if arguments.get("binary", False):
            try:
                return base64.b64decode(content, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise FileOperationError("CONTENT_INVALID", "base64 content is invalid") from exc
        encoding = str(arguments.get("encoding") or "utf-8")
        try:
            return content.encode(encoding)
        except (LookupError, UnicodeError) as exc:
            raise FileOperationError("CONTENT_ENCODING_INVALID", "content encoding is invalid") from exc

    def _read_bounded(self, path: Path, limit: int) -> bytes:
        try:
            size = path.stat().st_size
            if size > limit:
                raise FileOperationError("FILE_SIZE_LIMIT_EXCEEDED", "file exceeds the read limit")
            return path.read_bytes()
        except FileOperationError:
            raise
        except (OSError, ValueError) as exc:
            raise FileOperationError("FILE_READ_FAILED", "file could not be read") from exc

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
            ) as handle:
                temporary = handle.name
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as exc:
            raise FileOperationError("FILE_WRITE_FAILED", "file could not be written") from exc
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def apply_unified_patch(source: str, patch_text: str) -> str:
    """Apply exact single-file unified hunks without invoking a patch utility."""
    lines = source.splitlines(keepends=True)
    patch_lines = patch_text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in source else "\n"
    hunks: list[tuple[int, int, list[str]]] = []
    index = 0
    while index < len(patch_lines):
        line = patch_lines[index]
        if not line.startswith("@@"):
            index += 1
            continue
        try:
            header = line.split("@@", 2)[1].strip()
            old_part, new_part = header.split(" ", 1)
            old_start, old_count = _parse_hunk_range(old_part, "-")
            _new_start, _new_count = _parse_hunk_range(new_part, "+")
        except (IndexError, ValueError) as exc:
            raise PatchConflictError() from exc
        index += 1
        body: list[str] = []
        while index < len(patch_lines) and not patch_lines[index].startswith("@@"):
            item = patch_lines[index]
            if item.startswith((" ", "+", "-")):
                body.append(item)
            elif item.startswith("\\ No newline"):
                pass
            elif item.startswith(("---", "+++")) and not body:
                pass
            else:
                raise PatchConflictError()
            index += 1
        hunks.append((old_start, old_count, _new_count, body))
    if not hunks:
        raise PatchConflictError()
    offset = 0
    for old_start, old_count, new_count, body in hunks:
        position = (0 if old_start == 0 else old_start - 1) + offset
        old_lines: list[str] = []
        new_lines: list[str] = []
        for item in body:
            if item.startswith(" "):
                content = _normalize_patch_line(item[1:], newline)
                old_lines.append(content)
                new_lines.append(content)
            elif item.startswith("-"):
                old_lines.append(_normalize_patch_line(item[1:], newline))
            elif item.startswith("+"):
                new_lines.append(_normalize_patch_line(item[1:], newline))
        if (
            len(old_lines) != old_count
            or len(new_lines) != new_count
            or lines[position:position + old_count] != old_lines
        ):
            raise PatchConflictError()
        lines[position:position + old_count] = new_lines
        offset += len(new_lines) - old_count
    return "".join(lines)


def _parse_hunk_range(value: str, marker: str) -> tuple[int, int]:
    if not value.startswith(marker):
        raise ValueError("invalid hunk marker")
    raw = value[1:]
    if "," in raw:
        start, count = raw.split(",", 1)
        return int(start), int(count)
    return int(raw), 1


def _normalize_patch_line(value: str, newline: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.endswith("\n"):
        return normalized[:-1] + newline
    return normalized


__all__ = ["FileSystemPolicy", "FilesystemCapabilities", "apply_unified_patch"]
