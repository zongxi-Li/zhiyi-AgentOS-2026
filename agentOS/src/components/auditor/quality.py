"""质量阈值计算。"""


def quality_passed(score: float, threshold: float = 0.8) -> bool:
    """判断经 [0, 1] 截断的质量分是否达到 ``threshold``。

    ``score`` 超出范围时先被限制，阈值本身保持调用者语义、不作隐式校正；返回
    布尔结果且不记录评估历史。计算只含常数次比较，时间与空间复杂度均为 O(1)。
    """
    return max(0.0, min(1.0, score)) >= threshold
