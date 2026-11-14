"""激活信封；不包含原文、token IDs、身份自报字段或任意 metadata。

TODO(P1)：冻结规范 JSON 与字节序测试向量；HTTP 层在解析 JSON 前限制 body。
TODO(P3)：step 的阶段形状还需与受信 manifest、已存会话共同核验。
完整性哈希不能替代认证；同一信封重试必须保持原字节与 release_id。
"""

from typing import Annotated, Literal

from pydantic import Field

from safe.contracts.base import Digest, SafeContract

Dimension = Annotated[int, Field(ge=1)]
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_BASE64_CHARS = ((MAX_RAW_BYTES + 2) // 3) * 4


class ActivationEnvelope(SafeContract):
    protocol_version: Literal["safe-v1"] = "safe-v1"
    encoding: Literal["fp32-le-base64"] = "fp32-le-base64"
    dtype: Literal["float32"] = "float32"
    shape: tuple[Dimension, Dimension, Dimension]
    raw_bytes: int = Field(ge=4, le=MAX_RAW_BYTES)
    sha256: Digest
    data: str = Field(min_length=8, max_length=MAX_BASE64_CHARS, repr=False)
