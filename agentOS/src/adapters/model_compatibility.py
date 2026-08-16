"""多模型提供商统一接入的协议与注册边界。"""

from __future__ import annotations

import asyncio
import inspect
import re
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
    """定义所有模型提供商适配器必须实现的无 SDK 调用接口。

    适配器还可选实现 ``check_health() -> bool | Awaitable[bool]``，由应用层定时调用
    ``ModelCompatibilityRegistry.refresh_health``。该可选方法不属于调用必要条件，
    因而不会破坏仅提供同步 ``is_available`` 的既有适配器。
    """

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
        # 异步健康探测只保留能力 ID 到布尔状态的投影，不保存错误、响应正文或时间。
        # 缓存未命中时仍使用既有同步 ``is_available`` 语义，保证旧适配器兼容。
        self._health: dict[str, bool] = {}
        self._adapters: dict[str, ModelProviderAdapter] = {}
        self._manifests: dict[str, CapabilityManifest] = {}
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
        self._version_tuple(manifest.version)

        with self._lock:
            entry = self._capabilities.register(adapter)
            self._adapters.setdefault(entry.manifest.capability_id, entry.adapter)
            self._manifests.setdefault(entry.manifest.capability_id, entry.manifest)
            self._health.pop(entry.manifest.capability_id, None)
            for route in routes:
                candidates = self._routes.setdefault(route, [])
                candidate = (-priority, entry.manifest.capability_id)
                if candidate not in candidates:
                    candidates.append(candidate)
                    candidates.sort()

    def resolve(
        self,
        provider: str,
        model: str,
        *,
        version: str | None = None,
    ) -> ModelProviderAdapter:
        """按提供商和模型名解析健康适配器，不进行隐式模型或端点回退。"""
        return self.resolve_candidates(provider, model, version=version)[0]

    def resolve_candidates(
        self,
        provider: str,
        model: str,
        *,
        version: str | None = None,
    ) -> tuple[ModelProviderAdapter, ...]:
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
        constraint = self._version_constraint(version)
        compatible = []
        for priority, capability_id in candidates:
            manifest = self._manifests.get(capability_id)
            if manifest is None:
                continue
            parsed_version = self._version_tuple(manifest.version)
            if self._matches_version(parsed_version, constraint):
                compatible.append((parsed_version, priority, capability_id))
        compatible.sort(
            key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[1], item[2])
        )
        if not compatible:
            requested = version or "latest"
            raise LookupError(
                f"MODEL_VERSION_UNAVAILABLE: {route[0]}/{route[1]} does not satisfy {requested}"
            )
        resolved: list[ModelProviderAdapter] = []
        for _, _, capability_id in compatible:
            with self._lock:
                cached_health = self._health.get(capability_id)
            if cached_health is False:
                continue
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

    async def refresh_health(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, bool]:
        """异步刷新指定模型或全部模型的健康缓存，不把网络 I/O 放进路由路径。

        适配器可选实现 ``check_health()``，返回布尔值或布尔协程。没有该方法的旧
        实现会退回同步 ``is_available()``；探测异常、超时和非布尔结果一律标记为
        不健康。返回值只含能力 ID 与布尔状态，适合应用层监控且不泄露供应商正文。
        """
        if timeout_seconds <= 0:
            raise ValueError("MODEL_HEALTH_TIMEOUT_INVALID: timeout_seconds must be greater than zero")
        if model is not None and provider is None:
            raise ValueError("MODEL_HEALTH_FILTER_INVALID: model requires provider")
        provider_filter = self._provider_key(provider) if provider is not None else None
        model_filter = self._model_key(model) if model is not None else None
        with self._lock:
            routes = tuple(
                (route, tuple(candidates))
                for route, candidates in self._routes.items()
                if (provider_filter is None or route[0] == provider_filter)
                and (model_filter is None or route[1] == model_filter)
            )
            candidate_ids = tuple(
                capability_id
                for _, candidates in routes
                for _, capability_id in candidates
            )
            adapters = {
                capability_id: self._adapters[capability_id]
                for capability_id in candidate_ids
                if capability_id in self._adapters
            }
        refreshed: dict[str, bool] = {}
        for capability_id in candidate_ids:
            adapter = adapters.get(capability_id)
            if adapter is None or capability_id in refreshed:
                continue
            healthy = await self._probe_health(adapter, timeout_seconds=timeout_seconds)
            with self._lock:
                self._health[capability_id] = healthy
            refreshed[capability_id] = healthy
        return refreshed

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

    _VERSION_PATTERN = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")

    @classmethod
    def _version_tuple(cls, value: str) -> tuple[int, int, int]:
        """解析受限语义版本；拒绝预发布和任意文本以保持协商结果可预测。"""
        matched = cls._VERSION_PATTERN.fullmatch(value.strip())
        if matched is None:
            raise CapabilityRegistrationError(
                "MODEL_VERSION_INVALID: version must use numeric semantic form such as 2.1.0"
            )
        return tuple(int(part or 0) for part in matched.groups())

    @classmethod
    def _version_constraint(cls, value: str | None) -> tuple[str, tuple[int, int, int]] | None:
        """解析精确、主版本兼容和次版本兼容约束。"""
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        operator = "="
        if normalized[0] in {"^", "~"}:
            operator, normalized = normalized[0], normalized[1:]
        try:
            return operator, cls._version_tuple(normalized)
        except CapabilityRegistrationError as exc:
            raise ValueError("MODEL_VERSION_CONSTRAINT_INVALID: invalid model version constraint") from exc

    @staticmethod
    def _matches_version(
        candidate: tuple[int, int, int],
        constraint: tuple[str, tuple[int, int, int]] | None,
    ) -> bool:
        """按约束判断候选版本是否兼容；未指定时由最高可用版本胜出。"""
        if constraint is None:
            return True
        operator, requested = constraint
        if operator == "=":
            return candidate == requested
        if operator == "^":
            return candidate[0] == requested[0] and candidate >= requested
        return candidate[:2] == requested[:2] and candidate >= requested

    @staticmethod
    async def _probe_health(adapter: ModelProviderAdapter, *, timeout_seconds: float) -> bool:
        """执行可选健康探测并把任意失败收敛为 ``False``，不暴露异常文字。"""
        checker = getattr(adapter, "check_health", None)
        if checker is None:
            checker = getattr(adapter, "is_available", None)
        if not callable(checker):
            return True
        try:
            value = checker()
            if inspect.isawaitable(value):
                value = await asyncio.wait_for(value, timeout=timeout_seconds)
        except Exception:
            return False
        return value is True


__all__ = ["ModelCompatibilityRegistry", "ModelProviderAdapter"]
