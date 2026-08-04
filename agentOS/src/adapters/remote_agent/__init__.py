"""远程 Agent 传输的适配器边界。"""

from typing import Any, Protocol


class RemoteAgentClient(Protocol):
    """定义向远程 Agent 提交可序列化工作负载的异步边界。

    调用者与实现之间只交换 Agent 标识、JSON 负载和 JSON 结果，不暴露
    HTTP/gRPC 对象；认证、幂等、超时与熔断由具体传输适配器负责。
    """

    async def invoke(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 ``agent_id`` 并返回其可序列化结果。

        ``payload`` 必须可被传输层编码；找不到 Agent、网络失败、远端拒绝或
        响应无法解析时由实现显式报告。协议不保证调用已执行一次且仅一次。
        """
        ...


# TODO: 接入 HTTP 或 gRPC 传输，实现身份认证、幂等键、超时和熔断。

__all__ = ["RemoteAgentClient"]
