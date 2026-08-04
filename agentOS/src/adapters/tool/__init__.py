"""外部工具调用的适配器边界。"""

from typing import Any, Protocol


class ToolProvider(Protocol):
    """具名工具协议，调用方只传递 JSON 兼容参数和结果。"""

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行工具并返回可序列化结果。"""
        ...


# TODO: 接入 HTTP/MCP 工具客户端，补充鉴权、取消传播和调用审计。

__all__ = ["ToolProvider"]
