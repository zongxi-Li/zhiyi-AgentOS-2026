"""ACG 格式选择导出器。"""

from .graphviz import to_dot
from .mermaid import to_mermaid


def export_graph(graph: dict[str, object], format_name: str = "mermaid") -> str:
    """按显式格式导出图文本，未知格式立即报错避免误导消费者。"""
    if format_name == "mermaid":
        return to_mermaid(graph)
    if format_name == "dot":
        return to_dot(graph)
    raise ValueError(f"不支持的图导出格式：{format_name}")
