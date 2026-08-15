"""多模型提供商统一接入的协议与注册边界。"""

from __future__ import annotations

from typing import Protocol

from contracts.capability import CapabilityManifest, ModelInvocationRequest, ModelInvocationResponse


class ModelProviderAdapter(Protocol):
    """定义所有模型提供商适配器必须实现的无 SDK 调用接口。"""

    @property
    def manifest(self) -> CapabilityManifest:
        """返回模型提供商、能力和协议的只读声明。"""
        ...

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResponse:
        """将规范请求转换为供应商调用并返回规范响应。"""
        ...


class ModelCompatibilityRegistry:
    """为应用装配层预留多模型适配器注册与解析门面。"""

    def register(self, adapter: ModelProviderAdapter) -> None:
        """登记一个模型提供商适配器。

        TODO: 按 manifest 的 provider、版本和模型能力实现冲突检测与线程安全注册。
        """
        del adapter
        raise NotImplementedError("TODO: 实现模型适配器注册表")

    def resolve(self, provider: str, model: str) -> ModelProviderAdapter:
        """按提供商和模型名解析已登记适配器。

        TODO: 实现模型别名、版本协商、健康过滤和 OpenAI 兼容端点回退。
        """
        del provider, model
        raise NotImplementedError("TODO: 实现模型适配器解析")


__all__ = ["ModelCompatibilityRegistry", "ModelProviderAdapter"]
