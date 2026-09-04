"""恢复任务排序的纯函数。"""


def recovery_priority(retryable: bool, attempts: int, impact: float = 0.0) -> float:
    """可重试、高影响、低尝试次数的恢复请求优先。"""
    return (10.0 if retryable else 0.0) + max(0.0, impact) - max(0, attempts) * 2.0
