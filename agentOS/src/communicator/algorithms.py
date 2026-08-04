"""通信内容选择的纯函数。"""


def low_entropy_choice(candidates: list[str]) -> str | None:
    """选择字典序最小的候选作为稳定的低不确定性默认项。"""
    return min(candidates) if candidates else None
