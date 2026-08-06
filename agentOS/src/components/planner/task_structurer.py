"""将意图事实整理为最小任务骨架。"""


def structure_tasks(intent: dict[str, object]) -> list[dict[str, object]]:
    """在没有领域模板时创建单任务计划，避免凭空展开执行步骤。"""
    return [{"taskId": "task-1", "intent": dict(intent), "dependsOn": []}]
