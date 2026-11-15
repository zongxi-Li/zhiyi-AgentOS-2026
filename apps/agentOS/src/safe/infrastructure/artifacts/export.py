"""显式离线导出Qwen2角色，原子发布，保留模型许可，tied lm_head显式复制。

输入源目录/revision须由操作者核验；不自动下载，也不运行任意远程模型代码。
TODO(P2)：大模型分片及隔离子进程导出；目前只支持单文件标准Qwen2白名单。
"""

import json
import os
from pathlib import Path
import shutil
import tempfile

from pydantic import ValidationError

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.manifest import SplitModelManifest
from safe.domain.compatibility import manifest_digest
from safe.infrastructure.artifacts.local_store import LocalArtifactStore, TOKENIZER_FILES, file_digest, template_digest, tokenizer_digest
from safe.infrastructure.artifacts.safetensors import check_header, validate_qwen_state


def export_qwen_artifacts(source: Path, destination: Path, *, model_id: str, revision: str,
                          cut_layer: int, license_id: str) -> str:
    """只读已准备好的源，返回待批准摘要；输出存在时拒绝覆盖，失败清理临时目录。"""
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    source_store = LocalArtifactStore(source)
    target = Path(destination).resolve()
    if target.exists() or type(cut_layer) is not int:
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
    try:
        config_path = source_store.path("config.json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        layers = config["num_hidden_layers"]
        if (config.get("model_type") != "qwen2" or config.get("use_sliding_window", False)
                or not 0 < cut_layer < layers):
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        SplitModelManifest(model_id=model_id, revision=revision, config_digest="0" * 64,
            tokenizer_digest="0" * 64, template_digest="0" * 64, prefix_digest="0" * 64,
            suffix_digest="0" * 64, total_layers=layers, cut_layer=cut_layer,
            hidden_size=config["hidden_size"], license_id=license_id)
        source_store.path("LICENSE", max_bytes=1024 * 1024)
        source_store.path("tokenizer.json")
        source_store.path("tokenizer_config.json")
        weights = source_store.path("model.safetensors", max_bytes=4 * 1024 ** 3)
        check_header(weights)
        for name in TOKENIZER_FILES:
            if (source_store.directory / name).exists():
                source_store.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".safe-export-", dir=target.parent))
        try:
            for role in ("prefix", "suffix"):
                directory = temporary / role
                directory.mkdir()
                shutil.copyfile(config_path, directory / "config.json")
                shutil.copyfile(source_store.path("LICENSE"), directory / "LICENSE")
                (directory / "role.json").write_text(json.dumps({"role": role}), encoding="utf-8")
                if role == "prefix":
                    (directory / "tokenizer").mkdir()
                    for name in TOKENIZER_FILES:
                        if (source_store.directory / name).is_file():
                            shutil.copyfile(source_store.path(name), directory / "tokenizer" / name)
                state = {}
                with safe_open(str(weights), framework="pt", device="cpu") as tensors:
                    for key in tensors.keys():
                        if key.startswith("model.layers."):
                            index = int(key.split(".")[2])
                            if not 0 <= index < layers:
                                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
                            if (index < cut_layer) == (role == "prefix"):
                                state[key.removeprefix("model.")] = tensors.get_tensor(key).to(torch.float32).contiguous()
                        elif key == "model.embed_tokens.weight" and role == "prefix":
                            state["embed_tokens.weight"] = tensors.get_tensor(key).to(torch.float32).contiguous()
                        elif key == "model.norm.weight" and role == "suffix":
                            state["norm.weight"] = tensors.get_tensor(key).to(torch.float32).contiguous()
                        elif key == "lm_head.weight" and role == "suffix":
                            state[key] = tensors.get_tensor(key).to(torch.float32).contiguous()
                        elif key not in {"model.embed_tokens.weight", "model.norm.weight", "lm_head.weight"}:
                            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
                    if role == "suffix":
                        if config.get("tie_word_embeddings", False):
                            embedding = tensors.get_tensor("model.embed_tokens.weight").to(torch.float32).contiguous()
                            if "lm_head.weight" in state and not torch.equal(state["lm_head.weight"], embedding):
                                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
                            state["lm_head.weight"] = embedding
                        elif "lm_head.weight" not in state:
                            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
                validate_qwen_state(config, cut_layer, role, state)
                save_file(state, str(directory / "model.safetensors"), metadata={"format": "pt"})
                del state
            manifest = SplitModelManifest(model_id=model_id, revision=revision,
                config_digest=file_digest(config_path), tokenizer_digest=tokenizer_digest(temporary / "prefix/tokenizer"),
                template_digest=template_digest(temporary / "prefix/tokenizer"),
                prefix_digest=file_digest(temporary / "prefix/model.safetensors"),
                suffix_digest=file_digest(temporary / "suffix/model.safetensors"), total_layers=layers,
                cut_layer=cut_layer, hidden_size=config["hidden_size"], license_id=license_id)
            digest = manifest_digest(manifest)
            for role in ("prefix", "suffix"):
                (temporary / role / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
                LocalArtifactStore(temporary / role).verified_manifest(digest)
            (temporary / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            if target.exists():
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            os.replace(temporary, target)
            return digest
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    except (OSError, ValueError, KeyError, ValidationError, TypeError):
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None
