"""风险等级归一化。"""


def classify_risk(score: float) -> str:
    """将量化分数映射到合同允许的风险等级。"""
    if score >= 15:
        return "critical"
    if score >= 7:
        return "high"
    if score >= 3:
        return "medium"
    return "low" if score > 0 else "info"
