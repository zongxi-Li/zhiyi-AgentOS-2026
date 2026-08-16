"""将统一模型适配器桥接为原生 Agent 所需的结构化生成运行时。"""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any
from uuid import uuid4

from adapters.model_adapter import (
    StructuredGenerationError,
    StructuredGenerationResult,
)
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.openai_runtime import ModelInvocationError
from contracts.capability import ModelInvocationRequest


class RegisteredModelRuntime:
    """按已冻结的提供商和模型名解析统一适配器的无 SDK 生成运行时。

    本类不缓存供应商客户端、不持有密钥，也不改变注册表。每次调用都经注册表重新
    解析健康适配器，因此应用层撤销或替换失效实现后不会继续调用旧对象。超时、重试
    和限流由外层 ``GuardedModelRuntime`` 统一控制；此桥接层仅负责合同转换。
    """

    def __init__(
        self,
        *,
        registry: ModelCompatibilityRegistry,
        provider: str,
        model: str,
    ) -> None:
        """保存只读路由键；空键在构造期失败，避免节点开始后才发现配置不完整。"""
        self._registry = registry
        self.provider = provider.strip()
        self.model = model.strip()
        if not self.provider:
            raise ValueError("MODEL_PROVIDER_REQUIRED: Agent profile must set modelProvider")
        if not self.model:
            raise ValueError("MODEL_NAME_REQUIRED: Agent profile must set modelName")

    def is_available(self) -> bool:
        """返回当前路由是否能解析到健康适配器，不执行网络连通性探测。"""
        try:
            self._registry.resolve(self.provider, self.model)
        except LookupError:
            return False
        return True

    async def generate_json(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        thinking_mode: str = "disabled",
        timeout_seconds: float = 120.0,
        max_output_tokens: int = 4096,
        prompt_version: str = "native-capability.v1",
        commit_id: str | None = None,
    ) -> StructuredGenerationResult:
        """把原生 JSON 生成请求转换为统一模型调用，并返回安全审计投影。"""
        del thinking_mode
        if timeout_seconds <= 0:
            raise StructuredGenerationError(
                "MODEL_TIMEOUT_INVALID",
                "timeout_seconds must be greater than zero",
            )
        if max_output_tokens <= 0:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_BUDGET_INVALID",
                "max_output_tokens must be greater than zero",
            )
        request = ModelInvocationRequest(
            requestId=commit_id or f"model:{uuid4().hex}",
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            responseSchema=dict(schema),
            options={"max_tokens": max_output_tokens},
            commitId=commit_id,
        )
        started = monotonic()
        try:
            adapter = self._registry.resolve(self.provider, self.model)
            response = await asyncio.wait_for(
                adapter.invoke(request),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise StructuredGenerationError(
                "MODEL_TIMEOUT",
                "model invocation timed out",
            ) from exc
        except ModelInvocationError as exc:
            raise StructuredGenerationError(exc.code, str(exc)) from exc
        except LookupError as exc:
            raise StructuredGenerationError(
                "MODEL_NOT_CONFIGURED",
                "requested model adapter is not registered or healthy",
            ) from exc
        except Exception as exc:
            raise StructuredGenerationError(
                "MODEL_PROVIDER_FAILED",
                "model provider invocation failed",
            ) from exc
        return StructuredGenerationResult(
            data=dict(response.content),
            provider=response.provider,
            model=response.model,
            latencyMs=round((monotonic() - started) * 1000),
            promptVersion=prompt_version,
            usage=dict(response.usage),
        )


__all__ = ["RegisteredModelRuntime"]
