"""Windows-aware workspace containment and canonical path resolution."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from runtime.errors import PathPolicyError


@dataclass(frozen=True)
class ResolvedWorkspacePath:
    root: Path
    target: Path
    relative_path: str
    exists: bool


class CanonicalWorkspaceResolver:
    """Resolve existing and new targets without string-prefix containment."""

    def canonicalize_root(self, root: str | os.PathLike[str]) -> Path:
        candidate = Path(root).expanduser()
        try:
            canonical = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PathPolicyError("WORKSPACE_ROOT_INVALID") from exc
        if not canonical.is_dir():
            raise PathPolicyError("WORKSPACE_ROOT_INVALID")
        return canonical

    def resolve(
        self,
        root: str | os.PathLike[str],
        requested: str | os.PathLike[str],
        *,
        must_exist: bool,
    ) -> ResolvedWorkspacePath:
        canonical_root = self.canonicalize_root(root)
        raw = os.fspath(requested)
        if not str(raw).strip():
            raise PathPolicyError("PATH_INVALID")
        candidate = Path(raw)
        combined = candidate if candidate.is_absolute() else canonical_root / candidate
        for reparse_component in self._reparse_components(combined):
            try:
                reparse_target = reparse_component.resolve(strict=True)
            except (OSError, RuntimeError, ValueError) as exc:
                raise PathPolicyError("PATH_INVALID") from exc
            if not self._contained(canonical_root, reparse_target):
                raise PathPolicyError()
        try:
            target = combined.resolve(strict=must_exist)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise PathPolicyError("PATH_INVALID") from exc
        if not self._contained(canonical_root, target):
            raise PathPolicyError()
        if must_exist and not target.exists():
            raise PathPolicyError("PATH_NOT_FOUND")
        if not must_exist:
            parent = target.parent
            if parent.exists():
                try:
                    canonical_parent = parent.resolve(strict=True)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise PathPolicyError("PATH_INVALID") from exc
                if not self._contained(canonical_root, canonical_parent):
                    raise PathPolicyError()
        relative = os.path.relpath(str(target), str(canonical_root))
        if relative == ".":
            relative = "."
        else:
            relative = relative.replace(os.sep, "/")
        return ResolvedWorkspacePath(
            root=canonical_root,
            target=target,
            relative_path=relative,
            exists=target.exists(),
        )

    @staticmethod
    def _contained(root: Path, target: Path) -> bool:
        """Use OS path semantics, including Windows case-insensitive paths."""
        try:
            normalized_root = CanonicalWorkspaceResolver._comparison_path(root)
            normalized_target = CanonicalWorkspaceResolver._comparison_path(target)
            return os.path.commonpath([normalized_root, normalized_target]) == normalized_root
        except (OSError, ValueError):
            return False

    @staticmethod
    def _comparison_path(value: Path) -> str:
        normalized = os.path.normcase(os.path.normpath(os.fspath(value)))
        if normalized.startswith("\\\\?\\UNC\\"):
            return "\\\\" + normalized[8:]
        if normalized.startswith("\\\\?\\"):
            return normalized[4:]
        return normalized

    @classmethod
    def _reparse_components(cls, path: Path) -> list[Path]:
        """Identify symlink/junction/reparse components before final containment."""
        current = Path(path.anchor) if path.anchor else Path()
        components: list[Path] = []
        for part in path.parts:
            if part == path.anchor:
                continue
            current = current / part
            if os.path.lexists(current) and cls._is_reparse_point(current):
                components.append(current)
        return components

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        try:
            attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        except OSError:
            return False
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
        return path.is_symlink() or bool(attributes & reparse_flag)


__all__ = ["CanonicalWorkspaceResolver", "ResolvedWorkspacePath"]
