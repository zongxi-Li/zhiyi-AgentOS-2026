"""远程或本地模型的适配器边界。"""

from typing import Protocol


class ModelProvider(Protocol):
    """定义应用层注入模型客户端的最小异步边界。

    实现负责供应商 SDK、认证、超时和重试；调用方只能依赖文本输入与
    文本输出，不得保留或解释供应商私有响应对象。
    """

    async def generate(self, prompt: str) -> str:
        """根据 ``prompt`` 生成一段文本结果。

        返回值必须是可消费的纯文本；网络、限流或供应商错误由具体实现以
        明确异常上抛，协议不承诺重试、流式传输或线程安全性。
        """
        ...


# TODO: 实现 OpenAI/本地模型客户端时，统一超时、重试、限流和结构化错误映射。

from .native import NativeGeneralAgent, register_native_runtime

__all__ = ["ModelProvider", "NativeGeneralAgent", "register_native_runtime"]
