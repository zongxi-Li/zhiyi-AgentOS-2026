"""远程 Agent 传输的适配器边界。"""

from typing import Any, Protocol


class RemoteAgentClient(Protocol):
    """提交可序列化工作负载并取得结果的协议。"""

    async def invoke(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用远程 Agent，不泄漏 HTTP/gRPC 客户端类型。"""
        ...


# TODO: 接入 HTTP 或 gRPC 传输，实现身份认证、幂等键、超时和熔断。

__all__ = ["RemoteAgentClient"]
