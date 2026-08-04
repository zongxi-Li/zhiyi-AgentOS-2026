"""执行器的纯算法出口与可审计摘要工具。"""

import json
from time import perf_counter
from typing import Any

from .graph import RuntimeGraph, RuntimeNode, ready_set


def select_maximum_batch(graph: RuntimeGraph, ready: list[RuntimeNode], max_parallelism: int) -> list[RuntimeNode]:
    """按优先级和 node id 在独立资源键上贪心选择最大确定性批次。"""
    del graph
    selected: list[RuntimeNode] = []
    occupied: set[str] = set()
    for node in sorted(ready, key=lambda item: (-int(item.spec.get("priority", 0)), item.node_id)):
        resource = str((node.current_binding or {}).get("resourceId") or (node.current_binding or {}).get("assignedAgentId") or node.node_id)
        if len(selected) >= max(1, max_parallelism) or resource in occupied:
            continue
        selected.append(node); occupied.add(resource)
    return selected


def summarize(data: Any, *, max_chars: int = 280) -> str:
    """为审计事件生成稳定、有界的输入输出摘要。"""
    try: text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError): text = str(data)
    text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[:max_chars] + f"…(+{len(text) - max_chars} chars)"


class StepExecutionTimer:
    """轻量、无外部依赖的节点耗时计时器。"""
    def __init__(self) -> None: self._started = perf_counter()
    def elapsed_ms(self) -> int: return int((perf_counter() - self._started) * 1000)

__all__ = ["StepExecutionTimer", "ready_set", "select_maximum_batch", "summarize"]
