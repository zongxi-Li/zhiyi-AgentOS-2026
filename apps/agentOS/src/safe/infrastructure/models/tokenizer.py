"""批准prefix制品中的离线分词器；固定模板、完整EOS集合与本机整段解码。

generation_config只读取EOS，不启用其中的随机采样、重复惩罚或温度。
TODO(P3)：流式解码须另行处理多字节片段；当前只解码完整已确认输出。
TODO(P5)：安装目录须为不可变快照，沿用LocalArtifactStore的TOCTOU边界。
"""

import json
from pathlib import Path

from safe.contracts.errors import ErrorCode, SafeError
from safe.infrastructure.artifacts.local_store import LocalArtifactStore


class HuggingFaceTokenizer:
    def __init__(self, directory: Path, *, approved_digest: str):
        from transformers import AutoTokenizer

        store = LocalArtifactStore(directory)
        self.manifest = store.verified_manifest(approved_digest)
        if store.role != "prefix":
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        try:
            config = json.loads(store.path("config.json").read_text(encoding="utf-8"))
            self.vocab_size = config["vocab_size"]
            if type(self.vocab_size) is not int or self.vocab_size <= 0:
                raise ValueError()
            self._tokenizer = AutoTokenizer.from_pretrained(str(store.directory / "tokenizer"),
                local_files_only=True, trust_remote_code=False)
            if len(self._tokenizer) > self.vocab_size:
                raise ValueError()
            self._template = json.loads(store.path("tokenizer/tokenizer_config.json").read_text(
                encoding="utf-8"))["chat_template"]
            generation = {}
            if (store.directory / "tokenizer/generation_config.json").is_file():
                generation = json.loads(store.path("tokenizer/generation_config.json").read_text(encoding="utf-8"))
            eos = generation.get("eos_token_id", config.get("eos_token_id", self._tokenizer.eos_token_id))
            if eos is None:
                eos = []
            elif type(eos) is int:
                eos = [eos]
            if type(eos) is not list or any(type(t) is not int or not 0 <= t < self.vocab_size for t in eos):
                raise ValueError()
            self.eos_token_ids = frozenset(eos)
        except (ValueError, KeyError, TypeError, OSError):
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None

    def encode_prompt(self, prompt: str) -> tuple[int, ...]:
        if type(prompt) is not str or not 1 <= len(prompt) <= 16384:
            raise SafeError(ErrorCode.INFERENCE_INVALID)
        ids = tuple(self._tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
            chat_template=self._template, tokenize=True, add_generation_prompt=True))
        if not 1 <= len(ids) <= 128 or any(type(t) is not int or not 0 <= t < self.vocab_size for t in ids):
            raise SafeError(ErrorCode.INFERENCE_INVALID)
        return ids

    def decode(self, token_ids: tuple[int, ...]) -> str:
        if (not isinstance(token_ids, tuple) or len(token_ids) > 32
                or any(type(t) is not int or not 0 <= t < self.vocab_size for t in token_ids)):
            raise SafeError(ErrorCode.MODEL_OUTPUT_INVALID)
        return self._tokenizer.decode(token_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)


__all__ = ["HuggingFaceTokenizer"]
