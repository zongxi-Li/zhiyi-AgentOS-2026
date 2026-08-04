"""审计结果的纯评分函数。"""


def audit_score(severity_counts: dict[str, int]) -> float:
    """用固定权重聚合风险级别，数值越高表示越需要关注。"""
    weights = {"info": 0, "low": 1, "medium": 3, "high": 7, "critical": 15}
    return sum(weights.get(level, 0) * max(0, count) for level, count in severity_counts.items())
