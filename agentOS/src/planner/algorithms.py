"""规划候选比较的纯函数。"""


def planning_score(coverage: float, confidence: float, cost: float = 0.0) -> float:
    """用覆盖率和置信度奖励候选，并对代价作温和惩罚。"""
    return max(0.0, coverage) * 0.6 + max(0.0, confidence) * 0.4 - max(0.0, cost) * 0.1
