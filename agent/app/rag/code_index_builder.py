"""Bounded local code index used by the read-only AgentOS tool runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


class CodeIndexBuilder:
    """Build a deterministic keyword index without executing workspace code."""

    SOURCE_EXTENSIONS = {
        ".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".java", ".js",
        ".jsx", ".kt", ".py", ".rs", ".swift", ".ts", ".tsx", ".vue",
    }
    SKIP_DIRECTORIES = {
        ".git", ".idea", ".mypy_cache", ".pytest_cache", ".venv",
        ".vscode", "__pycache__", "build", "dist", "node_modules", "target", "venv",
    }
    MAX_FILE_BYTES = 2 * 1024 * 1024
    CHUNK_LINES = 80

    def __init__(self, *, project_root: Path | None = None, cache_dir: Path | None = None) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parents[3]).resolve()
        data_root = Path(os.getenv("AGENTOS_DATA_DIR", "")).resolve() if os.getenv("AGENTOS_DATA_DIR") else self.project_root / ".agentos-data"
        self.cache_dir = (cache_dir or data_root / "code_index").resolve()
        self.manifest_path = self.cache_dir / "code_index_manifest.json"
        self.cache_path = self.cache_dir / "code_index_cache.json"

    def _normalize_path(self, root_path: str | None) -> Path:
        configured = str(root_path or os.getenv("TOOL_CODEBASE_ROOT") or "").strip()
        root = Path(configured) if configured else self.project_root
        if not root.is_absolute():
            root = self.project_root / root
        return root.resolve()

    @staticmethod
    def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return dict(default)
        return value if isinstance(value, dict) else dict(default)

    @staticmethod
    def _save_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _language(path: Path) -> str:
        return {
            ".py": "python", ".java": "java", ".js": "javascript",
            ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
            ".vue": "vue",
        }.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "text")

    def _source_files(self, root: Path) -> list[Path]:
        if not root.is_dir():
            return []
        result: list[Path] = []
        for current, directories, filenames in os.walk(root, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in self.SKIP_DIRECTORIES)
            base = Path(current)
            for name in sorted(filenames):
                path = base / name
                try:
                    resolved = path.resolve()
                    size = path.stat().st_size
                except OSError:
                    continue
                if (
                    path.suffix.lower() in self.SOURCE_EXTENSIONS
                    and resolved.is_relative_to(root)
                    and size <= self.MAX_FILE_BYTES
                ):
                    result.append(resolved)
        return result

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _documents(self, root: Path, path: Path) -> list[dict[str, Any]]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        relative = path.relative_to(root).as_posix()
        documents: list[dict[str, Any]] = []
        for offset in range(0, max(1, len(lines)), self.CHUNK_LINES):
            content = "\n".join(lines[offset: offset + self.CHUNK_LINES]).strip()
            if not content:
                continue
            line = offset + 1
            documents.append({
                "id": f"{relative}:{line}",
                "content": content[:12000],
                "metadata": {
                    "file_path": relative,
                    "line": line,
                    "language": self._language(path),
                },
            })
        return documents

    def build_code_index(self, root_path: str | None = None, *, enable_vectors: bool = False) -> dict[str, Any]:
        del enable_vectors
        root = self._normalize_path(root_path)
        if not root.is_dir():
            return {"success": False, "root_path": str(root), "files": {}, "indexed_docs": 0}
        files: dict[str, Any] = {}
        documents: dict[str, Any] = {}
        for path in self._source_files(root):
            relative = path.relative_to(root).as_posix()
            docs = self._documents(root, path)
            files[relative] = {"hash": self._digest(path), "ids": [item["id"] for item in docs]}
            documents.update({item["id"]: {"content": item["content"], "metadata": item["metadata"]} for item in docs})
        self._save_json(self.manifest_path, {"root_path": str(root), "files": files})
        self._save_json(self.cache_path, {"docs": documents})
        return {
            "success": True,
            "root_path": str(root),
            "indexed_files": len(files),
            "indexed_docs": len(documents),
            "vector_enabled": False,
        }

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return re.findall(r"[a-z0-9_./-]+|[\u4e00-\u9fff]+", value.lower())

    def search_code(self, query: str, top_k: int = 5, *, prefer_vectors: bool = False) -> list[dict[str, Any]]:
        del prefer_vectors
        tokens = self._tokens(query)
        docs = self._load_json(self.cache_path, {"docs": {}}).get("docs") or {}
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for document_id, payload in docs.items():
            if not isinstance(payload, dict):
                continue
            content = str(payload.get("content") or "")
            searchable = f"{document_id}\n{content}".lower()
            score = sum(3.0 if token in document_id.lower() else 1.0 for token in tokens if token in searchable)
            if score:
                scored.append((score, str(document_id), payload))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            {
                "id": document_id,
                "content": payload.get("content", ""),
                "metadata": payload.get("metadata", {}),
                "score": score,
            }
            for score, document_id, payload in scored[: max(1, min(int(top_k), 20))]
        ]


code_index_builder = CodeIndexBuilder()


__all__ = ["CodeIndexBuilder", "code_index_builder"]
