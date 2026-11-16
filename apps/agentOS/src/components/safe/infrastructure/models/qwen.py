"""Qwen2 CPU/FP32/eager runner，支持无KV参考和进程内逐token缓存。

参考Transformers v4.46.3的decoder/RoPE/norm调用语义，直接复用Apache-2.0库API，
未复制网络服务代码；来源见docs/superpowers/reports/safe/references。
KV 使用 Transformers DynamicCache，prefix/suffix 各自持有独立角色缓存；激活边界不传KV。
TODO(P3)：接入取消/deadline和执行中隔离；当前角色runner不应直接暴露公网。
"""

import json
import math
from pathlib import Path
import secrets
import threading
from dataclasses import dataclass, field
from contextlib import contextmanager, nullcontext
from typing import Iterator

from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.domain.activation_policy import checked_raw_bytes
from components.safe.infrastructure.artifacts.local_store import LocalArtifactStore
from components.safe.infrastructure.artifacts.safetensors import check_header, validate_qwen_state
from components.safe.ports.model_runner import KVHandle


def _load_role(directory: Path, approved_digest: str, role: str):
    """只构造本角色，不创建完整模型后再删层。meta构造避免随机权重峰值。"""
    import torch
    from safetensors.torch import load_file
    from transformers import Qwen2Config
    from transformers.models.qwen2.modeling_qwen2 import Qwen2DecoderLayer, Qwen2RMSNorm, Qwen2RotaryEmbedding

    store = LocalArtifactStore(directory)
    manifest = store.verified_manifest(approved_digest)
    if store.role != role:
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
    config = Qwen2Config.from_dict(json.loads(store.path("config.json").read_text(encoding="utf-8")))
    if (config.model_type != "qwen2" or config.use_sliding_window
            or config.hidden_size != manifest.hidden_size or config.num_hidden_layers != manifest.total_layers):
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
    config._attn_implementation = "eager"
    config.use_cache = False
    with torch.device("meta"):
        module = torch.nn.Module()
        indices = range(manifest.cut_layer) if role == "prefix" else range(manifest.cut_layer, manifest.total_layers)
        module.layers = torch.nn.ModuleDict({str(i): Qwen2DecoderLayer(config, i) for i in indices})
        if role == "prefix":
            module.embed_tokens = torch.nn.Embedding(config.vocab_size, config.hidden_size, config.pad_token_id)
        else:
            module.norm = Qwen2RMSNorm(config.hidden_size, eps=config.rms_norm_eps)
            module.lm_head = torch.nn.Linear(config.hidden_size, config.vocab_size, bias=False)
    weight_path = store.path("model.safetensors", max_bytes=4 * 1024 ** 3)
    check_header(weight_path)
    state = load_file(str(weight_path), device="cpu")
    validate_qwen_state(config.to_dict(), manifest.cut_layer, role, state)
    try:
        module.load_state_dict(state, strict=True, assign=True)
    except RuntimeError:
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None
    module.eval().requires_grad_(False)
    rope = Qwen2RotaryEmbedding(config=config, device="cpu")
    return module, rope, config, manifest


def _layers(module, rope, hidden, *, cache=None, position_offset: int = 0):
    """运行一段连续位置；可把当前角色的KV追加到本地DynamicCache。"""
    import torch

    length = hidden.shape[1]
    positions = torch.arange(position_offset, position_offset + length, dtype=torch.long)
    position_ids = positions.unsqueeze(0)
    key_positions = torch.arange(position_offset + length, dtype=torch.long)
    blocked = key_positions.unsqueeze(0) > positions.unsqueeze(1)
    mask = torch.zeros((length, position_offset + length), dtype=torch.float32)
    mask.masked_fill_(blocked, torch.finfo(torch.float32).min)
    mask = mask[None, None, :, :]
    embeddings = rope(hidden, position_ids)
    for layer in module.layers.values():
        hidden = layer(hidden, attention_mask=mask, position_ids=position_ids, past_key_value=cache,
                       use_cache=cache is not None, cache_position=positions, position_embeddings=embeddings)[0]
    return hidden


@dataclass
class _CacheEntry:
    session_id: str
    cache: object
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class _CacheRegistry:
    """按随机句柄隔离缓存；释放与正在执行的单会话前向互斥。"""

    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()
        self._closed = False

    def create(self, session_id: str) -> KVHandle:
        from transformers.cache_utils import DynamicCache

        if not isinstance(session_id, str) or not session_id:
            raise SafeError(ErrorCode.SESSION_INVALID)
        handle = KVHandle(secrets.token_urlsafe(32))
        entry = _CacheEntry(session_id=session_id, cache=DynamicCache())
        with self._lock:
            if self._closed:
                raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
            self._entries[str(handle)] = entry
        return handle

    @contextmanager
    def access(self, handle: KVHandle, session_id: str) -> Iterator[_CacheEntry]:
        key = str(handle)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or entry.session_id != session_id:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        with entry.lock:
            with self._lock:
                if self._entries.get(key) is not entry:
                    raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
            try:
                yield entry
            except BaseException:
                # 层前向、有限值检查或结果转换失败时，KV可能已被部分更新。
                # 不尝试回滚缓存长度：整个句柄失效，其他会话不受影响。
                self.release(handle)
                raise

    def release(self, handle: KVHandle) -> None:
        key = str(handle)
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            return
        with entry.lock:
            entry.cache.key_cache.clear()
            entry.cache.value_cache.clear()

    def clear(self) -> None:
        with self._lock:
            self._closed = True
            handles = tuple(KVHandle(handle) for handle in self._entries)
        for handle in handles:
            self.release(handle)


class QwenPrefixRunner:
    def __init__(self, directory: Path, *, approved_digest: str):
        self._module, self._rope, self._config, self.manifest = _load_role(directory, approved_digest, "prefix")
        self._caches = _CacheRegistry()

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._module.named_parameters()) if self._module is not None else ()

    def prefill(self, token_ids: tuple[int, ...], *, kv_handle: KVHandle | None = None,
                session_id: str | None = None) -> tuple[tuple[float, ...], tuple[int, int, int]]:
        """原始token只在本机角色使用；返回扁平激活，不返回内部tensor。"""
        import torch

        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        if not 1 <= len(token_ids) <= 128 or any(type(t) is not int or not 0 <= t < self._config.vocab_size for t in token_ids):
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        if (kv_handle is None) != (session_id is None):
            raise SafeError(ErrorCode.SESSION_INVALID)
        if len(token_ids) > self.manifest.max_context:
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        cache_scope = nullcontext(None) if kv_handle is None else self._caches.access(kv_handle, session_id)
        with torch.inference_mode(), cache_scope as entry:
            if entry is not None and entry.cache.get_seq_length(0) != 0:
                raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
            embedded = self._module.embed_tokens(torch.tensor([token_ids], dtype=torch.long))
            hidden = _layers(self._module, self._rope, embedded,
                             cache=None if entry is None else entry.cache)
            if not torch.isfinite(hidden).all():
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            return tuple(hidden.reshape(-1).tolist()), (1, len(token_ids), self.manifest.hidden_size)

    def create_kv(self, session_id: str) -> KVHandle:
        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        return self._caches.create(session_id)

    def decode(self, kv_handle: KVHandle, session_id: str, token_id: int) -> tuple[tuple[float, ...], tuple[int, int, int]]:
        import torch

        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        if type(token_id) is not int or not 0 <= token_id < self._config.vocab_size:
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        with self._caches.access(kv_handle, session_id) as entry:
            position = entry.cache.get_seq_length(0)
            if position <= 0 or position >= self.manifest.max_context:
                raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
            with torch.inference_mode():
                embedded = self._module.embed_tokens(torch.tensor([[token_id]], dtype=torch.long))
                hidden = _layers(self._module, self._rope, embedded, cache=entry.cache, position_offset=position)
                if not torch.isfinite(hidden).all():
                    raise SafeError(ErrorCode.ACTIVATION_INVALID)
                return tuple(hidden.reshape(-1).tolist()), (1, 1, self.manifest.hidden_size)

    def release_kv(self, handle: KVHandle) -> None:
        self._caches.release(handle)

    def close(self) -> None:
        self._caches.clear()
        self._module = None
        self._rope = None


class QwenSuffixRunner:
    def __init__(self, directory: Path, *, approved_digest: str):
        self._module, self._rope, self._config, self.manifest = _load_role(directory, approved_digest, "suffix")
        self._caches = _CacheRegistry()

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._module.named_parameters()) if self._module is not None else ()

    def prefill(self, activation: tuple[float, ...], shape: tuple[int, int, int], *,
                kv_handle: KVHandle | None = None, session_id: str | None = None) -> tuple[float, ...]:
        """接收已通过身份边界的激活，输出最后位置logits供本机对照/云端采样。"""
        import torch

        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        expected = checked_raw_bytes(shape) // 4
        if shape[2] != self.manifest.hidden_size or len(activation) != expected or not all(math.isfinite(v) for v in activation):
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        if (kv_handle is None) != (session_id is None):
            raise SafeError(ErrorCode.SESSION_INVALID)
        if shape[1] > self.manifest.max_context:
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        cache_scope = nullcontext(None) if kv_handle is None else self._caches.access(kv_handle, session_id)
        with torch.inference_mode(), cache_scope as entry:
            if entry is not None and entry.cache.get_seq_length(self.manifest.cut_layer) != 0:
                raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
            hidden = torch.tensor(activation, dtype=torch.float32).reshape(shape)
            if not torch.isfinite(hidden).all():
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            hidden = _layers(self._module, self._rope, hidden,
                             cache=None if entry is None else entry.cache)
            logits = self._module.lm_head(self._module.norm(hidden[:, -1:, :]))[0, -1]
            if not torch.isfinite(logits).all():
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            return tuple(logits.tolist())

    def create_kv(self, session_id: str) -> KVHandle:
        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        return self._caches.create(session_id)

    def decode(self, kv_handle: KVHandle, session_id: str,
               activation: tuple[float, ...], shape: tuple[int, int, int]) -> tuple[float, ...]:
        import torch

        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        if shape != (1, 1, self.manifest.hidden_size) or len(activation) != self.manifest.hidden_size:
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        if not all(math.isfinite(value) for value in activation):
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        with self._caches.access(kv_handle, session_id) as entry:
            position = entry.cache.get_seq_length(self.manifest.cut_layer)
            if position <= 0 or position >= self.manifest.max_context:
                raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
            with torch.inference_mode():
                hidden = torch.tensor(activation, dtype=torch.float32).reshape(1, 1, -1)
                hidden = _layers(self._module, self._rope, hidden, cache=entry.cache, position_offset=position)
                logits = self._module.lm_head(self._module.norm(hidden[:, -1:, :]))[0, -1]
                if not torch.isfinite(logits).all():
                    raise SafeError(ErrorCode.ACTIVATION_INVALID)
                return tuple(logits.tolist())

    def release_kv(self, handle: KVHandle) -> None:
        self._caches.release(handle)

    def close(self) -> None:
        self._caches.clear()
        self._module = None
        self._rope = None
