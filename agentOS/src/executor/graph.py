"""执行图的就绪节点计算。"""

from collections.abc import Mapping


def ready_set(dependencies: Mapping[str, set[str]], completed: set[str]) -> list[str]:
    """返回依赖均已完成的节点，按名称排序以保证调度可复放。"""
    return sorted(node for node, required in dependencies.items() if node not in completed and required <= completed)
