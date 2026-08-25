"""将统一模型适配器桥接为原生 Agent 所需的结构化生成运行时。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any
from uuid import uuid4

from adapters.model_adapter import (
    StructuredGenerationError,
    StructuredGenerationResult,
)
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.openai_runtime import ModelInvocationError
from contracts.capability import (
    ModelCapabilityEnvelope,
    ModelOutputPolicy,
    ModelInvocationRequest,
)


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
        version: str | None = None,
        clock: Callable[[], float] = monotonic,
        wait_for: Callable[[Awaitable[Any], float], Awaitable[Any]] | None = None,
    ) -> None:
        """保存只读路由键；空键在构造期失败，避免节点开始后才发现配置不完整。"""
        self._registry = registry
        self.provider = provider.strip()
        self.model = model.strip()
        self.version = version.strip() if version is not None else None
        self._clock = clock
        self._wait_for = wait_for or _wait_for
        if not self.provider:
            raise ValueError("MODEL_PROVIDER_REQUIRED: Agent profile must set modelProvider")
        if not self.model:
            raise ValueError("MODEL_NAME_REQUIRED: Agent profile must set modelName")

    def is_available(self) -> bool:
        """返回当前路由是否能解析到健康适配器，不执行网络连通性探测。"""
        try:
            self._registry.resolve(self.provider, self.model, version=self.version)
        except LookupError:
            return False
        return True

    def describe_model(self) -> ModelCapabilityEnvelope:
        """读取当前首选模型路由的能力，不触发远端探测。"""
        return self._registry.describe_model(
            self.provider,
            self.model,
            version=self.version,
        )

    _FAILOVER_CODES = frozenset(
        {
            "MODEL_TIMEOUT",
            "MODEL_RATE_LIMITED",
            "MODEL_TEMPORARY_UNAVAILABLE",
            "MODEL_PROVIDER_FAILED",
        }
    )

    async def generate_json(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        thinking_mode: str = "disabled",
        timeout_seconds: float = 120.0,
        max_output_tokens: int | None = None,
        prompt_version: str = "native-capability.v3",
        commit_id: str | None = None,
    ) -> StructuredGenerationResult:
        """把原生 JSON 生成请求转换为统一模型调用，并返回安全审计投影。"""
        del thinking_mode
        if timeout_seconds <= 0:
            raise StructuredGenerationError(
                "MODEL_TIMEOUT_INVALID",
                "timeout_seconds must be greater than zero",
            )
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_BUDGET_INVALID",
                "max_output_tokens must be greater than zero",
            )
        request_id = commit_id or f"model:{uuid4().hex}"
        started = self._clock()
        try:
            candidates = self._registry.resolve_candidates(
                self.provider,
                self.model,
                version=self.version,
            )
        except LookupError as exc:
            raise StructuredGenerationError(
                "MODEL_NOT_CONFIGURED",
                "requested model adapter is not registered or healthy",
            ) from exc
        response = None
        last_error: ModelInvocationError | asyncio.TimeoutError | None = None
        selected_capability: ModelCapabilityEnvelope | None = None
        selected_policy = ModelOutputPolicy.API_CONTROLLED
        selected_effective_tokens: int | None = None
        selected_reason = "provider_default"
        for index, adapter in enumerate(candidates):
            # ``timeout_seconds`` 是整个模型选择动作的上限，而不是每个候选各自的
            # 上限。剩余时间在尚未尝试的候选之间均分：主实现慢超时时备实现仍有机会
            # 返回，同时候选数增加也不会线性放大用户等待时间。
            remaining = timeout_seconds - (self._clock() - started)
            if remaining <= 0:
                raise StructuredGenerationError(
                    "MODEL_TIMEOUT",
                    "model invocation timed out",
                )
            candidate_timeout = remaining / (len(candidates) - index)
            describer = getattr(adapter, "describe_model", None)
            capability = (
                describer(self.model)
                if callable(describer)
                else ModelCapabilityEnvelope.unknown(
                    provider=self.provider,
                    model=self.model,
                    version=self.version,
                )
            )
            options: dict[str, Any] = {}
            policy = ModelOutputPolicy.API_CONTROLLED
            effective_tokens: int | None = None
            effective_reason = "provider_default"
            if max_output_tokens is not None:
                field = capability.max_tokens_field or "max_tokens"
                options[field] = max_output_tokens
                policy = ModelOutputPolicy.EXPLICIT
                effective_tokens = max_output_tokens
                effective_reason = "explicit_request"
            elif capability.max_tokens_required:
                if capability.max_output_tokens is None:
                    raise StructuredGenerationError(
                        "MODEL_CAPABILITY_INVALID",
                        "provider requires an output token field but declares no value",
                    )
                field = capability.max_tokens_field or "max_tokens"
                options[field] = capability.max_output_tokens
                policy = ModelOutputPolicy.PROVIDER_REQUIRED
                effective_tokens = capability.max_output_tokens
                effective_reason = "provider_required"
            request = ModelInvocationRequest(
                requestId=request_id,
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                responseSchema=dict(schema),
                options=options,
                commitId=commit_id,
            )
            try:
                response = await self._wait_for(
                    adapter.invoke(request),
                    candidate_timeout,
                )
                selected_capability = capability
                selected_policy = policy
                selected_effective_tokens = effective_tokens
                selected_reason = effective_reason
                break
            except asyncio.TimeoutError as exc:
                last_error = exc
                if index + 1 < len(candidates):
                    continue
                raise StructuredGenerationError(
                    "MODEL_TIMEOUT",
                    "model invocation timed out",
                ) from exc
            except ModelInvocationError as exc:
                last_error = exc
                if exc.code in self._FAILOVER_CODES and index + 1 < len(candidates):
                    continue
                raise StructuredGenerationError(
                    exc.code,
                    str(exc),
                    # 容量耗尽需进入分解/分片恢复，普通重试同一语义单元
                    # 只会重复失败并放大费用。
                    retryable=exc.code in self._FAILOVER_CODES,
                    audit={
                        "provider": capability.provider,
                        "model": capability.model,
                        "usage": dict(getattr(exc, "usage", {}) or {}),
                        "finishReason": (getattr(exc, "metadata", {}) or {}).get("finishReason"),
                        "capability": capability.model_dump(by_alias=True, mode="json", exclude_none=True),
                        "outputPolicy": policy.value,
                        "requestedOutputTokens": max_output_tokens,
                        "effectiveOutputTokens": effective_tokens,
                        "effectiveReason": effective_reason,
                        "outputExhausted": exc.code == "MODEL_OUTPUT_EXHAUSTED",
                    },
                ) from exc
            except Exception as exc:
                raise StructuredGenerationError(
                    "MODEL_PROVIDER_FAILED",
                    "model provider invocation failed",
                ) from exc
        if response is None:
            if isinstance(last_error, ModelInvocationError):
                raise StructuredGenerationError(last_error.code, str(last_error)) from last_error
            raise StructuredGenerationError(
                "MODEL_PROVIDER_FAILED",
                "model provider invocation failed",
            )
        finish_reason = str(response.metadata.get("finishReason") or "") or None
        output_exhausted = finish_reason in {"length", "max_tokens", "max_output_tokens"}
        if output_exhausted:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_EXHAUSTED",
                "model provider exhausted its output capacity before completing the response",
                retryable=False,
                audit={
                    "provider": selected_capability.provider,
                    "model": selected_capability.model,
                    "usage": dict(response.usage),
                    "finishReason": finish_reason,
                    "capability": selected_capability.model_dump(
                        by_alias=True, mode="json", exclude_none=True
                    ),
                    "outputPolicy": selected_policy.value,
                    "requestedOutputTokens": max_output_tokens,
                    "effectiveOutputTokens": selected_effective_tokens,
                    "effectiveReason": selected_reason,
                    "outputExhausted": True,
                },
            )
        return StructuredGenerationResult(
            data=dict(response.content),
            provider=response.provider,
            model=response.model,
            latencyMs=round((self._clock() - started) * 1000),
            promptVersion=prompt_version,
            promptTemplateHash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            usage=dict(response.usage),
            finishReason=finish_reason,
            capability=selected_capability,
            outputPolicy=selected_policy,
            requestedOutputTokens=max_output_tokens,
            effectiveOutputTokens=selected_effective_tokens,
            effectiveReason=selected_reason,
            outputExhausted=False,
        )

async def _wait_for(awaitable: Awaitable[Any], timeout: float) -> Any:
    """Keep asyncio behind an injectable deadline boundary for deterministic tests."""
    return await asyncio.wait_for(awaitable, timeout=timeout)


__all__ = ["RegisteredModelRuntime"]
