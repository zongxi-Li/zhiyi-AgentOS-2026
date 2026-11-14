"""有界 little-endian FP32/base64 编码；仅标准库，算法为本项目实现。

TODO(P1)：流式 HTTP 仍须先限制 body≤12MiB、元数据≤16KiB；本类不能代替入口限流。
TODO(P3)：调用方核实 manifest.hidden_size、phase、位置与会话后才交 runner。
TODO(P6)：测量最大合法张量的峰值内存；新格式必须另加 codec，不修改 v1 字节语义。
"""

import base64
import binascii
import hashlib
import itertools
import math
import struct
from collections.abc import Iterable

from pydantic import ValidationError

from safe.contracts.activation import ActivationEnvelope
from safe.contracts.errors import ErrorCode, SafeError
from safe.domain.activation_policy import checked_raw_bytes


class FP32Codec:
    """输入为扁平数值迭代器；输出解码值不持有 Torch/NumPy 对象。"""

    def encode(self, values: Iterable[float], shape: tuple[int, int, int]) -> ActivationEnvelope:
        size = checked_raw_bytes(shape)
        count = size // 4
        flat = tuple(itertools.islice(values, count + 1))
        if len(flat) != count:
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        try:
            if any(isinstance(value, bool) or not math.isfinite(value) for value in flat):
                raise SafeError(ErrorCode.ACTIVATION_INVALID)
            raw = struct.pack(f"<{count}f", *flat)
        except (OverflowError, TypeError, ValueError, struct.error):
            raise SafeError(ErrorCode.ACTIVATION_INVALID) from None
        return ActivationEnvelope(shape=shape, raw_bytes=size, sha256=hashlib.sha256(raw).hexdigest(),
                                  data=base64.b64encode(raw).decode("ascii"))

    def decode(self, envelope: ActivationEnvelope) -> tuple[float, ...]:
        # 再校验一次，防止调用方使用 model_construct/model_copy 绕开合同校验。
        try:
            envelope = ActivationEnvelope.model_validate(envelope.model_dump())
        except ValidationError:
            raise SafeError(ErrorCode.ACTIVATION_INVALID) from None
        size = checked_raw_bytes(envelope.shape)
        if size != envelope.raw_bytes or len(envelope.data) != ((size + 2) // 3) * 4:
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        try:
            raw = base64.b64decode(envelope.data, validate=True)
        except (ValueError, binascii.Error):
            raise SafeError(ErrorCode.ACTIVATION_INVALID) from None
        if (len(raw) != size or base64.b64encode(raw).decode("ascii") != envelope.data
                or hashlib.sha256(raw).hexdigest() != envelope.sha256):
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        values = struct.unpack(f"<{size // 4}f", raw)
        if not all(math.isfinite(value) for value in values):
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        return values
