"""Graphviz DOT 文本导出器。"""

from .labels import node_label


def to_dot(graph: dict[str, object]) -> str:
    """生成纯文本 DOT，不要求本机安装 graphviz 二进制程序。"""
    lines = ["digraph ACG {"]
    for node in graph.get("nodes", []) if isinstance(graph.get("nodes", []), list) else []:
        if isinstance(node, dict):
            identifier = str(node.get("id", "node"))
            lines.append(f'  "{identifier}" [label="{node_label(node)}"];')
    for edge in graph.get("edges", []) if isinstance(graph.get("edges", []), list) else []:
        if isinstance(edge, dict) and edge.get("source") and edge.get("target"):
            lines.append(f'  "{edge["source"]}" -> "{edge["target"]}";')
    return "\n".join(lines + ["}"])


# TODO: 若需要 PNG/SVG 渲染，注入 graphviz 可执行程序或远程渲染适配器。
