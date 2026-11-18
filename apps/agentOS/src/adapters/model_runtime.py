"""将统一模型适配器桥接为原生 Agent 所需的结构化生成运行时。"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, nullcontext
from time import monotonic
from typing import Any
from uuid import uuid4

from adapters.model_adapter import (
    StructuredGenerationError,
    StructuredGenerationResult,
)
from adapters.model_diagnostics import safe_stream_diagnostics, safe_transport_diagnostics
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.openai_runtime import ModelInvocationError, decode_json_object
from adapters.prompt_runtime import canonical_hash, prompt_instance_metadata, trust_summary
from adapters.execution_prefix import execution_messages
from contracts.capability import (
    ModelCapabilityEnvelope,
    ModelOutputPolicy,
    ModelInvocationRequest,
)
from contracts.runtime_events import RuntimeEvent
from support.model_stream_policy import ModelStreamPolicy
from adapters.request_diagnostics import resolve_request_budget


# 允许透传的思考档位：GLM 5.3 low/high/max 与 OpenAI 系 low/medium/high 的并集。
_REASONING_EFFORT_VALUES = frozenset({"low", "medium", "high", "max"})
def _validated_reasoning_effort(value: Any) -> str | None:
    """只放行受支持的档位，防止任务输入把任意键值注入供应商请求体。"""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _REASONING_EFFORT_VALUES:
            return normalized
    return None


@dataclass(frozen=True)
class _PreparedRequest:
    request: ModelInvocationRequest
    template_metadata: dict[str, Any]
    instance_metadata: dict[str, str]
    audit: dict[str, Any]
    output_policy: ModelOutputPolicy
    effective_tokens: int | None
    effective_reason: str


class RegisteredModelRuntime:
    """按已冻结的提供商和模型名解析统一适配器的无 SDK 生成运行时。

    本类不缓存供应商客户端、不持有密钥，也不改变注册表。每次调用都经注册表重新
    解析健康适配器，因此应用层撤销或替换失效实现后不会继续调用旧对象。超时、重试
    和限流由外层 ``GuardedModelRuntime`` 统一控制；此桥接层仅负责合同转换。
    """

    supports_continuation = True
    # Streaming tool turns enforce their own provider phase and total deadline;
    # GuardedModelRuntime must not wrap them in a competing wait_for.
    manages_tool_turn_timeout = True

    def __init__(
        self,
        *,
        registry: ModelCompatibilityRegistry,
        provider: str,
        model: str,
        version: str | None = None,
        clock: Callable[[], float] = monotonic,
        wait_for: Callable[[Awaitable[Any], float], Awaitable[Any]] | None = None,
        call_quota: Callable | None = None,
    ) -> None:
        """保存只读路由键；空键在构造期失败，避免节点开始后才发现配置不完整。"""
        self._registry = registry
        self.provider = provider.strip()
        self.model = model.strip()
        self.version = version.strip() if version is not None else None
        self._clock = clock
        self._wait_for = wait_for or _wait_for
        self._call_quota = call_quota
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

    @property
    def supports_tool_calling(self) -> bool:
        return self.describe_model().features.tools is True

    async def generate_tool_turn(self, *, messages, tools, schema, timeout_seconds=120.0,
                                 commit_id=None, max_output_tokens=None, reasoning_effort=None,
                                 temperature=None, progress_callback=None, request_budget=None,
                                 schema_message_index=None, emit_reasoning_deltas=False, **kwargs):
        """One native Function Calling turn through the registered model adapter."""
        if not self.supports_tool_calling:
            raise StructuredGenerationError("MODEL_TOOLS_UNSUPPORTED", "model does not declare tool calling")
        capability = self.describe_model()
        # Providers default to autonomous selection; some thinking endpoints
        # reject an explicit tool_choice even when Function Calling is enabled.
        options = {"tools": tools}
        tokens = max_output_tokens or capability.max_output_tokens
        if tokens is not None:
            options[capability.max_tokens_field or "max_tokens"] = tokens
        effort = _validated_reasoning_effort(reasoning_effort)
        if effort:
            options['reasoning_effort'] = effort
        if temperature is not None:
            options['temperature'] = temperature
        request = ModelInvocationRequest(requestId=commit_id or f"model:{uuid4().hex}", model=self.model,
            messages=messages, responseSchema=schema, schemaMessageIndex=schema_message_index,
            options=options, commitId=commit_id, streamReasoning=emit_reasoning_deltas,
            requestBudget=resolve_request_budget(request_budget, capability, tokens))
        try:
            adapter = self._registry.resolve(self.provider, self.model, version=self.version)
            if progress_callback is not None and getattr(adapter, "supports_streamed_tool_turns", False):
                return await self._stream_tool_turn(adapter, request, progress_callback, timeout_seconds)
            return await self._wait_for(self._invoke(adapter, request, timeout_seconds), timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise StructuredGenerationError("MODEL_TIMEOUT", "model tool turn timed out") from exc
        except ModelInvocationError as exc:
            raise StructuredGenerationError(exc.code, "model tool turn failed", audit={
                "provider": self.provider, "model": self.model, "usage": dict(exc.usage),
                "requestDiagnostics": dict(exc.metadata.get("requestDiagnostics") or {}),
                "streamDiagnostics": safe_stream_diagnostics(exc.metadata.get("streamDiagnostics")),
                "transportDiagnostics": safe_transport_diagnostics(exc.metadata.get("transportDiagnostics"))}) from exc

    async def _invoke(self, adapter, request, timeout):
        slot = self._call_quota(request, timeout) if self._call_quota else nullcontext()
        async with slot as charge:
            response = await adapter.invoke(request)
            if charge is not None:
                charge.observe(response.usage)
            return response

    async def _stream(self, adapter, request, timeout, charge=None):
        slot = self._call_quota(request, timeout) if self._call_quota and charge is None else nullcontext(charge)
        async with slot as charge:
            iterator = adapter.astream(request).__aiter__()
            try:
                async for event in iterator:
                    if charge is not None:
                        charge.observe(event.response.usage if event.response is not None else event.metadata.get("usage"))
                    yield event
            finally:
                closer = getattr(iterator, "aclose", None)
                if callable(closer):
                    await closer()

    async def _stream_tool_turn(self, adapter, request, progress, timeout):
        """Forward public content while retaining the complete tool turn internally."""
        policy = ModelStreamPolicy.from_environment()
        total_timeout = min(timeout, policy.total)
        quota_stack = AsyncExitStack()
        iterator = None
        response = None
        sealed_response = None
        first = False
        provider_active = False
        chunks = length = 0
        started = last_activity = self._clock()
        provider_started = False
        stream_usage = {}

        def audit(reason):
            return {"provider": self.provider, "model": self.model, "usage": dict(stream_usage),
                "streamDiagnostics": {"streamStarted": provider_started, "firstTokenObserved": first,
                    "outputDeltaObserved": first, "deltaCount": chunks,
                    "completionObserved": response is not None or sealed_response is not None, "streamTerminationReason": reason,
                    "elapsedMs": max(0, round((self._clock() - started) * 1000))}}

        def recover_usage_tail(code):
            diagnostics = audit("completed_after_usage_timeout")["streamDiagnostics"]
            usage = dict(stream_usage or sealed_response.usage)
            metadata = {**sealed_response.metadata, "streamDiagnostics": diagnostics, "usageTailTimeoutCode": code}
            if usage:
                metadata["usage"] = usage
            return sealed_response.model_copy(update={"usage": usage, "metadata": metadata})

        try:
            # Overall request time still includes quota admission. Provider
            # first-response/idle clocks begin only after admission, as on the
            # ordinary JSON stream path.
            async with asyncio.timeout(timeout):
                charge = await quota_stack.enter_async_context(self._call_quota(request, timeout)) if self._call_quota else None
                started = last_activity = last_activity_event = self._clock()
                iterator = self._stream(adapter, request, total_timeout, charge).__aiter__()
                provider_started = True
                await progress("model.started", {"provider": self.provider, "model": self.model, "streamingCapability": True})
                while True:
                    try:
                        event = await self._next_stream_event(iterator, started=started, last_activity=last_activity,
                            provider_active=provider_active, ttft_timeout=policy.first_response,
                            idle_timeout=policy.idle, total_timeout=total_timeout)
                    except StopAsyncIteration:
                        break
                    raw_usage = event.metadata.get("usage")
                    if isinstance(raw_usage, dict):
                        stream_usage = dict(raw_usage)
                    if event.event_type in {"activity", "reasoning_delta", "tool_call", "sealed"} or (
                        event.event_type == "delta" and event.delta
                    ):
                        provider_active = True
                        last_activity = self._clock()
                    if event.event_type == "delta" and event.delta:
                        chunks += 1
                        length += len(event.delta)
                        if not first:
                            first = True
                            await progress("model.first_token", {})
                        await progress("model.output.delta", {"delta": event.delta})
                    elif event.event_type == "reasoning_delta" and event.delta:
                        await progress("model.reasoning.delta", {"delta": event.delta})
                    elif event.event_type == "sealed":
                        if event.response is None:
                            raise ModelInvocationError("MODEL_RESPONSE_INVALID", "sealed stream has no response")
                        sealed_response = event.response
                    elif event.event_type == "completed":
                        response = event.response
                        break
                    if provider_active and self._clock() - last_activity_event >= .35:
                        last_activity_event = self._clock()
                        await progress("model.activity", {"elapsedMs": round((last_activity_event-started)*1000),
                            "receivedChunks": chunks, "receivedLength": length})
                if response is None:
                    raise StructuredGenerationError("MODEL_STREAM_INCOMPLETE", "tool stream ended without a complete response")
        except asyncio.TimeoutError as exc:
            if sealed_response is None:
                raise StructuredGenerationError("MODEL_TIMEOUT", "model tool turn timed out", audit=audit("MODEL_TIMEOUT")) from exc
            response = recover_usage_tail("MODEL_TIMEOUT")
        except StructuredGenerationError as exc:
            if sealed_response is not None and exc.code in {"MODEL_IDLE_TIMEOUT", "MODEL_TOTAL_TIMEOUT", "MODEL_TIMEOUT"}:
                response = recover_usage_tail(exc.code)
            else:
                exc.audit = {**audit(exc.code), **exc.audit}
                raise
        except ModelInvocationError as exc:
            exc.metadata.setdefault("streamDiagnostics", audit(exc.code)["streamDiagnostics"])
            raise
        finally:
            try:
                closer = getattr(iterator, "aclose", None)
                if callable(closer):
                    await closer()
            finally:
                await quota_stack.aclose()
        # Provider resources are settled before reporting completion. Display
        # backpressure cannot invalidate an already parsed, sealed model turn.
        try:
            await self._wait_for(progress("model.completed", {"provider": response.provider, "model": response.model,
                "receivedLength": length, "usage": dict(response.usage),
                "finishReason": response.metadata.get("finishReason")}), timeout)
        except asyncio.TimeoutError:
            pass
        return response

    async def _next_stream_event(self, iterator, *, started, last_activity, provider_active,
                                 ttft_timeout, idle_timeout, total_timeout):
        """One deadline policy shared by ordinary and tool-capable streams."""
        now = self._clock()
        total_left = total_timeout - (now - started)
        if total_left <= 0:
            raise StructuredGenerationError("MODEL_TOTAL_TIMEOUT", "model stream total timeout exceeded")
        window = idle_timeout if provider_active else ttft_timeout
        activity_left = window - (now - (last_activity if provider_active else started))
        activity_code = "MODEL_IDLE_TIMEOUT" if provider_active else "MODEL_TTFT_TIMEOUT"
        if activity_left <= 0:
            raise StructuredGenerationError(activity_code, "model stream activity deadline exceeded", retryable=True)
        timeout_code = "MODEL_TOTAL_TIMEOUT" if total_left <= activity_left else activity_code
        try:
            return await self._wait_for(anext(iterator), min(total_left, activity_left))
        except asyncio.TimeoutError as exc:
            raise StructuredGenerationError(timeout_code, "model stream deadline exceeded",
                retryable=timeout_code != "MODEL_TOTAL_TIMEOUT") from exc

    async def generate_json(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        system_prompt: str | None = None,
        thinking_mode: str = "disabled",
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float = 120.0,
        max_output_tokens: int | None = None,
        prompt_version: str = "native-capability.v3",
        commit_id: str | None = None,
        prompt_metadata: dict[str, Any] | None = None,
        continuation: list[dict[str, str]] | None = None,
        prefix_schema: dict[str, Any] | None = None,
    ) -> StructuredGenerationResult:
        """把原生 JSON 生成请求转换为统一模型调用，并返回安全审计投影。"""
        # thinking_mode 的供应商映射发生在适配器层；本桥接只转发显式声明的
        # reasoning_effort（OpenAI 兼容参数），是否外发由适配器按提供方裁决。
        del thinking_mode
        reasoning_effort = _validated_reasoning_effort(reasoning_effort)
        self._validate_generation_options(temperature, max_output_tokens)
        if timeout_seconds <= 0:
            raise StructuredGenerationError(
                "MODEL_TIMEOUT_INVALID",
                "timeout_seconds must be greater than zero",
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
        selected_prompt_identity: dict[str, str] = {}
        last_prompt_audit: dict[str, Any] = {}
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
            prepared = self._prepare_request(
                prompt=prompt, schema=schema, system_prompt=system_prompt,
                prompt_metadata=prompt_metadata, prompt_version=prompt_version,
                capability=capability, request_id=request_id, commit_id=commit_id,
                max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort,
                temperature=temperature, streaming=False,
                continuation=continuation, prefix_schema=prefix_schema,
            )
            request = prepared.request
            safe_prompt_metadata = prepared.template_metadata
            invocation_identity = prepared.instance_metadata
            candidate_prompt_audit = last_prompt_audit = prepared.audit
            policy = prepared.output_policy
            effective_tokens = prepared.effective_tokens
            effective_reason = prepared.effective_reason
            try:
                response = await self._wait_for(
                    self._invoke(adapter, request, candidate_timeout),
                    candidate_timeout,
                )
                selected_capability = capability
                selected_policy = policy
                selected_effective_tokens = effective_tokens
                selected_reason = effective_reason
                selected_prompt_identity = invocation_identity
                break
            except asyncio.TimeoutError as exc:
                last_error = exc
                if index + 1 < len(candidates):
                    continue
                raise StructuredGenerationError(
                    "MODEL_TIMEOUT",
                    "model invocation timed out",
                    audit=candidate_prompt_audit,
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
                        **candidate_prompt_audit,
                        "provider": capability.provider,
                        "model": capability.model,
                        "usage": dict(getattr(exc, "usage", {}) or {}),
                        "finishReason": (getattr(exc, "metadata", {}) or {}).get("finishReason"),
                        "candidateFingerprint": (getattr(exc, "metadata", {}) or {}).get("candidateFingerprint"),
                        "requestDiagnostics": dict((getattr(exc, "metadata", {}) or {}).get("requestDiagnostics") or {}),
                        "capability": capability.model_dump(by_alias=True, mode="json", exclude_none=True),
                        "outputPolicy": policy.value,
                        "requestedOutputTokens": max_output_tokens,
                        "effectiveOutputTokens": effective_tokens,
                        "effectiveReason": effective_reason,
                        "outputExhausted": exc.code == "MODEL_OUTPUT_EXHAUSTED",
                    },
                ) from exc
            except StructuredGenerationError:
                raise
            except Exception as exc:
                raise StructuredGenerationError(
                    "MODEL_PROVIDER_FAILED",
                    "model provider invocation failed",
                    audit=candidate_prompt_audit,
                ) from exc
        if response is None:
            if isinstance(last_error, ModelInvocationError):
                raise StructuredGenerationError(
                    last_error.code,
                    str(last_error),
                    audit=last_prompt_audit,
                ) from last_error
            raise StructuredGenerationError(
                "MODEL_PROVIDER_FAILED",
                "model provider invocation failed",
                audit=last_prompt_audit,
            )
        finish_reason = str(response.metadata.get("finishReason") or "") or None
        output_exhausted = finish_reason in {"length", "max_tokens", "max_output_tokens"}
        if output_exhausted:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_EXHAUSTED",
                "model provider exhausted its output capacity before completing the response",
                retryable=False,
                audit={
                    **safe_prompt_metadata,
                    **selected_prompt_identity,
                    "promptVersion": prompt_version,
                    "requestType": self._request_type(prompt),
                    "providerFamily": selected_capability.provider or self.provider,
                    "modelVersion": selected_capability.version or self.version,
                    "streaming": False,
                    "trustSummary": trust_summary(prompt),
                    "provider": selected_capability.provider,
                    "model": selected_capability.model,
                    "requestDiagnostics": dict(response.metadata.get("requestDiagnostics") or {}),
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
            promptTemplateHash=safe_prompt_metadata["promptTemplateHash"],
            promptInstanceHash=selected_prompt_identity["promptInstanceHash"],
            stablePrefixHash=safe_prompt_metadata["stablePrefixHash"],
            schemaHash=selected_prompt_identity["schemaHash"],
            kernelVersion=safe_prompt_metadata.get("kernelVersion"),
            preset=safe_prompt_metadata.get("preset"),
            presetVersion=safe_prompt_metadata.get("presetVersion"),
            capabilityId=safe_prompt_metadata.get("capabilityId"),
            capabilityPolicyVersion=safe_prompt_metadata.get("capabilityPolicyVersion"),
            requestProtocolVersion=safe_prompt_metadata.get("requestProtocolVersion"),
            outputProtocolVersion=safe_prompt_metadata.get("outputProtocolVersion"),
            promptRendererVersion=safe_prompt_metadata.get("promptRendererVersion"),
            requestType=self._request_type(prompt),
            providerFamily=(selected_capability.provider or self.provider),
            modelVersion=(selected_capability.version or self.version),
            streaming=False,
            trustSummary=trust_summary(prompt),
            requestDiagnostics=dict(response.metadata.get("requestDiagnostics") or {}),
            usage=dict(response.usage),
            finishReason=finish_reason,
            capability=selected_capability,
            outputPolicy=selected_policy,
            requestedOutputTokens=max_output_tokens,
            effectiveOutputTokens=selected_effective_tokens,
            effectiveReason=selected_reason,
            outputExhausted=False,
        )

    async def stream_generate_json(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        system_prompt: str | None = None,
        run_id: str,
        node_id: str | None = None,
        attempt_id: str | None = None,
        ttft_timeout: float | None = None,
        idle_timeout: float | None = None,
        total_timeout: float | None = None,
        thinking_mode: str = "disabled",
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        prompt_version: str = "native-capability.v3",
        commit_id: str | None = None,
        emit_output_deltas: bool = True,
        emit_reasoning_deltas: bool = False,
        prompt_metadata: dict[str, Any] | None = None,
    ):
        """Consume a provider stream while keeping structured output private when requested."""
        del thinking_mode
        reasoning_effort = _validated_reasoning_effort(reasoning_effort)
        self._validate_generation_options(temperature, max_output_tokens)
        policy = ModelStreamPolicy.from_environment()
        ttft_timeout = policy.first_response if ttft_timeout is None else ttft_timeout
        idle_timeout = policy.idle if idle_timeout is None else idle_timeout
        total_timeout = policy.total if total_timeout is None else total_timeout
        if min(ttft_timeout, idle_timeout, total_timeout) <= 0:
            raise StructuredGenerationError("MODEL_TIMEOUT_INVALID", "stream timeouts must be positive")
        try:
            candidates = self._registry.resolve_candidates(self.provider, self.model, version=self.version)
        except LookupError as exc:
            raise StructuredGenerationError("MODEL_NOT_CONFIGURED", "requested model adapter is not registered") from exc
        adapter = candidates[0]
        streamer = getattr(adapter, "astream", None)
        if not callable(streamer):
            raise StructuredGenerationError("MODEL_STREAM_UNSUPPORTED", "model adapter does not support streaming")
        try:
            capability = adapter.describe_model(self.model)
        except Exception:
            capability = ModelCapabilityEnvelope.unknown(
                provider=self.provider, model=self.model, version=self.version
            )
        request_id = commit_id or f"model:{uuid4().hex}"
        prepared = self._prepare_request(
            prompt=prompt, schema=schema, system_prompt=system_prompt,
            prompt_metadata=prompt_metadata, prompt_version=prompt_version,
            capability=capability, request_id=request_id, commit_id=commit_id,
            max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort,
            temperature=temperature, streaming=True,
        )
        request, safe_audit = prepared.request, prepared.audit
        if emit_reasoning_deltas:
            request = request.model_copy(update={"stream_reasoning": True})
        safe_audit.update(capability=capability.model_dump(by_alias=True, mode="json"),
            outputPolicy=prepared.output_policy.value, effectiveOutputTokens=prepared.effective_tokens,
            effectiveReason=prepared.effective_reason)
        # Queue for shared quota before starting provider TTFT/idle clocks.
        quota_stack = AsyncExitStack()
        charge = await quota_stack.enter_async_context(self._call_quota(request, total_timeout)) if self._call_quota else None
        seq = 0
        started = self._clock()
        last_activity = started
        last_activity_event = started
        first = False
        provider_active = False
        received_chunks = 0
        public_activity_pending = False
        buffer: list[str] = []
        finish_reason: str | None = None
        stream_usage: dict[str, Any] = {}
        stream_diagnostics: dict[str, Any] = {}
        iterator = self._stream(adapter, request, total_timeout, charge)

        def emit(kind: str, payload: dict[str, Any] | None = None) -> RuntimeEvent:
            nonlocal seq
            seq += 1
            return RuntimeEvent(
                eventType=kind,
                runId=run_id,
                nodeId=node_id,
                attemptId=attempt_id,
                sequence=seq,
                payload=payload or {},
            )

        def activity_payload(idle_ms: float) -> dict[str, Any]:
            return {
                "elapsedMs": round((self._clock() - started) * 1000),
                "idleMs": round(max(0.0, idle_ms) * 1000),
                "receivedChunks": received_chunks,
                "receivedLength": sum(map(len, buffer)),
            }

        completed = False
        try:
            yield emit("model.started", {
                "requestId": request_id,
                "provider": self.provider,
                "model": self.model,
                "streamingCapability": True,
                **safe_audit,
            })
            while True:
                try:
                    item = await self._next_stream_event(iterator, started=started, last_activity=last_activity,
                        provider_active=provider_active, ttft_timeout=ttft_timeout,
                        idle_timeout=idle_timeout, total_timeout=total_timeout)
                except StopAsyncIteration:
                    break
                except ModelInvocationError as exc:
                    audit = {
                        "provider": self.provider,
                        "model": self.model,
                        "usage": dict(getattr(exc, "usage", {}) or {}),
                        "finishReason": (getattr(exc, "metadata", {}) or {}).get("finishReason"),
                        "candidateFingerprint": (getattr(exc, "metadata", {}) or {}).get("candidateFingerprint"),
                        "requestDiagnostics": dict((getattr(exc, "metadata", {}) or {}).get("requestDiagnostics") or {}),
                    }
                    stream_diagnostics = safe_stream_diagnostics(
                        (getattr(exc, "metadata", {}) or {}).get("streamDiagnostics"))
                    if stream_diagnostics:
                        audit["streamDiagnostics"] = dict(stream_diagnostics)
                    raise StructuredGenerationError(
                        exc.code,
                        "model provider stream failed",
                        retryable=exc.code in self._FAILOVER_CODES,
                        audit=audit,
                    ) from exc
                now = self._clock()
                if item.event_type in {"activity", "reasoning_delta", "tool_call"}:
                    provider_active = True
                    idle_ms = now - last_activity
                    last_activity = now
                    if item.event_type == "reasoning_delta" and item.delta and emit_reasoning_deltas:
                        yield emit("model.reasoning.delta", {"delta": item.delta})
                    if now - last_activity_event >= 0.35:
                        last_activity_event = now
                        yield emit("model.activity", activity_payload(idle_ms))
                elif item.event_type == "delta" and item.delta:
                    provider_active = True
                    received_chunks += 1
                    buffer.append(item.delta)
                    public_activity_pending = True
                    idle_ms = now - last_activity
                    last_activity = now
                    if not first:
                        first = True
                        yield emit("model.first_token", activity_payload(idle_ms))
                    if emit_output_deltas:
                        yield emit("model.output.delta", {"delta": item.delta})
                    if received_chunks == 1 or now - last_activity_event >= 0.35:
                        last_activity_event = now
                        public_activity_pending = False
                        yield emit("model.activity", activity_payload(idle_ms))
                elif item.event_type == "completed":
                    safe_audit["requestDiagnostics"] = dict(item.metadata.get("requestDiagnostics") or {})
                    raw_finish_reason = item.metadata.get("finishReason")
                    finish_reason = str(raw_finish_reason or "") or None
                    raw_usage = item.metadata.get("usage")
                    if isinstance(raw_usage, dict):
                        stream_usage = dict(raw_usage)
                    raw_diagnostics = item.metadata.get("streamDiagnostics")
                    if isinstance(raw_diagnostics, dict):
                        stream_diagnostics = dict(raw_diagnostics)
                    completed = True
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, StructuredGenerationError):
                exc.audit = {**safe_audit, **exc.audit}
                if charge is not None:
                    charge.observe(exc.audit.get("usage"))
            raise
        finally:
            try:
                close = getattr(iterator, "aclose", None)
                if callable(close):
                    await close()
            finally:
                await quota_stack.aclose()
        if not first:
            raise StructuredGenerationError(
                "MODEL_TTFT_TIMEOUT",
                "model stream completed without output",
                audit=safe_audit,
            )
        if not completed:
            # A provider adapter normally emits completed; treating a clean end
            # as parseable keeps compatible fake streams useful without relaxing
            # TTFT/idle/total ownership.
            completed = True
        # Usage is reported before JSON decoding. A malformed answer still
        # consumed provider tokens and must remain measurable when repaired.
        completed_audit = {
            **safe_audit,
            "provider": capability.provider or self.provider,
            "model": capability.model or self.model,
            "usage": dict(stream_usage),
            "finishReason": finish_reason,
            "latencyMs": round((self._clock() - started) * 1000),
        }
        if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_EXHAUSTED",
                "model provider exhausted its output capacity before completing the response",
                retryable=False,
                audit=completed_audit,
            )
        if public_activity_pending:
            yield emit("model.activity", activity_payload(0.0))
        try:
            data = decode_json_object("".join(buffer), finish_reason=finish_reason)
        except ModelInvocationError as exc:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_INVALID_JSON",
                "streamed model output is not valid JSON",
                audit={**completed_audit, "candidateFingerprint": canonical_hash({"text": "".join(buffer)})},
            ) from exc
        yield emit("model.completed", {
            "receivedLength": sum(map(len, buffer)),
            "data": data,
            "provider": self.provider,
            "model": self.model,
            "usage": dict(stream_usage),
            "finishReason": finish_reason,
            "latencyMs": round((self._clock() - started) * 1000),
            "streamDiagnostics": dict(stream_diagnostics),
            **safe_audit,
        })

    @staticmethod
    def _validate_generation_options(temperature, max_output_tokens):
        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or not 0 <= float(temperature) <= 2
        ):
            raise StructuredGenerationError(
                "MODEL_TEMPERATURE_INVALID", "temperature must be between 0 and 2"
            )
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_BUDGET_INVALID", "max_output_tokens must be greater than zero"
            )

    def _prepare_request(
        self, *, prompt: str, schema: dict[str, Any], system_prompt: str | None,
        prompt_metadata: dict[str, Any] | None, prompt_version: str,
        capability: ModelCapabilityEnvelope, request_id: str, commit_id: str | None,
        max_output_tokens: int | None, reasoning_effort: str | None,
        temperature: float | None, streaming: bool,
        continuation: list[dict[str, str]] | None = None,
        prefix_schema: dict[str, Any] | None = None,
    ) -> _PreparedRequest:
        """Build the same protocol input and audit identity for every transport mode.

        Candidate-specific capabilities are resolved by the caller; failover and
        streaming lifetime remain outside request construction.
        """
        messages, schema_message_index = execution_messages(
            prompt=prompt, system_prompt=system_prompt, provider=self.provider, prompt_metadata=prompt_metadata,
        )
        if continuation is not None:
            if not isinstance(continuation, list) or not continuation or any(
                not isinstance(item, dict) or set(item) != {"role", "content"} or item["role"] not in {"assistant", "user"}
                or not isinstance(item["content"], str) for item in continuation
            ) or continuation[-1]["role"] != "user":
                raise StructuredGenerationError("MODEL_CONTINUATION_INVALID", "continuation must end in user data")
            messages.extend(dict(item) for item in continuation)
        if prefix_schema is not None and not continuation:
            raise StructuredGenerationError("MODEL_CONTINUATION_INVALID", "a prefix contract requires continuation messages")
        safe_prompt_metadata = self._prompt_metadata(
            prompt_metadata=prompt_metadata,
            system_prompt=system_prompt,
            prompt_version=prompt_version,
        )
        if schema_message_index is not None:
            safe_prompt_metadata["stablePrefixHash"] = canonical_hash(messages[:schema_message_index])
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
        elif capability.max_output_tokens is not None:
            # 调用方未指定时，能力目录登记的输出上限必须显式随请求发送：
            # "未指定"不得等价于供应商服务端默认额度（结构化 JSON 会被静默截断）。
            field = capability.max_tokens_field or "max_tokens"
            options[field] = capability.max_output_tokens
            policy = ModelOutputPolicy.CATALOG_DEFAULT
            effective_tokens = capability.max_output_tokens
            effective_reason = "catalog_default"
        if reasoning_effort:
            options["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            options["temperature"] = float(temperature)
        invocation_identity = prompt_instance_metadata(
            messages=messages,
            response_schema=dict(schema),
            provider_family=capability.provider or self.provider,
            model=capability.model or self.model,
            model_version=capability.version or self.version,
            behavior_options={**options, **({"prefixResponseSchemaHash": canonical_hash(prefix_schema)}
                                           if prefix_schema is not None else {})},
        )
        candidate_prompt_audit = {
            **safe_prompt_metadata,
            **invocation_identity,
            "promptVersion": prompt_version,
            "requestType": self._request_type(prompt),
            "providerFamily": capability.provider or self.provider,
            "modelVersion": capability.version or self.version,
            "streaming": streaming,
            "trustSummary": trust_summary(prompt),
        }
        request = ModelInvocationRequest(
            requestId=request_id,
            model=self.model,
            messages=messages,
            responseSchema=dict(schema),
            prefixResponseSchema=prefix_schema,
            schemaMessageIndex=schema_message_index,
            requestBudget=resolve_request_budget((prompt_metadata or {}).get("requestBudget"), capability, effective_tokens,
                workset=(prompt_metadata or {}).get("materialWorkset") is True),
            options=options,
            commitId=commit_id,
        )
        return _PreparedRequest(
            request, safe_prompt_metadata, invocation_identity, candidate_prompt_audit,
            policy, effective_tokens, effective_reason,
        )

    @staticmethod
    def _prompt_metadata(
        *,
        prompt_metadata: dict[str, Any] | None,
        system_prompt: str | None,
        prompt_version: str,
    ) -> dict[str, Any]:
        allowed = {
            "promptTemplateHash", "stablePrefixHash", "kernelVersion", "preset",
            "presetVersion", "capabilityId", "capabilityPolicyVersion",
            "requestProtocolVersion", "outputProtocolVersion", "promptRendererVersion",
        }
        metadata = {
            key: value for key, value in dict(prompt_metadata or {}).items() if key in allowed
        }
        if "stablePrefixHash" not in metadata:
            metadata["stablePrefixHash"] = canonical_hash(
                ([{"role": "system", "content": system_prompt}] if system_prompt else [])
            )
        if "promptTemplateHash" not in metadata:
            metadata["promptTemplateHash"] = canonical_hash({
                "legacyPromptVersion": prompt_version,
                "systemPrompt": system_prompt or "",
            })
        return metadata

    @staticmethod
    def _request_type(prompt: str) -> str | None:
        try:
            payload = json.loads(prompt)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        request_type = payload.get("requestType")
        if not isinstance(request_type, str):
            nested = payload.get("executionRequest")
            request_type = nested.get("requestType") if isinstance(nested, dict) else None
        return request_type if isinstance(request_type, str) and request_type else None


async def _wait_for(awaitable: Awaitable[Any], timeout: float) -> Any:
    """Keep asyncio behind an injectable deadline boundary for deterministic tests."""
    return await asyncio.wait_for(awaitable, timeout=timeout)


__all__ = ["RegisteredModelRuntime"]
