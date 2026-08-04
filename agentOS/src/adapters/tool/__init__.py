"""外部工具调用的适配器边界。"""

from typing import Any, Protocol


class ToolProvider(Protocol):
    """定义具名外部工具的异步调用协议。

    调用方只提交 JSON 兼容的参数并取得可序列化结果；实现负责传输、鉴权和
    工具生命周期，协议本身不承诺幂等、重试或跨请求并发安全。
    """

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """以 ``arguments`` 调用名为 ``name`` 的工具并返回 JSON 结果。

        未知工具、无效参数、超时和远端失败应由具体实现以可辨识异常或约定
        错误载荷报告；本协议不暴露底层客户端或自动修复参数。
        """
        ...


# TODO: 接入 HTTP/MCP 工具客户端，补充鉴权、取消传播和调用审计。

__all__ = ["ToolProvider"]
