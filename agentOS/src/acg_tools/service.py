"""ACG 工具部件的公共 Facade。"""

from typing import Any

from .exporter import export_graph
from .serializer import serialize_graph


class ACGToolsService:
    """提供图的稳定序列化和文本可视化导出。"""

    def serialize(self, graph: Any) -> str:
        """序列化 Pydantic 图模型或已准备的 JSON 值。"""
        return serialize_graph(graph)

    def export(self, graph: dict[str, object], format_name: str = "mermaid") -> str:
        """导出 Mermaid 或 DOT 文本。"""
        return export_graph(graph, format_name)
