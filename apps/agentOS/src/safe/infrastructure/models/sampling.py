"""无随机状态的greedy采样：并列最大值取最小token索引。

词表大小和EOS集合由可信模型配置注入，不能从请求体覆盖。
TODO(P3)：批准generation配置的加载由装配层实现；本组件不读取文件或下载模型。
TODO(P6)：随机采样须另行冻结RNG/temperature/top-k/top-p规则，不改变当前greedy语义。
"""

import math

from safe.contracts.errors import ErrorCode, SafeError


class GreedySampler:
    def __init__(self, *, vocab_size: int, eos_token_ids: frozenset[int] = frozenset()):
        if type(vocab_size) is not int or vocab_size <= 0:
            raise ValueError("词表大小必须是正整数")
        if not isinstance(eos_token_ids, frozenset) or any(
            type(token) is not int or not 0 <= token < vocab_size for token in eos_token_ids
        ):
            raise ValueError("EOS必须是词表内整数的不可变集合")
        self._vocab_size = vocab_size
        self._eos_token_ids = eos_token_ids

    def sample(self, logits: tuple[float, ...]) -> tuple[int, bool]:
        if not isinstance(logits, tuple) or len(logits) != self._vocab_size or any(
            type(value) is not float or not math.isfinite(value) for value in logits
        ):
            raise SafeError(ErrorCode.MODEL_OUTPUT_INVALID)
        token = max(range(self._vocab_size), key=logits.__getitem__)
        return token, token in self._eos_token_ids


__all__ = ["GreedySampler"]
