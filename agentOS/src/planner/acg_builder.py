"""ACG 构建边界的最小、可序列化表示。"""


def build_acg(tasks: list[dict[str, object]]) -> dict[str, object]:
    """以任务标识创建无边的初始图；具体图模型由 contracts 逐步接管。"""
    return {"nodes": [{"id": task["taskId"]} for task in tasks], "edges": []}
