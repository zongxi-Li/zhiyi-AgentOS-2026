"""本机推理合同；InferenceRequest 的 prompt 严禁用于云端接口。

TODO(P0)：本机身份必须由调用适配器注入，不能从请求 prompt 或 owner 字段推断。
TODO(P2)：字符上限只防入口滥用；套用固定 chat template 后仍需检查 ≤128 token。
TODO(P3)：首版仅 greedy、batch=1；随机采样通过版本化选项另行开放。
"""

from typing import Literal

from pydantic import Field

from safe.contracts.base import SafeContract


class GenerationOptions(SafeContract):
    max_new_tokens: int = Field(default=32, ge=1, le=32)
    sampling: Literal["greedy"] = "greedy"


class InferenceRequest(SafeContract):
    prompt: str = Field(min_length=1, max_length=16384, repr=False)
    generation: GenerationOptions = Field(default_factory=GenerationOptions)


class InferenceResult(SafeContract):
    text: str = Field(repr=False)
    generated_tokens: int = Field(ge=0, le=32)
    finish_reason: Literal["eos", "length", "cancelled"]


class Capabilities(SafeContract):
    protocol_version: Literal["safe-v1"] = "safe-v1"
    available: bool = False
    max_prompt_tokens: Literal[128] = 128
    max_new_tokens: Literal[32] = 32
    codecs: tuple[Literal["fp32-le-base64"], ...] = ("fp32-le-base64",)
