"""工作流运行时 Facade。"""

from collections.abc import Callable
from typing import Any


class WorkflowRuntime:
    """运行由调用方注入的工作流函数，不固化具体编排引擎。"""

    def run(self, workflow: Callable[..., Any], **inputs: Any) -> Any:
        """执行同步工作流入口；异步编排由上层事件循环负责。"""
        return workflow(**inputs)
