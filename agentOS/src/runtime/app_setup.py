"""应用进程的 OpenAI 兼容模型配置与生命周期装配。"""

from __future__ import annotations

import asyncio
import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from adapters.http_transport import HttpJsonTransport, RotatingKeyProvider
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.openai_runtime import OpenAICompatibleRuntime
from contracts.capability import CapabilityKind, CapabilityManifest
from runtime.bootstrap import bootstrap
from runtime.dependencies import DependencyRegistry


class ApplicationSetupError(ValueError):
    """表示模型应用配置无效；错误文本不包含端点密钥或配置正文。"""


@dataclass(frozen=True)
class ModelSetup:
    """单个 OpenAI 兼容实现的已校验应用配置。"""

    capability_id: str
    provider: str
    models: tuple[str, ...]
    base_url: str
    key_env: str | None
    version: str
    priority: int
    request_timeout: float
    allow_insecure: bool


class ApplicationSetup:
    """持有进程级模型适配器生命周期，不创建 Workflow Runtime。

    生产装配必须注入现有 ``WorkflowRuntime.model_registry``。保留依赖容器入口是为了
    独立适配器测试，但同一实例内只允许一个 registry，避免模型路由出现双事实源。
    """

    def __init__(
        self,
        *,
        setups: tuple[ModelSetup, ...],
        model_registry: ModelCompatibilityRegistry | None = None,
        dependencies: DependencyRegistry | None = None,
        health_interval_seconds: float = 30.0,
    ) -> None:
        if not math.isfinite(health_interval_seconds) or health_interval_seconds <= 0:
            raise ApplicationSetupError(
                "APP_HEALTH_INTERVAL_INVALID: health interval must be greater than zero"
            )
        if dependencies is None:
            overrides = (
                {"model_compatibility_registry": model_registry}
                if model_registry is not None
                else None
            )
            dependencies = bootstrap(overrides)
        registry = dependencies.require("model_compatibility_registry")
        if not isinstance(registry, ModelCompatibilityRegistry):
            raise ApplicationSetupError(
                "APP_MODEL_REGISTRY_INVALID: model compatibility registry has an invalid type"
            )
        if model_registry is not None and registry is not model_registry:
            raise ApplicationSetupError(
                "APP_MODEL_REGISTRY_CONFLICT: setup must use one model compatibility registry"
            )
        self._setups = setups
        self.dependencies = dependencies
        self._registry = registry
        self._health_interval_seconds = health_interval_seconds
        self._key_providers: dict[str, RotatingKeyProvider] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._started = False
        self._registered = False
        self._environment: Mapping[str, str] = os.environ

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        model_registry: ModelCompatibilityRegistry | None = None,
        dependencies: DependencyRegistry | None = None,
    ) -> "ApplicationSetup":
        """从显式环境视图读取配置；空配置不会创建后台健康任务。"""
        values: Mapping[str, str] = os.environ if environment is None else environment
        app = cls(
            setups=cls._read_setups(values),
            model_registry=model_registry,
            dependencies=dependencies,
            health_interval_seconds=cls._positive_float(
                values.get("AGENTOS_MODEL_HEALTH_INTERVAL_SECONDS", "30"),
                code="APP_HEALTH_INTERVAL_INVALID",
            ),
        )
        app._environment = values
        return app

    @property
    def started(self) -> bool:
        return self._started

    @property
    def model_registry(self) -> ModelCompatibilityRegistry:
        """暴露只读身份，供 composition root 断言与 Runtime 共用同一实例。"""
        return self._registry

    async def start(self) -> None:
        """登记模型并启动健康刷新；重复启动不会更换已注册适配器。"""
        if self._started:
            return
        if not self._registered:
            adapters: list[tuple[OpenAICompatibleRuntime, RotatingKeyProvider]] = []
            for setup in self._setups:
                key = self._environment.get(setup.key_env, "") if setup.key_env else None
                provider = RotatingKeyProvider(key)
                adapter = OpenAICompatibleRuntime(
                    manifest=CapabilityManifest(
                        capabilityId=setup.capability_id,
                        kind=CapabilityKind.MODEL,
                        displayName=setup.capability_id,
                        provider=setup.provider,
                        capabilities=list(setup.models),
                        version=setup.version,
                        metadata={"priority": setup.priority},
                    ),
                    transport=HttpJsonTransport(
                        base_url=setup.base_url,
                        key_provider=provider,
                        request_timeout=setup.request_timeout,
                        allow_insecure=setup.allow_insecure,
                    ),
                )
                adapters.append((adapter, provider))
            for adapter, provider in adapters:
                self._registry.register(adapter)
                self._key_providers[adapter.manifest.capability_id] = provider
            self._registered = True
        if not self._setups:
            self._started = True
            return
        await self._registry.refresh_health()
        self._health_task = asyncio.create_task(self._refresh_loop())
        self._started = True

    async def close(self) -> None:
        """停止健康刷新；注册对象保留，允许同一应用实例安全重启生命周期。"""
        task = self._health_task
        self._health_task = None
        self._started = False
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def rotate_key(self, capability_id: str, key: str | None) -> int:
        """原子轮换指定实现的密钥，返回不含敏感信息的修订号。"""
        provider = self._key_providers.get(capability_id.strip())
        if provider is None:
            raise ApplicationSetupError(
                "APP_MODEL_NOT_REGISTERED: model capability is not registered"
            )
        return provider.rotate(key)

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._health_interval_seconds)
            try:
                await self._registry.refresh_health()
            except Exception:
                continue

    @classmethod
    def _read_setups(cls, values: Mapping[str, str]) -> tuple[ModelSetup, ...]:
        raw = values.get("AGENTOS_MODELS", "").strip()
        if not raw:
            return ()
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApplicationSetupError(
                "APP_MODEL_CONFIG_INVALID: AGENTOS_MODELS must be a JSON array"
            ) from exc
        if not isinstance(items, list):
            raise ApplicationSetupError(
                "APP_MODEL_CONFIG_INVALID: AGENTOS_MODELS must be a JSON array"
            )
        setups: list[ModelSetup] = []
        identifiers: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise ApplicationSetupError(
                    "APP_MODEL_CONFIG_INVALID: each model entry must be an object"
                )
            capability_id = cls._required_text(item, "capabilityId")
            if capability_id in identifiers:
                raise ApplicationSetupError(
                    "APP_MODEL_CONFIG_INVALID: capabilityId must be unique"
                )
            identifiers.add(capability_id)
            models = item.get("models")
            if not isinstance(models, list) or not models or any(
                not isinstance(model, str) or not model.strip() for model in models
            ):
                raise ApplicationSetupError(
                    "APP_MODEL_CONFIG_INVALID: models must be a non-empty string array"
                )
            key_env = item.get("apiKeyEnv")
            if key_env is not None and (
                not isinstance(key_env, str) or not key_env.strip()
            ):
                raise ApplicationSetupError(
                    "APP_MODEL_CONFIG_INVALID: apiKeyEnv must be a non-empty string"
                )
            priority = item.get("priority", 0)
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise ApplicationSetupError(
                    "APP_MODEL_CONFIG_INVALID: priority must be an integer"
                )
            allow_insecure = item.get("allowInsecure", False)
            if not isinstance(allow_insecure, bool):
                raise ApplicationSetupError(
                    "APP_MODEL_CONFIG_INVALID: allowInsecure must be boolean"
                )
            version = item.get("version", "v1")
            if not isinstance(version, str) or not version.strip():
                raise ApplicationSetupError(
                    "APP_MODEL_CONFIG_INVALID: version must be a non-empty string"
                )
            setups.append(
                ModelSetup(
                    capability_id=capability_id,
                    provider=cls._required_text(item, "provider"),
                    models=tuple(model.strip() for model in models),
                    base_url=cls._required_text(item, "baseUrl"),
                    key_env=key_env.strip() if isinstance(key_env, str) else None,
                    version=version.strip(),
                    priority=priority,
                    request_timeout=cls._positive_float(
                        item.get("requestTimeoutSeconds", 120),
                        code="APP_MODEL_CONFIG_INVALID",
                    ),
                    allow_insecure=allow_insecure,
                )
            )
        return tuple(setups)

    @staticmethod
    def _required_text(item: dict[str, Any], name: str) -> str:
        value = item.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ApplicationSetupError(
                f"APP_MODEL_CONFIG_INVALID: {name} must be a non-empty string"
            )
        return value.strip()

    @staticmethod
    def _positive_float(value: object, *, code: str) -> float:
        if isinstance(value, bool):
            raise ApplicationSetupError(f"{code}: value must be greater than zero")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ApplicationSetupError(
                f"{code}: value must be greater than zero"
            ) from exc
        if not math.isfinite(result) or result <= 0:
            raise ApplicationSetupError(f"{code}: value must be greater than zero")
        return result


__all__ = ["ApplicationSetup", "ApplicationSetupError", "ModelSetup"]
