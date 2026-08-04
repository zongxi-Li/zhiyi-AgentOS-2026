"""任务管理中的确定性、无副作用算法。"""


def task_complexity(constraint_count: int, dependency_count: int = 0) -> float:
    """以约束和依赖数估计任务复杂度，供排序而非业务决策使用。"""
    return max(0, constraint_count) + max(0, dependency_count) * 1.5
