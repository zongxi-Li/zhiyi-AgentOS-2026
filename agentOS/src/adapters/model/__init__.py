"""远程或本地模型的适配器边界。"""

from typing import Protocol


class ModelProvider(Protocol):
    """模型提供方最小协议，应用层负责注入具体 SDK 客户端。"""

    async def generate(self, prompt: str) -> str:
        """生成文本结果，不暴露供应商私有响应对象。"""
        ...


# TODO: 实现 OpenAI/本地模型客户端时，统一超时、重试、限流和结构化错误映射。

from .native import NativeGeneralAgent, register_native_runtime

__all__ = ["ModelProvider", "NativeGeneralAgent", "register_native_runtime"]
