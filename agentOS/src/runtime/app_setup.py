"""应用进程的模型配置、注册与生命周期装配。"""

from __future__ import annotations

import asyncio
import json
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
    """表示应用层模型配置无效，错误文字不含端点密钥或配置正文。"""


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
    """持有进程级适配器生命周期，核心执行器不直接依赖此类。

    配置只描述端点、模型和密钥环境变量名。密钥值在构造传输时进入
    ``RotatingKeyProvider``，不会写进能力声明、依赖名称、运行状态或检查点。每个
    模型实现单独登记，因此同一逻辑模型可沿用兼容注册表的优先级与故障切换机制。
    """

    def __init__(
        self,
        *,
        setups: tuple[ModelSetup, ...],
        dependencies: DependencyRegistry | None = None,
        health_interval_seconds: float = 30.0,
    ) -> None:
        if health_interval_seconds <= 0:
            raise ApplicationSetupError(
                "APP_HEALTH_INTERVAL_INVALID: health interval must be greater than zero"
            )
        self._setups = setups
        self.dependencies = dependencies or bootstrap()
        registry = self.dependencies.require("model_compatibility_registry")
        if not isinstance(registry, ModelCompatibilityRegistry):
            raise ApplicationSetupError(
                "APP_MODEL_REGISTRY_INVALID: model compatibility registry has an invalid type"
            )
        self._registry = registry
        self._health_interval_seconds = health_interval_seconds
        self._key_providers: dict[str, RotatingKeyProvider] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._started = False

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "ApplicationSetup":
        """从显式环境视图读取配置；未配置模型时保留可启动的空注册表。"""
        values: Mapping[str, str] = os.environ if environment is None else environment
        setups = cls._read_setups(values)
        interval = cls._positive_float(
            values.get("AGENTOS_MODEL_HEALTH_INTERVAL_SECONDS", "30"),
            code="APP_HEALTH_INTERVAL_INVALID",
        )
        app = cls(setups=setups, health_interval_seconds=interval)
        app._environment = values
        return app

    @property
    def started(self) -> bool:
        """返回健康任务是否已经由当前应用实例启动。"""
        return self._started

    async def start(self) -> None:
        """创建传输、登记模型并启动后台健康刷新；重复调用不重复注册或建任务。"""
        if self._started:
            return
        environment = getattr(self, "_environment", os.environ)
        for setup in self._setups:
            key = environment.get(setup.key_env, "") if setup.key_env else None
            provider = RotatingKeyProvider(key)
            transport = HttpJsonTransport(
                base_url=setup.base_url,
                key_provider=provider,
                request_timeout=setup.request_timeout,
                allow_insecure=setup.allow_insecure,
            )
            runtime = OpenAICompatibleRuntime(
                manifest=CapabilityManifest(
                    capabilityId=setup.capability_id,
                    kind=CapabilityKind.MODEL,
                    displayName=setup.capability_id,
                    provider=setup.provider,
                    capabilities=list(setup.models),
                    version=setup.version,
                    metadata={"priority": setup.priority},
                ),
                transport=transport,
            )
            self._registry.register(runtime)
            self._key_providers[setup.capability_id] = provider
        self._started = True
        # 初始刷新建立确定的健康投影；随后才启动定时循环，避免启动第一刻路由状态不明。
        await self._registry.refresh_health()
        self._health_task = asyncio.create_task(self._refresh_loop())

    async def close(self) -> None:
        """停止健康刷新任务；HTTP 请求由各请求的生成器或调用协程自行释放。"""
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
        """原子轮换指定模型实现的密钥，后续请求才会读取新值。"""
        provider = self._key_providers.get(capability_id.strip())
        if provider is None:
            raise ApplicationSetupError(
                "APP_MODEL_NOT_REGISTERED: model capability is not registered"
            )
        return provider.rotate(key)

    async def _refresh_loop(self) -> None:
        """按固定间隔刷新缓存；一次探测失败不应终止整个应用生命周期。"""
        while True:
            await asyncio.sleep(self._health_interval_seconds)
            try:
                await self._registry.refresh_health()
            except Exception:
                # ``refresh_health`` 自身会隔离单适配器故障；此处再防护定时任务意外
                # 退出。错误正文不保存，下一周期可自然恢复。
                continue

    @classmethod
    def _read_setups(cls, values: Mapping[str, str]) -> tuple[ModelSetup, ...]:
        """解析 ``AGENTOS_MODELS`` JSON 数组，并拒绝模糊或含空标识的配置。"""
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
            if key_env is not None and (not isinstance(key_env, str) or not key_env.strip()):
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
            setups.append(
                ModelSetup(
                    capability_id=capability_id,
                    provider=cls._required_text(item, "provider"),
                    models=tuple(model.strip() for model in models),
                    base_url=cls._required_text(item, "baseUrl"),
                    key_env=key_env.strip() if isinstance(key_env, str) else None,
                    version=str(item.get("version", "v1")).strip(),
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
        """取得必填非空字符串，避免不完整配置在网络调用时才失败。"""
        value = item.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ApplicationSetupError(
                f"APP_MODEL_CONFIG_INVALID: {name} must be a non-empty string"
            )
        return value.strip()

    @staticmethod
    def _positive_float(value: object, *, code: str) -> float:
        """将环境或 JSON 数值转换为正浮点，拒绝布尔值和非有限文本。"""
        if isinstance(value, bool):
            raise ApplicationSetupError(f"{code}: value must be greater than zero")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ApplicationSetupError(f"{code}: value must be greater than zero") from exc
        if result <= 0:
            raise ApplicationSetupError(f"{code}: value must be greater than zero")
        return result


__all__ = ["ApplicationSetup", "ApplicationSetupError", "ModelSetup"]
