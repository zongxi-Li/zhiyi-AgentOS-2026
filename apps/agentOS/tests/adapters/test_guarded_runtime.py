"""外部模型与工具保护运行时的行为测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.guarded_model import GuardedModelRuntime
from adapters.guarded_tool import GuardedToolRuntime, ToolInvocationError
from adapters.model_adapter import StructuredGenerationError, StructuredGenerationResult
from contracts.runtime_events import RuntimeEvent


class _FlakyModel:
    """首次报告临时故障，随后返回可验证的结构化结果。"""

    def __init__(self) -> None:
        self.commit_ids: list[str | None] = []
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def generate_json(self, *, commit_id: str | None = None, **_kwargs) -> StructuredGenerationResult:
        self.calls += 1
        self.commit_ids.append(commit_id)
        if self.calls == 1:
            raise StructuredGenerationError("MODEL_TEMPORARY_UNAVAILABLE", "provider failed")
        return StructuredGenerationResult(data={"ok": True}, provider="test", model="test")


class _SlowModel:
    """用于触发本地超时映射，不返回任何敏感请求内容。"""

    def is_available(self) -> bool:
        return True

    async def generate_json(self, **_kwargs) -> StructuredGenerationResult:
        await asyncio.sleep(0.05)
        raise AssertionError("unreachable")


class _FlakyTool:
    """首次使用稳定临时错误码失败，后续返回普通工具结果。"""

    def __init__(self) -> None:
        self.commit_ids: list[str | None] = []
        self.calls = 0

    def scoped(self, _allowed_tools):
        return self

    async def run(self, _text: str, **_kwargs):
        return {"ok": True}

    async def execute(self, _name: str, _arguments: dict[str, object], **kwargs):
        self.calls += 1
        self.commit_ids.append(kwargs.get("commit_id"))
        if self.calls == 1:
            raise ToolInvocationError("TOOL_TEMPORARY_UNAVAILABLE", "provider failed")
        return {"ok": True}


class _FailingTool:
    """模拟不含稳定错误码的供应商异常，验证包装器不会泄露调用正文。"""

    def scoped(self, _allowed_tools):
        return self

    async def run(self, _text: str, **_kwargs):
        raise RuntimeError("private prompt")

    async def execute(self, _name: str, arguments: dict[str, object], **_kwargs):
        raise RuntimeError(str(arguments))


class _StreamingTool:
    def scoped(self, _allowed_tools):
        return self

    async def run(self, _text: str, **_kwargs):
        return {"ok": True}

    async def execute(self, _name: str, _arguments: dict[str, object], **_kwargs):
        return {"ok": True}

    async def astream_execute(self, _name: str, _arguments: dict[str, object], **_kwargs):
        yield {"delta": "first"}
        await asyncio.sleep(0.05)
        yield {"delta": "late"}


class _FlakyStreamingModel:
    def __init__(self) -> None:
        self.attempt_ids: list[str] = []

    def is_available(self) -> bool:
        return True

    async def stream_generate_json(self, **kwargs):
        attempt_id = str(kwargs["attempt_id"])
        self.attempt_ids.append(attempt_id)
        yield RuntimeEvent(
            eventType="model.output.delta",
            runId="run-1",
            nodeId="node-1",
            attemptId=attempt_id,
            sequence=1,
            payload={"delta": "stale" if len(self.attempt_ids) == 1 else "fresh"},
        )
        if len(self.attempt_ids) == 1:
            raise StructuredGenerationError("MODEL_IDLE_TIMEOUT", "provider stalled")
        yield RuntimeEvent(
            eventType="model.completed",
            runId="run-1",
            nodeId="node-1",
            attemptId=attempt_id,
            sequence=2,
            payload={},
        )


class _RateLimitedStreamingModel:
    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def stream_generate_json(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise StructuredGenerationError("MODEL_RATE_LIMITED", "provider throttled", retryable=True)
        yield RuntimeEvent(
            eventType="model.completed",
            runId="run-1",
            nodeId="node-1",
            attemptId=kwargs["attempt_id"],
            sequence=1,
            payload={},
        )


class _ConcurrentStreamingModel:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    def is_available(self) -> bool:
        return True

    async def stream_generate_json(self, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        yield RuntimeEvent(
            eventType="model.completed",
            runId="run-1",
            nodeId=kwargs["node_id"],
            attemptId=kwargs["attempt_id"],
            sequence=1,
            payload={},
        )
        self.active -= 1


def test_guarded_model_stream_retry_uses_a_new_attempt_id() -> None:
    delegate = _FlakyStreamingModel()
    runtime = GuardedModelRuntime(delegate=delegate, retries=1)

    async def collect():
        return [
            event
            async for event in runtime.stream_generate_json(
                run_id="run-1",
                node_id="node-1",
                attempt_id="attempt-1",
            )
        ]

    events = asyncio.run(collect())

    assert delegate.attempt_ids[0] == "attempt-1"
    assert len(delegate.attempt_ids) == 2
    assert delegate.attempt_ids[1].startswith("attempt-1:retry:")
    assert events[0].attempt_id == delegate.attempt_ids[0]
    assert events[1].attempt_id == delegate.attempt_ids[1]


def test_guarded_model_stream_retries_provider_rate_limit() -> None:
    delegate = _RateLimitedStreamingModel()
    runtime = GuardedModelRuntime(delegate=delegate, retries=1)

    async def collect():
        return [event async for event in runtime.stream_generate_json(
            run_id="run-1", node_id="node-1", attempt_id="attempt-1"
        )]

    events = asyncio.run(collect())

    assert delegate.calls == 2
    assert events[-1].event_type == "model.completed"
    assert events[-1].attempt_id.startswith("attempt-1:retry:")


def test_guarded_model_stream_holds_concurrency_slot_until_stream_finishes() -> None:
    delegate = _ConcurrentStreamingModel()
    runtime = GuardedModelRuntime(delegate=delegate, max_concurrency=1)

    async def consume(node_id: str):
        return [event async for event in runtime.stream_generate_json(
            run_id="run-1", node_id=node_id, attempt_id=f"attempt-{node_id}"
        )]

    async def collect():
        await asyncio.gather(consume("node-1"), consume("node-2"))

    asyncio.run(collect())

    assert delegate.max_active == 1


def test_guarded_model_retries_temporary_error_with_same_commit_id() -> None:
    """可重试模型错误必须复用同一个提交标识，不能生成第二个外部副作用边界。"""
    delegate = _FlakyModel()
    runtime = GuardedModelRuntime(delegate=delegate, retries=1)

    result = asyncio.run(
        runtime.generate_json(
            prompt="private prompt",
            schema={"type": "object"},
            commit_id="commit:run:step:0",
        )
    )

    assert result.data == {"ok": True}
    assert delegate.commit_ids == ["commit:run:step:0", "commit:run:step:0"]


def test_guarded_model_maps_timeout_without_prompt_body() -> None:
    """模型超时只能产出稳定错误码，异常文字不能带入提示词正文。"""
    runtime = GuardedModelRuntime(delegate=_SlowModel(), retries=0)

    with pytest.raises(StructuredGenerationError) as captured:
        asyncio.run(
            runtime.generate_json(
                prompt="private prompt",
                schema={},
                timeout_seconds=0.001,
                commit_id="commit:run:step:0",
            )
        )

    assert captured.value.code == "MODEL_TIMEOUT"
    assert "private prompt" not in str(captured.value)


def test_guarded_tool_retries_temporary_error_with_same_commit_id() -> None:
    """可重试工具错误也必须透传同一个提交标识并只重试一次。"""
    delegate = _FlakyTool()
    runtime = GuardedToolRuntime(delegate=delegate, retries=1)

    result = asyncio.run(
        runtime.execute(
            "search",
            {"query": "private input"},
            commit_id="commit:run:step:0",
        )
    )

    assert result == {"ok": True}
    assert delegate.commit_ids == ["commit:run:step:0", "commit:run:step:0"]


def test_guarded_tool_maps_unknown_failure_without_argument_body() -> None:
    """工具失败不能把参数正文写入结构化错误，避免经 Trace 泄露。"""
    runtime = GuardedToolRuntime(delegate=_FailingTool(), retries=0)

    with pytest.raises(ToolInvocationError) as captured:
        asyncio.run(
            runtime.execute(
                "search",
                {"query": "private input"},
                commit_id="commit:run:step:0",
            )
        )

    assert captured.value.code == "TOOL_EXECUTION_FAILED"
    assert "private input" not in str(captured.value)


def test_guarded_tool_stream_enforces_total_timeout() -> None:
    """流式工具在完整流生命周期内受总超时保护。"""
    runtime = GuardedToolRuntime(delegate=_StreamingTool())

    async def collect():
        return [
            event
            async for event in runtime.astream_execute(
                "search",
                {"query": "private"},
                timeout_seconds=0.01,
            )
        ]

    with pytest.raises(ToolInvocationError) as captured:
        asyncio.run(collect())
    assert captured.value.code == "TOOL_TIMEOUT"
    assert "private" not in str(captured.value)

