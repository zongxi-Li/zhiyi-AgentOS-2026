"""校准机制端口；参数必须源自批准profile，不能从原始数据自适应推导。

TODO(P4)：冻结vector邻接和机制版本后，增加带校准证据的参数合同。
TODO(P4)：Accountant单独声明组合与保守舍入；不得直接套用DP-SGD会计假设。
实现必须用安全随机源并在缺依赖/溢出时拒绝，无普通噪声fallback。
"""

from typing import Protocol


class PrivacyMechanism(Protocol):
    def perturb(self, clipped: tuple[float, ...], *, sensitivity: float, epsilon: float,
                delta: float) -> tuple[float, ...]:
        """仅在已预扣预算的用例内执行；结果不能直接作为已批准发布回执。"""
        ...
