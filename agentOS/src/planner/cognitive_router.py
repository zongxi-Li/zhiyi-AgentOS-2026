"""认知路径选择的确定性兼容实现。"""


def route_cognition(intent: dict[str, object]) -> str:
    """疑问句进入研究路径，其他输入进入直接执行规划路径。"""
    return "research" if intent.get("has_question") else "direct"
