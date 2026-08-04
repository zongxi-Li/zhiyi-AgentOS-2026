"""ACG 的稳定 JSON 序列化。"""

from typing import Any

from contracts import stable_json_dumps


def serialize_graph(graph: Any) -> str:
    """优先使用 Pydantic 的合同别名导出，再生成稳定 JSON。"""
    payload = graph.model_dump(by_alias=True) if hasattr(graph, "model_dump") else graph
    return stable_json_dumps(payload)
