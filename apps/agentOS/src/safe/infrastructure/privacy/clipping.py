"""整份激活向量的全局 L2 裁剪，采用缩放避免平方求和溢出。

固定阈值 C 时，replacement 邻接的输出距离≤2C；这只是敏感度边界，尚无 DP 保证。
TODO(P4)：冻结完整张量的邻接、定长 padding 及裁剪顺序；禁止逐 token 自选 C。
TODO(P4)：结合经校准机制、持久账本与 transcript 组合测试后才允许对外发布。
来源：Dwork/Roth 的有界敏感度思想；本函数独立实现，未复制上游代码。
"""

import math

from safe.contracts.errors import ErrorCode, SafeError


def clip_global_l2(values: tuple[float, ...], bound: float) -> tuple[float, ...]:
    if not math.isfinite(bound) or bound <= 0 or not values or not all(math.isfinite(v) for v in values):
        raise SafeError(ErrorCode.ACTIVATION_INVALID)
    peak = max(abs(value) for value in values)
    if peak == 0:
        return values
    scaled_norm = math.sqrt(math.fsum((value / peak) ** 2 for value in values))
    if peak <= bound / scaled_norm:
        return values
    # 先归一化再乘 bound，避免 peak * scaled_norm 溢出。
    return tuple((value / peak) * (bound / scaled_norm) for value in values)
