"""质量阈值计算。"""


def quality_passed(score: float, threshold: float = 0.8) -> bool:
    """限定到 [0, 1] 的质量分达到阈值时通过。"""
    return max(0.0, min(1.0, score)) >= threshold
