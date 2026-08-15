"""Mermaid 文本导出器。"""

from .labels import node_label


def to_mermaid(graph: dict[str, object]) -> str:
    """把简化 nodes/edges 图投影为 Mermaid flowchart 文本。"""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    lines = ["flowchart TD"]
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict):
            identifier = str(node.get("id", "node"))
            lines.append(f'    {identifier}["{node_label(node)}"]')
    for edge in edges if isinstance(edges, list) else []:
        if isinstance(edge, dict) and edge.get("source") and edge.get("target"):
            lines.append(f"    {edge['source']} --> {edge['target']}")
    return "\n".join(lines)
