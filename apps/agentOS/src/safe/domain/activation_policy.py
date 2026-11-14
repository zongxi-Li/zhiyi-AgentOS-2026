"""纯张量边界规则，不分配张量、不读取网络。

TODO(P3)：将 hidden_size 与受信 manifest 比较；prefill≤128、decode=1 由会话核验。
TODO(P6)：覆盖最大合法张量、恶意超长维数与分配前拒绝的资源测量。
"""

from safe.contracts.activation import MAX_RAW_BYTES
from safe.contracts.errors import ErrorCode, SafeError


def checked_raw_bytes(shape: tuple[int, int, int]) -> int:
    """首期 batch=1、序列≤128、三维FP32；先检查再允许分配。"""
    if len(shape) != 3 or any(type(n) is not int or n < 1 for n in shape):
        raise SafeError(ErrorCode.ACTIVATION_INVALID)
    if shape[0] != 1 or shape[1] > 128:
        raise SafeError(ErrorCode.ACTIVATION_INVALID)
    size = 4
    for dimension in shape:
        if dimension > MAX_RAW_BYTES // size:
            raise SafeError(ErrorCode.ACTIVATION_INVALID)
        size *= dimension
    return size
