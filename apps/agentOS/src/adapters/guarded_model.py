"""模型外部副作用的超时、重试、限流与安全错误包装器。

包装器只处理调用调度，不保存 prompt、schema 或模型响应。稳定 ``commit_id`` 会原样
传给应用层模型运行时，使支持幂等的供应商能够把同一节点尝试识别为同一调用边界。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeVar
from uuid import uuid4

from adapters.model_adapter import (
    StructuredGenerationError,
    StructuredGenerationResult,
    StructuredGenerationRuntime,
)
from contracts.runtime_events import RuntimeEvent


_Result = TypeVar("_Result")
_RETRYABLE_CODES = frozenset(
    {"MODEL_TIMEOUT", "MODEL_RATE_LIMITED", "MODEL_TEMPORARY_UNAVAILABLE"}
)


class _CallGate:
    """在单个包装器范围内限制并发和调用起始间隔。

    运行时对象通常按应用依赖生命周期创建，因此闸门不使用无锁全局变量；不同模型
    实例不会相互阻塞。同一实例的重试会再次经过闸门，避免故障时放大上游压力。
    """

    def __init__(self, *, max_concurrency: int, min_interval_seconds: float) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must not be negative")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._spacing_lock = asyncio.Lock()
        self._min_interval_seconds = min_interval_seconds
        self._last_started: float | None = None

    async def call(self, operation: Callable[[], Awaitable[_Result]]) -> _Result:
        """在取得并发许可且满足最小间隔后执行一次外部调用。"""
        async with self._semaphore:
            async with self._spacing_lock:
                now = asyncio.get_running_loop().time()
                if self._last_started is not None:
                    remaining = self._min_interval_seconds - (now - self._last_started)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                self._last_started = asyncio.get_running_loop().time()
            return await operation()

    @asynccontextmanager
    async def stream_slot(self):
        """Hold one concurrency slot for the complete provider stream."""
        await self._semaphore.acquire()
        try:
            async with self._spacing_lock:
                now = asyncio.get_running_loop().time()
                if self._last_started is not None:
                    remaining = self._min_interval_seconds - (now - self._last_started)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                self._last_started = asyncio.get_running_loop().time()
            yield
        finally:
            self._semaphore.release()


class GuardedModelRuntime:
    """为任意结构化模型运行时添加一致的外部调用保护。"""

    def __init__(
        self,
        *,
        delegate: StructuredGenerationRuntime,
        retries: int = 0,
        max_concurrency: int = 4,
        min_interval_seconds: float = 0.0,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        if retries < 0:
            raise ValueError("retries must not be negative")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative")
        self.delegate = delegate
        self.retries = retries
        self.retry_delay_seconds = retry_delay_seconds
        self.max_concurrency = max_concurrency
        self.min_interval_seconds = min_interval_seconds
        self._gate = _CallGate(
            max_concurrency=max_concurrency,
            min_interval_seconds=min_interval_seconds,
        )
        self.last_attempt_id: str | None = None

    def is_available(self) -> bool:
        """保留原运行时的可用性语义，不因包装器自行推断远端状态。"""
        return self.delegate.is_available()

    async def generate_json(
        self,
        *,
        prompt: str,
        schema: dict,
        thinking_mode: str = "disabled",
        reasoning_effort: str | None = None,
        timeout_seconds: float = 120.0,
        max_output_tokens: int | None = None,
        prompt_version: str = "native-capability.v3",
        commit_id: str | None = None,
    ) -> StructuredGenerationResult:
        """在本地保护边界内调用模型，并只暴露稳定、无正文的错误。"""
        if timeout_seconds <= 0:
            raise StructuredGenerationError("MODEL_TIMEOUT", "model timeout must be positive")
        for attempt in range(1, self.retries + 2):
            try:
                delegate_kwargs = {
                    "prompt": prompt,
                    "schema": schema,
                    "thinking_mode": thinking_mode,
                    "timeout_seconds": timeout_seconds,
                    "max_output_tokens": max_output_tokens,
                    "prompt_version": prompt_version,
                    "commit_id": commit_id,
                }
                if reasoning_effort is not None:
                    delegate_kwargs["reasoning_effort"] = reasoning_effort
                return await self._gate.call(
                    lambda: asyncio.wait_for(
                        self.delegate.generate_json(**delegate_kwargs),
                        timeout=timeout_seconds,
                    )
                )
            except asyncio.TimeoutError as exc:
                error = StructuredGenerationError(
                    "MODEL_TIMEOUT", "model operation timed out", attempts=attempt, retryable=True
                )
                if attempt > self.retries:
                    raise error from exc
            except StructuredGenerationError as exc:
                error = StructuredGenerationError(
                    exc.code,
                    f"model operation failed ({exc.code})",
                    attempts=attempt,
                    retryable=exc.code in _RETRYABLE_CODES,
                    audit=exc.audit,
                )
                if exc.code not in _RETRYABLE_CODES or attempt > self.retries:
                    raise error from exc
            except Exception as exc:
                raise StructuredGenerationError(
                    "MODEL_EXECUTION_FAILED",
                    "model operation failed",
                    attempts=attempt,
                ) from exc
            if self.retry_delay_seconds:
                await asyncio.sleep(self.retry_delay_seconds)
        raise AssertionError("model retry loop must return or raise")

    async def stream_generate_json(self, **kwargs) -> AsyncIterator[RuntimeEvent]:
        """Stream through the delegate while retaining retry-from-scratch semantics."""
        streamer = getattr(self.delegate, "stream_generate_json", None)
        if not callable(streamer):
            raise StructuredGenerationError("MODEL_STREAM_UNSUPPORTED", "model runtime does not support streaming")
        for attempt in range(1, self.retries + 2):
            delegate_kwargs = dict(kwargs)
            base_attempt_id = kwargs.get("attempt_id")
            attempt_id = str(base_attempt_id or f"attempt:{uuid4().hex}")
            if attempt > 1:
                attempt_id = f"{attempt_id}:retry:{uuid4().hex[:12]}"
            delegate_kwargs["attempt_id"] = attempt_id
            self.last_attempt_id = attempt_id
            try:
                async with self._gate.stream_slot():
                    async for event in streamer(**delegate_kwargs):
                        yield event
                return
            except asyncio.CancelledError:
                raise
            except StructuredGenerationError as exc:
                retryable_codes = _RETRYABLE_CODES | {
                    "MODEL_TTFT_TIMEOUT",
                    "MODEL_IDLE_TIMEOUT",
                    "MODEL_TOTAL_TIMEOUT",
                }
                if exc.code not in retryable_codes or attempt > self.retries:
                    raise
                if self.retry_delay_seconds:
                    await asyncio.sleep(self.retry_delay_seconds * attempt)

    def describe_model(self):
        """透明转发模型能力，不在保护包装器中创造容量事实。"""
        describer = getattr(self.delegate, "describe_model", None)
        if not callable(describer):
            raise LookupError("MODEL_CAPABILITY_UNKNOWN")
        return describer()


__all__ = ["GuardedModelRuntime"]
