"""标准Qwen2角色参数白名单与受限safetensors头检查，不反序列化可执行对象。

参数形状依据Transformers v4.46.3 Qwen2的q/k/v bias、MLP和RMSNorm定义。
TODO(P2)：新增架构/分片须独立适配；不能以strict=False忽略结构差异。
"""

from pathlib import Path
import struct

from safe.contracts.errors import ErrorCode, SafeError


def check_header(path: Path) -> None:
    """解析器读取header前先限制其大小；实际格式/offset再由审核库校验。"""
    with path.open("rb") as stream:
        prefix = stream.read(8)
    if len(prefix) != 8:
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
    size = struct.unpack("<Q", prefix)[0]
    if not 1 <= size <= min(8 * 1024 * 1024, path.stat().st_size - 8):
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)


def validate_qwen_state(config: dict, cut_layer: int, role: str, state: dict) -> None:
    """导出时核实每个键/shape/dtype/有限值，阻止发布只能在加载时才发现损坏的制品。"""
    import torch

    try:
        hidden, heads = config["hidden_size"], config["num_attention_heads"]
        kv_heads = config.get("num_key_value_heads", heads)
        intermediate, vocab, layers = config["intermediate_size"], config["vocab_size"], config["num_hidden_layers"]
        if (role not in {"prefix", "suffix"} or any(type(n) is not int or n < 1
                for n in (hidden, heads, kv_heads, intermediate, vocab, layers))
                or hidden % heads or heads % kv_heads):
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        dimension = hidden // heads
        expected = {"embed_tokens.weight": (vocab, hidden)} if role == "prefix" else {
            "norm.weight": (hidden,), "lm_head.weight": (vocab, hidden)}
        indices = range(cut_layer) if role == "prefix" else range(cut_layer, layers)
        for index in indices:
            prefix = f"layers.{index}."
            expected[prefix + "input_layernorm.weight"] = (hidden,)
            expected[prefix + "post_attention_layernorm.weight"] = (hidden,)
            for projection, width in (("q", hidden), ("k", kv_heads * dimension), ("v", kv_heads * dimension)):
                expected[prefix + f"self_attn.{projection}_proj.weight"] = (width, hidden)
                expected[prefix + f"self_attn.{projection}_proj.bias"] = (width,)
            expected[prefix + "self_attn.o_proj.weight"] = (hidden, hidden)
            for name in ("gate_proj", "up_proj"):
                expected[prefix + f"mlp.{name}.weight"] = (intermediate, hidden)
            expected[prefix + "mlp.down_proj.weight"] = (hidden, intermediate)
        if set(state) != set(expected):
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        for key, value in state.items():
            if tuple(value.shape) != expected[key] or value.dtype != torch.float32 or not torch.isfinite(value).all():
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None
