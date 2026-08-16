"""多模型提供商统一接入的协议与注册边界。"""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from adapters.registry import CapabilityRegistrationError, CapabilityRegistry
from contracts.capability import (
    CapabilityKind,
    CapabilityManifest,
    ModelInvocationRequest,
    ModelInvocationResponse,
)


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
    """维护提供商与模型名到模型适配器的确定性、无网络映射。"""

    def __init__(self) -> None:
        self._capabilities: CapabilityRegistry[ModelProviderAdapter] = CapabilityRegistry(
            allowed_kinds=(CapabilityKind.MODEL,)
        )
        self._routes: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def register(self, adapter: ModelProviderAdapter) -> None:
        """登记模型适配器，并为其声明的每个模型建立精确路由。

        ``manifest.provider`` 不能为空，``manifest.capabilities`` 在模型注册表中
        专用于模型标识列表。一个提供商/模型组合只能由一个能力 ID 占用；相同
        声明的重复登记保持幂等，不允许启动顺序覆盖已有路由。
        """
        manifest = adapter.manifest
        if manifest.kind is not CapabilityKind.MODEL:
            raise CapabilityRegistrationError(
                f"CAPABILITY_KIND_INVALID: expected model, got {manifest.kind.value}"
            )
        provider = self._provider_key(manifest.provider)
        models = self._model_keys(manifest)
        routes = tuple((provider, model) for model in models)

        with self._lock:
            for route in routes:
                current_id = self._routes.get(route)
                if current_id is not None and current_id != manifest.capability_id:
                    raise CapabilityRegistrationError(
                        "MODEL_ROUTE_CONFLICT: "
                        f"{route[0]}/{route[1]} is already owned by {current_id}"
                    )
            entry = self._capabilities.register(adapter)
            for route in routes:
                self._routes[route] = entry.manifest.capability_id

    def resolve(self, provider: str, model: str) -> ModelProviderAdapter:
        """按提供商和模型名解析健康适配器，不进行隐式模型或端点回退。"""
        route = (self._provider_key(provider), self._model_key(model))
        with self._lock:
            capability_id = self._routes.get(route)
        if capability_id is None:
            raise LookupError(
                f"MODEL_NOT_FOUND: {route[0]}/{route[1]} is not registered"
            )
        return self._capabilities.resolve(capability_id)

    @staticmethod
    def _provider_key(provider: str) -> str:
        """标准化提供商名，避免大小写和首尾空白产生重复路由。"""
        normalized = provider.strip().lower()
        if not normalized:
            raise CapabilityRegistrationError("MODEL_PROVIDER_INVALID: provider is required")
        return normalized

    @staticmethod
    def _model_keys(manifest: CapabilityManifest) -> tuple[str, ...]:
        """读取声明的模型标识，拒绝空列表与空别名。"""
        if not manifest.capabilities:
            raise CapabilityRegistrationError(
                "MODEL_CAPABILITIES_INVALID: manifest.capabilities must declare at least one model"
            )
        return tuple(dict.fromkeys(ModelCompatibilityRegistry._model_key(item) for item in manifest.capabilities))

    @staticmethod
    def _model_key(model: str) -> str:
        """标准化模型键；模型名保留大小写，只去除无意义的首尾空白。"""
        normalized = model.strip()
        if not normalized:
            raise CapabilityRegistrationError("MODEL_NAME_INVALID: model is required")
        return normalized


__all__ = ["ModelCompatibilityRegistry", "ModelProviderAdapter"]
