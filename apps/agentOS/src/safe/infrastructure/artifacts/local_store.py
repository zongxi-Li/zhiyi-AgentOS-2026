"""只读独立角色制品验证；批准目录由配置注入，不能从请求取得。

TODO(P2)：目前信任安装目录不被并发写入；部署应使用只读权限/不可变快照防TOCTOU。
TODO(P6)：大模型另行实现分片和配额；当前单文件权重不超过4GiB。
"""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.manifest import SplitModelManifest
from safe.domain.compatibility import require_manifest_digest

TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "generation_config.json")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tokenizer_digest(directory: Path) -> str:
    files = {name: file_digest(directory / name) for name in TOKENIZER_FILES if (directory / name).is_file()}
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def template_digest(directory: Path) -> str:
    value = json.loads((directory / "tokenizer_config.json").read_text(encoding="utf-8"))
    template = value.get("chat_template")
    if not isinstance(template, str) or not template:
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


class LocalArtifactStore:
    def __init__(self, directory: Path):
        try:
            self.directory = Path(directory).resolve(strict=True)
            if not self.directory.is_dir():
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        except OSError:
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None

    def path(self, name: str, *, max_bytes: int = 16 * 1024 * 1024) -> Path:
        """内部固定名称读取，限制路径逃逸和文件大小；不作为任意路径API。"""
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        try:
            path = (self.directory / relative).resolve(strict=True)
            if not path.is_relative_to(self.directory) or not path.is_file() or path.stat().st_size > max_bytes:
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            return path
        except OSError:
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None

    @property
    def role(self) -> str:
        try:
            data = json.loads(self.path("role.json", max_bytes=1024).read_text(encoding="utf-8"))
            if data not in ({"role": "prefix"}, {"role": "suffix"}):
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            return data["role"]
        except (ValueError, TypeError):
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None

    def verified_manifest(self, manifest_digest: str) -> SplitModelManifest:
        try:
            value = SplitModelManifest.model_validate_json(self.path("manifest.json", max_bytes=16384).read_bytes())
            manifest = require_manifest_digest(value, manifest_digest)
            expected = manifest.prefix_digest if self.role == "prefix" else manifest.suffix_digest
            if (file_digest(self.path("model.safetensors", max_bytes=4 * 1024 ** 3)) != expected
                    or file_digest(self.path("config.json")) != manifest.config_digest):
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            self.path("LICENSE", max_bytes=1024 * 1024)
            if self.role == "prefix":
                for name in TOKENIZER_FILES:
                    if (self.directory / "tokenizer" / name).exists():
                        self.path("tokenizer/" + name)
                self.path("tokenizer/tokenizer.json")
                self.path("tokenizer/tokenizer_config.json")
                if (tokenizer_digest(self.directory / "tokenizer") != manifest.tokenizer_digest
                        or template_digest(self.directory / "tokenizer") != manifest.template_digest):
                    raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            return manifest
        except (ValidationError, ValueError, OSError, TypeError):
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None
