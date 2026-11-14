"""前后段制品身份；制品许可与模型许可单独记录，不能用仓库许可代替。

TODO(P0)：冻结 canonical JSON/digest 规范；digest 字段不能参与自身散列。
TODO(P2)：加入 chat template、special token、RoPE/context、tied weights 的导出验证。
TODO(P2)：由签名的批准清单核实哈希；客户端自报相同字段不能建立信任。
"""

from typing import Literal

from pydantic import Field, model_validator

from safe.contracts.base import Digest, SafeContract


class SplitModelManifest(SafeContract):
    schema_version: Literal["manifest-v1"] = "manifest-v1"
    model_id: str = Field(min_length=1, max_length=256)
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    config_digest: Digest
    tokenizer_digest: Digest
    template_digest: Digest
    prefix_digest: Digest
    suffix_digest: Digest
    total_layers: int = Field(ge=2)
    cut_layer: int = Field(ge=1, description="本机执行 [0,K)，云端执行 [K,N)")
    hidden_size: int = Field(ge=1)
    dtype: Literal["float32"] = "float32"
    max_context: int = Field(default=160, ge=160)
    license_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def check_partition(self) -> "SplitModelManifest":
        if self.cut_layer >= self.total_layers:
            raise ValueError("切口必须位于模型内部")
        return self
