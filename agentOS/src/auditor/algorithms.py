"""审计结果的纯评分函数。"""


def audit_score(severity_counts: dict[str, int]) -> float:
    """用固定权重把各风险级别的数量聚合为审计分数。

    ``severity_counts`` 的未知级别按零权重处理，负数数量按零截断；返回值越高
    表示需要越优先处理。算法单次遍历输入，时间复杂度 O(n)、额外空间 O(1)。
    """
    weights = {"info": 0, "low": 1, "medium": 3, "high": 7, "critical": 15}
    return sum(weights.get(level, 0) * max(0, count) for level, count in severity_counts.items())
