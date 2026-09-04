"""资源候选排序的纯函数。"""


def lease_score(available_slots: int, utilization: float, priority: int = 0) -> float:
    """可用槽位和请求优先级越高越优，利用率越高越受惩罚。"""
    return max(0, available_slots) * 10 + max(0, priority) - min(1.0, max(0.0, utilization)) * 10
