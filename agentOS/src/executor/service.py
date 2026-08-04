"""执行部件的公共 Facade。"""

from collections.abc import Callable, Mapping
from typing import Any

from .dispatcher import dispatch
from .graph import ready_set


class ExecutorService:
    """仅运行当前就绪节点，调用方负责提供具体执行器。"""

    def execute_ready(self, dependencies: Mapping[str, set[str]], completed: set[str], handlers: Mapping[str, Callable[[], Any]]) -> dict[str, Any]:
        """对每个就绪节点调用对应处理器并返回结果，不写入外部状态。"""
        return {node: dispatch(handlers[node], {}) for node in ready_set(dependencies, completed) if node in handlers}
