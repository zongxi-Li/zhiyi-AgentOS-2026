"""模型外部副作用的超时、重试、限流与安全错误包装器。

包装器只处理调用调度，不保存 prompt、schema 或模型响应。稳定 ``commit_id`` 会原样
传给应用层模型运行时，使支持幂等的供应商能够把同一节点尝试识别为同一调用边界。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Hashable
from contextlib import asynccontextmanager
from threading import RLock
from time import monotonic
from typing import TypeVar
from uuid import uuid4

from adapters.model_adapter import (
    StructuredGenerationError,
    StructuredGenerationResult,
    StructuredGenerationRuntime,
)
from adapters.model_diagnostics import safe_stream_diagnostics, safe_transport_diagnostics
from contracts.runtime_events import RuntimeEvent


_Result = TypeVar("_Result")
_RETRYABLE_CODES = frozenset(
    {
        "MODEL_TIMEOUT",
        "MODEL_RATE_LIMITED",
        "MODEL_TEMPORARY_UNAVAILABLE",
        # A provider stream can terminate after emitting a partial response
        # without producing its terminal finish chunk. Retry the model call,
        # not the node or planner graph.
        "MODEL_STREAM_INCOMPLETE",
    }
)

_STREAM_RETRYABLE_CODES = _RETRYABLE_CODES | {
    "MODEL_TTFT_TIMEOUT", "MODEL_IDLE_TIMEOUT", "MODEL_TOTAL_TIMEOUT",
}


class _CallGate:
    """同一路由的包装器共享调用容量；调用状态仍留在各自包装器中。"""

    def __init__(self, *, max_concurrency: int, min_interval_seconds: float) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must not be negative")
        self.max_concurrency = max_concurrency
        self._min_interval_seconds = min_interval_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = RLock()
        self._semaphore: asyncio.Semaphore | None = None
        self._spacing_lock: asyncio.Lock | None = None
        self._last_started: float | None = None

    def _primitives(self) -> tuple[asyncio.Semaphore, asyncio.Lock]:
        loop = asyncio.get_running_loop()
        with self._loop_lock:
            if self._loop is not loop:
                if self._loop is not None and not self._loop.is_closed():
                    # asyncio primitives cannot coordinate two live loops. Fail
                    # closed rather than silently granting a second capacity.
                    raise StructuredGenerationError(
                        "MODEL_GATE_EVENT_LOOP_MISMATCH",
                        "model call gate is owned by another live event loop",
                    )
                self._loop = loop
                self._semaphore = asyncio.Semaphore(self.max_concurrency)
                self._spacing_lock = asyncio.Lock()
            assert self._semaphore is not None and self._spacing_lock is not None
            return self._semaphore, self._spacing_lock

    async def call(self, operation: Callable[[], Awaitable[_Result]]) -> _Result:
        """在取得并发许可且满足最小间隔后执行一次外部调用。"""
        async with self.stream_slot():
            return await operation()

    @asynccontextmanager
    async def stream_slot(self):
        """Hold one concurrency slot for the complete provider stream."""
        semaphore, spacing_lock = self._primitives()
        async with semaphore:
            async with spacing_lock:
                now = monotonic()
                if self._last_started is not None:
                    remaining = self._min_interval_seconds - (now - self._last_started)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                self._last_started = monotonic()
            yield


class ModelCallGateRegistry:
    """应用执行服务内的路由闸门缓存，不注册资源或裁决调度租约。"""

    def __init__(self) -> None:
        self._gates: dict[Hashable, _CallGate] = {}
        self._lock = RLock()

    def gate_for(
        self, route: Hashable, *, max_concurrency: int, min_interval_seconds: float,
    ) -> _CallGate:
        with self._lock:
            gate = self._gates.get(route)
            if gate is None:
                gate = _CallGate(
                    max_concurrency=max_concurrency,
                    min_interval_seconds=min_interval_seconds,
                )
                self._gates[route] = gate
            elif (gate.max_concurrency, gate._min_interval_seconds) != (
                max_concurrency, min_interval_seconds,
            ):
                raise ValueError("model call gate policy cannot change for an existing route")
            return gate


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
        _gate: _CallGate | None = None,
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
        if _gate is not None and (
            _gate.max_concurrency, _gate._min_interval_seconds
        ) != (max_concurrency, min_interval_seconds):
            raise ValueError("model call gate policy does not match wrapper configuration")
        self._gate = _gate or _CallGate(
            max_concurrency=max_concurrency,
            min_interval_seconds=min_interval_seconds,
        )
        self.last_attempt_id: str | None = None

    def is_available(self) -> bool:
        """保留原运行时的可用性语义，不因包装器自行推断远端状态。"""
        return self.delegate.is_available()

    @property
    def supports_continuation(self) -> bool:
        return bool(getattr(self.delegate, "supports_continuation", False))

    @property
    def supports_tool_calling(self) -> bool:
        return bool(getattr(self.delegate, "supports_tool_calling", False))

    @property
    def manages_tool_turn_timeout(self) -> bool:
        return getattr(self.delegate, "manages_tool_turn_timeout", False) is True

    async def generate_tool_turn(self, *, timeout_seconds=120.0, **kwargs):
        """Retry unfinished model I/O in place; the caller owns tools and cancellation."""
        if timeout_seconds <= 0:
            raise StructuredGenerationError("MODEL_TIMEOUT", "model timeout must be positive")
        async def invoke():
            operation = self.delegate.generate_tool_turn(timeout_seconds=timeout_seconds, **kwargs)
            if self.manages_tool_turn_timeout:
                # The registered runtime owns request/stream deadlines and
                # diagnostics. A competing timer here would erase their cause.
                return await operation
            return await asyncio.wait_for(operation, timeout_seconds)
        attempt = 0
        delay = min(max(self.retry_delay_seconds, .25), 30.0)
        while True:
            attempt += 1
            try:
                return await self._gate.call(invoke)
            except asyncio.TimeoutError:
                error = StructuredGenerationError(
                    "MODEL_TIMEOUT", "model tool turn timed out", attempts=attempt, retryable=True)
            except StructuredGenerationError as exc:
                exc.attempts = attempt
                if exc.code not in _STREAM_RETRYABLE_CODES:
                    raise
                error = exc
                error.retryable = True
            # A failed model turn has not dispatched any tools. Keep the exact
            # conversation and commit identity; release capacity before the
            # cancellable backoff, with no retry-count termination rule.
            progress = kwargs.get("progress_callback")
            if progress is not None:
                await progress("model.activity", {
                    "phase": "retrying", "errorCode": error.code,
                    "retryCount": attempt, "retryDelayMs": round(delay * 1000),
                    **safe_stream_diagnostics(error.audit.get("streamDiagnostics")),
                    "transportDiagnostics": safe_transport_diagnostics(error.audit.get("transportDiagnostics")),
                })
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def generate_json(
        self,
        *,
        prompt: str,
        schema: dict,
        system_prompt: str | None = None,
        thinking_mode: str = "disabled",
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float = 120.0,
        max_output_tokens: int | None = None,
        prompt_version: str = "native-capability.v3",
        commit_id: str | None = None,
        prompt_metadata: dict | None = None,
        continuation: list[dict[str, str]] | None = None,
        prefix_schema: dict | None = None,
    ) -> StructuredGenerationResult:
        """在本地保护边界内调用模型，并只暴露稳定、无正文的错误。"""
        if timeout_seconds <= 0:
            raise StructuredGenerationError("MODEL_TIMEOUT", "model timeout must be positive")
        for attempt in range(1, self.retries + 2):
            try:
                delegate_kwargs = {
                    "prompt": prompt,
                    "schema": schema,
                    "system_prompt": system_prompt,
                    "thinking_mode": thinking_mode,
                    "timeout_seconds": timeout_seconds,
                    "max_output_tokens": max_output_tokens,
                    "prompt_version": prompt_version,
                    "commit_id": commit_id,
                }
                if prompt_metadata is not None:
                    delegate_kwargs["prompt_metadata"] = prompt_metadata
                if reasoning_effort is not None:
                    delegate_kwargs["reasoning_effort"] = reasoning_effort
                if temperature is not None:
                    delegate_kwargs["temperature"] = temperature
                if continuation is not None:
                    delegate_kwargs["continuation"] = continuation
                if prefix_schema is not None:
                    delegate_kwargs["prefix_schema"] = prefix_schema
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
                    iterator = streamer(**delegate_kwargs).__aiter__()
                    try:
                        async for event in iterator:
                            yield event
                    finally:
                        closer = getattr(iterator, "aclose", None)
                        if callable(closer):
                            await closer()
                return
            except asyncio.CancelledError:
                raise
            except StructuredGenerationError as exc:
                diagnostics = safe_stream_diagnostics(exc.audit.get("streamDiagnostics"))
                if diagnostics:
                    yield RuntimeEvent(
                        eventType="model.stream.failure",
                        runId=str(kwargs.get("run_id") or "unknown"),
                        nodeId=kwargs.get("node_id"),
                        attemptId=attempt_id,
                        sequence=0,
                        payload={
                            **diagnostics,
                            "errorCode": exc.code,
                            "retryCount": attempt - 1,
                        },
                    )
                if exc.code not in _STREAM_RETRYABLE_CODES or attempt > self.retries:
                    raise
                if self.retry_delay_seconds:
                    await asyncio.sleep(self.retry_delay_seconds * attempt)

    def describe_model(self):
        """透明转发模型能力，不在保护包装器中创造容量事实。"""
        describer = getattr(self.delegate, "describe_model", None)
        if not callable(describer):
            raise LookupError("MODEL_CAPABILITY_UNKNOWN")
        return describer()


__all__ = ["GuardedModelRuntime", "ModelCallGateRegistry"]
