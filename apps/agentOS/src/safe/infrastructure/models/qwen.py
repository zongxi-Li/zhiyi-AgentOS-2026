"""Qwen2 CPU/FP32/eager无KV参考runner，固定decoder切口续算。

参考Transformers v4.46.3的decoder/RoPE/norm调用语义，直接复用Apache-2.0库API，
未复制网络服务代码；来源见docs/superpowers/reports/safe/references。
仅prefill；重复全序列计算用于正确性对照，不代表逐token KV会话完成。
TODO(P3)：双端独立KV、取消、deadline；当前对象不能并发使用或直接发布公网。
"""

import json
import math
from pathlib import Path

from safe.contracts.errors import ErrorCode, SafeError
from safe.domain.activation_policy import checked_raw_bytes
from safe.infrastructure.artifacts.local_store import LocalArtifactStore
from safe.infrastructure.artifacts.safetensors import check_header, validate_qwen_state


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


def _layers(module, rope, hidden):
    """从位置0开始的完整prefill；两角色保留原始layer_idx及相同causal mask。"""
    import torch

    length = hidden.shape[1]
    positions = torch.arange(length, dtype=torch.long)
    position_ids = positions.unsqueeze(0)
    mask = torch.full((length, length), torch.finfo(torch.float32).min, dtype=torch.float32)
    mask = torch.triu(mask, diagonal=1)[None, None, :, :]
    embeddings = rope(hidden, position_ids)
    for layer in module.layers.values():
        hidden = layer(hidden, attention_mask=mask, position_ids=position_ids, past_key_value=None,
                       use_cache=False, cache_position=positions, position_embeddings=embeddings)[0]
    return hidden


class QwenPrefixRunner:
    def __init__(self, directory: Path, *, approved_digest: str):
        self._module, self._rope, self._config, self.manifest = _load_role(directory, approved_digest, "prefix")

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._module.named_parameters()) if self._module is not None else ()

    def prefill(self, token_ids: tuple[int, ...]) -> tuple[tuple[float, ...], tuple[int, int, int]]:
        """原始token只在本机角色使用；返回扁平激活，不返回内部tensor。"""
        import torch

        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        if not 1 <= len(token_ids) <= 128 or any(type(t) is not int or not 0 <= t < self._config.vocab_size for t in token_ids):
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        with torch.inference_mode():
            hidden = _layers(self._module, self._rope, self._module.embed_tokens(torch.tensor([token_ids], dtype=torch.long)))
            if not torch.isfinite(hidden).all():
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            return tuple(hidden.reshape(-1).tolist()), (1, len(token_ids), self.manifest.hidden_size)

    def close(self) -> None:
        self._module = None
        self._rope = None


class QwenSuffixRunner:
    def __init__(self, directory: Path, *, approved_digest: str):
        self._module, self._rope, self._config, self.manifest = _load_role(directory, approved_digest, "suffix")

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._module.named_parameters()) if self._module is not None else ()

    def prefill(self, activation: tuple[float, ...], shape: tuple[int, int, int]) -> tuple[float, ...]:
        """接收已通过身份边界的激活，输出最后位置logits供本机对照/云端采样。"""
        import torch

        if self._module is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        expected = checked_raw_bytes(shape) // 4
        if shape[2] != self.manifest.hidden_size or len(activation) != expected or not all(math.isfinite(v) for v in activation):
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        with torch.inference_mode():
            hidden = torch.tensor(activation, dtype=torch.float32).reshape(shape)
            if not torch.isfinite(hidden).all():
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            hidden = _layers(self._module, self._rope, hidden)
            logits = self._module.lm_head(self._module.norm(hidden[:, -1:, :]))[0, -1]
            if not torch.isfinite(logits).all():
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            return tuple(logits.tolist())

    def close(self) -> None:
        self._module = None
        self._rope = None
