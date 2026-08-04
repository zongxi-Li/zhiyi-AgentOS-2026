"""并发阶段完成屏障。"""


def barrier_satisfied(expected: set[str], completed: set[str]) -> bool:
    """所有预期节点完成时才允许下一个执行阶段开始。"""
    return expected <= completed
