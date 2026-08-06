"""图节点显示标签规则。"""


def node_label(node: dict[str, object]) -> str:
    """优先使用名称，其次标识，保证可视化输出始终具有文字。"""
    return str(node.get("name") or node.get("label") or node.get("id") or "unnamed-node")
