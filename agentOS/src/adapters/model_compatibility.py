"""多模型提供商统一接入的协议与注册边界。"""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from adapters.registry import (
    CapabilityRegistrationError,
    CapabilityRegistry,
    CapabilityResolutionError,
)
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
        # 一个逻辑模型可有多个实现。元组内容为 ``(-priority, capability_id)``，
        # 使优先级高的实现先被尝试；相同优先级按能力 ID 排序，避免注册顺序影响。
        self._routes: dict[tuple[str, str], list[tuple[int, str]]] = {}
        self._lock = RLock()

    def register(self, adapter: ModelProviderAdapter) -> None:
        """登记模型适配器，并为其声明的每个模型建立精确路由。

        ``manifest.provider`` 不能为空，``manifest.capabilities`` 在模型注册表中
        专用于模型标识列表。一个提供商/模型组合可以登记多个实现，按
        ``metadata.priority`` 从高到低选择；同优先级时按能力 ID 稳定排序。相同
        声明的重复登记保持幂等，不允许启动顺序覆盖已有能力声明。
        """
        manifest = adapter.manifest
        if manifest.kind is not CapabilityKind.MODEL:
            raise CapabilityRegistrationError(
                f"CAPABILITY_KIND_INVALID: expected model, got {manifest.kind.value}"
            )
        provider = self._provider_key(manifest.provider)
        models = self._model_keys(manifest)
        routes = tuple((provider, model) for model in models)
        priority = self._priority(manifest)

        with self._lock:
            entry = self._capabilities.register(adapter)
            for route in routes:
                candidates = self._routes.setdefault(route, [])
                candidate = (-priority, entry.manifest.capability_id)
                if candidate not in candidates:
                    candidates.append(candidate)
                    candidates.sort()

    def resolve(self, provider: str, model: str) -> ModelProviderAdapter:
        """按提供商和模型名解析健康适配器，不进行隐式模型或端点回退。"""
        return self.resolve_candidates(provider, model)[0]

    def resolve_candidates(self, provider: str, model: str) -> tuple[ModelProviderAdapter, ...]:
        """按优先级返回全部健康实现，供调用层在临时故障时受控切换。

        返回值是调用时的元组快照，后续注册不会改变本次调用的候选顺序。该方法不
        执行网络探测；适配器的同步 ``is_available`` 只决定是否纳入本次候选集。
        """
        route = (self._provider_key(provider), self._model_key(model))
        with self._lock:
            candidates = tuple(self._routes.get(route, ()))
        if not candidates:
            raise LookupError(
                f"MODEL_NOT_FOUND: {route[0]}/{route[1]} is not registered"
            )
        resolved: list[ModelProviderAdapter] = []
        for _, capability_id in candidates:
            try:
                resolved.append(self._capabilities.resolve(capability_id))
            except CapabilityResolutionError:
                # 单个实现的健康检查失败不应阻断同模型备实现。候选列表已稳定排序，
                # 因而每次解析的切换路径可预测且不依赖适配器注册先后。
                continue
        if resolved:
            return tuple(resolved)
        raise LookupError(
            f"MODEL_UNAVAILABLE: {route[0]}/{route[1]} has no healthy adapter"
        )

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

    @staticmethod
    def _priority(manifest: CapabilityManifest) -> int:
        """读取可选优先级；仅接受整数，避免字符串比较造成不稳定路由。"""
        priority = manifest.metadata.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise CapabilityRegistrationError(
                "MODEL_PRIORITY_INVALID: metadata.priority must be an integer"
            )
        return priority


__all__ = ["ModelCompatibilityRegistry", "ModelProviderAdapter"]
