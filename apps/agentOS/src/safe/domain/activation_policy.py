"""纯张量边界规则，不分配张量、不读取网络。

TODO(P3)：将 hidden_size 与受信 manifest 比较；prefill≤128、decode=1 由会话核验。
TODO(P6)：覆盖最大合法张量、恶意超长维数与分配前拒绝的资源测量。
"""

from safe.contracts.activation import MAX_RAW_BYTES
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.session import ActivationContext


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


def require_activation_boundary(shape: tuple[int, int, int], manifest: SplitModelManifest,
                                context: ActivationContext) -> None:
    """校验受信上下文的阶段、位置、长度和hidden size；不读取张量。"""
    checked_raw_bytes(shape)
    if shape[2] != manifest.hidden_size:
        raise SafeError(ErrorCode.ACTIVATION_INVALID)
    if context.phase == "prefill":
        if context.next_step != 0 or context.position_offset != 0:
            raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
    elif context.phase == "decode":
        if (not 1 <= context.next_step <= 31 or shape[1] != 1
                or context.position_offset < context.next_step):
            raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
    else:
        raise SafeError(ErrorCode.ACTIVATION_INVALID)
    # 首期固定总context≤160，即使模型配置允许更长也不动态放宽。
    if context.position_offset + shape[1] > min(160, manifest.max_context):
        raise SafeError(ErrorCode.ACTIVATION_INVALID)
