"""工具外部副作用的超时、重试、限流与安全错误包装器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from adapters.tool_adapter import ToolRuntime


_Result = TypeVar("_Result")
_RETRYABLE_CODES = frozenset(
    {"TOOL_TIMEOUT", "TOOL_RATE_LIMITED", "TOOL_TEMPORARY_UNAVAILABLE"}
)


class ToolInvocationError(RuntimeError):
    """工具保护层的无正文结构化失败。

    ``code``、``attempts`` 和 ``retryable`` 可以安全进入后续错误映射；工具名称、参数、
    命令、查询词和供应商异常消息都不进入异常文字，避免被 Trace 或调用方日志复制。
    """

    def __init__(self, code: str, message: str, *, attempts: int = 1, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.attempts = attempts
        self.retryable = retryable


class _CallGate:
    """在一个工具包装器及其 scoped 视图中共享的本地调用闸门。"""

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
        """串联开始间隔并限制同时运行的真实工具调用数。"""
        async with self.slot():
            return await operation()

    @asynccontextmanager
    async def slot(self):
        """在完整流生命周期内持有并发槽，并统一执行开始间隔。"""
        async with self._semaphore:
            async with self._spacing_lock:
                now = asyncio.get_running_loop().time()
                if self._last_started is not None:
                    remaining = self._min_interval_seconds - (now - self._last_started)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                self._last_started = asyncio.get_running_loop().time()
            yield


class GuardedToolRuntime:
    """给 ToolRuntime 增加本地调用保护，不替代既有授权与审计包装器。"""

    def __init__(
        self,
        *,
        delegate: ToolRuntime,
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
        self._max_concurrency = max_concurrency
        self._min_interval_seconds = min_interval_seconds
        self._gate = _gate or _CallGate(
            max_concurrency=max_concurrency,
            min_interval_seconds=min_interval_seconds,
        )

    def scoped(self, allowed_tools: Iterable[str]) -> "GuardedToolRuntime":
        """在保留同一限流闸门的同时，把真实工具权限继续交给 delegate 收缩。"""
        return GuardedToolRuntime(
            delegate=self.delegate.scoped(allowed_tools),
            retries=self.retries,
            max_concurrency=self._max_concurrency,
            min_interval_seconds=self._min_interval_seconds,
            retry_delay_seconds=self.retry_delay_seconds,
            _gate=self._gate,
        )

    async def run(
        self,
        text: str,
        *,
        timeout_seconds: float = 120.0,
        commit_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """保护文本入口；正文只在本次委托调用中存在，不写入包装器状态。"""
        return await self._invoke(
            lambda: self.delegate.run(text, commit_id=commit_id, **kwargs),
            timeout_seconds=timeout_seconds,
        )

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float = 120.0,
        commit_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """保护单工具调用并透传稳定提交标识，不记录工具参数。"""
        return await self._invoke(
            lambda: self.delegate.execute(name, arguments, commit_id=commit_id, **kwargs),
            timeout_seconds=timeout_seconds,
        )

    async def astream_execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float = 120.0,
        commit_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """在同一并发和总超时边界内转发流，取消信号不做错误改写。"""
        if timeout_seconds <= 0:
            raise ToolInvocationError(
                "TOOL_TIMEOUT",
                "tool timeout must be positive",
                retryable=True,
            )
        streamer = getattr(self.delegate, "astream_execute", None)
        if not callable(streamer):
            raise ToolInvocationError(
                "TOOL_STREAM_UNSUPPORTED",
                "tool runtime does not support streaming",
            )
        try:
            async with self._gate.slot():
                async with asyncio.timeout(timeout_seconds):
                    async for event in streamer(
                        name,
                        arguments,
                        commit_id=commit_id,
                        **kwargs,
                    ):
                        yield event
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise ToolInvocationError(
                "TOOL_TIMEOUT",
                "tool stream timed out",
                retryable=True,
            ) from exc
        except ToolInvocationError:
            raise
        except Exception as exc:
            raise ToolInvocationError(
                "TOOL_EXECUTION_FAILED",
                "tool stream failed",
            ) from exc

    async def _invoke(
        self,
        operation: Callable[[], Awaitable[_Result]],
        *,
        timeout_seconds: float,
    ) -> _Result:
        """重试明确可恢复的故障，其他异常立即归一为安全错误。"""
        if timeout_seconds <= 0:
            raise ToolInvocationError("TOOL_TIMEOUT", "tool timeout must be positive", retryable=True)
        for attempt in range(1, self.retries + 2):
            try:
                return await self._gate.call(
                    lambda: asyncio.wait_for(operation(), timeout=timeout_seconds)
                )
            except asyncio.TimeoutError as exc:
                error = ToolInvocationError(
                    "TOOL_TIMEOUT", "tool operation timed out", attempts=attempt, retryable=True
                )
                if attempt > self.retries:
                    raise error from exc
            except ToolInvocationError as exc:
                error = ToolInvocationError(
                    exc.code,
                    f"tool operation failed ({exc.code})",
                    attempts=attempt,
                    retryable=exc.code in _RETRYABLE_CODES,
                )
                if exc.code not in _RETRYABLE_CODES or attempt > self.retries:
                    raise error from exc
            except Exception as exc:
                raise ToolInvocationError(
                    "TOOL_EXECUTION_FAILED", "tool operation failed", attempts=attempt
                ) from exc
            if self.retry_delay_seconds:
                await asyncio.sleep(self.retry_delay_seconds)
        raise AssertionError("tool retry loop must return or raise")


__all__ = ["GuardedToolRuntime", "ToolInvocationError"]
