"""外部模型与工具保护运行时的行为测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.guarded_model import GuardedModelRuntime
from adapters.guarded_tool import GuardedToolRuntime, ToolInvocationError
from adapters.model_adapter import StructuredGenerationError, StructuredGenerationResult


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

