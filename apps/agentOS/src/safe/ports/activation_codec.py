"""有界张量编解码端口；格式与分配限额由实现核实。

TODO(P1)：为每个新codec提供合法/非法共享测试向量，禁止pickle或任意对象。
TODO(P3)：应用层另行验证manifest与会话的形状，不能仅凭codec接受而运行。
"""

from collections.abc import Iterable
from typing import Protocol

from safe.contracts.activation import ActivationEnvelope


class ActivationCodec(Protocol):
    def encode(self, values: Iterable[float], shape: tuple[int, int, int]) -> ActivationEnvelope:
        """先检查shape/限额，再读取有界数据；拒绝非有限或不可表示的FP32。"""
        ...

    def decode(self, envelope: ActivationEnvelope) -> tuple[float, ...]:
        """先校验长度/摘要，再返回有限浮点扁平值；不得构造框架对象。"""
        ...
