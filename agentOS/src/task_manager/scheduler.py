"""任务管理部件内部的轻量排队规则。"""

from collections.abc import Iterable


def order_task_ids(task_ids: Iterable[str]) -> list[str]:
    """按稳定字典序输出待处理任务，保证测试和审计结果可重放。"""
    return sorted(set(task_ids))
