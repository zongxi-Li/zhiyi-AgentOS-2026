"""本地执行调用分发边界。"""

from collections.abc import Callable
from typing import Any


def dispatch(handler: Callable[..., Any], payload: dict[str, Any]) -> Any:
    """同步调用注入的处理器；远程调用必须经 adapters.remote_agent 提供。"""
    return handler(**payload)


# TODO: 接入远程 Agent HTTP/gRPC 适配器，并传播可审计的超时和取消信号。
