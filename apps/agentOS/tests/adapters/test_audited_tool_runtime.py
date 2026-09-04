"""受审计工具运行时的授权前置检查测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.audited_tool_runtime import AuditedToolRuntime, ToolAuthorizationError


class _RecordingToolRuntime:
    """记录真实调用次数，用于证明拒绝路径没有产生外部副作用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def scoped(self, allowed_tools):
        return self

    async def run(self, text: str, **kwargs):
        return {"text": text}

    async def execute(self, name: str, arguments: dict[str, object], **kwargs):
        self.calls.append((name, arguments))
        return {"ok": True}

    async def astream_execute(self, name: str, arguments: dict[str, object], **kwargs):
        self.calls.append((name, arguments))
        yield {"type": "delta"}


def test_audited_tool_runtime_blocks_unapproved_tool_before_delegate() -> None:
    """工具未获冻结 scope 授权时，必须在 delegate 调用前失败。"""
    delegate = _RecordingToolRuntime()
    runtime = AuditedToolRuntime(delegate=delegate, allowed_tools={"search"})

    with pytest.raises(ToolAuthorizationError, match="shell"):
        asyncio.run(runtime.execute("shell", {"command": "whoami"}))

    assert delegate.calls == []


def test_audited_tool_runtime_records_safe_metadata_for_allowed_tool() -> None:
    """允许工具被调用时只记录工具名和调用标识，不复制可能敏感的参数正文。"""
    delegate = _RecordingToolRuntime()
    runtime = AuditedToolRuntime(delegate=delegate, allowed_tools={"search"})

    result = asyncio.run(runtime.execute("search", {"query": "private input"}))

    assert result == {"ok": True}
    assert delegate.calls == [("search", {"query": "private input"})]
    assert runtime.events == [{"type": "tool_called", "tool": "search"}]


def test_scoped_tool_runtime_has_independent_event_buffer() -> None:
    """并行节点创建的受限视图不能共享工具事件缓冲区。"""
    runtime = AuditedToolRuntime(delegate=_RecordingToolRuntime(), allowed_tools=["search"])
    left = runtime.scoped(["search"])
    right = runtime.scoped(["search"])

    asyncio.run(left.execute("search", {"query": "left"}))

    assert left.events == [{"type": "tool_called", "tool": "search"}]
    assert right.events == []
    assert runtime.events == []


def test_audited_tool_stream_checks_scope_before_delegate() -> None:
    """流式入口必须复用相同授权边界，且审计事件不包含参数。"""
    delegate = _RecordingToolRuntime()
    runtime = AuditedToolRuntime(delegate=delegate, allowed_tools={"search"})

    async def collect(name: str):
        return [event async for event in runtime.astream_execute(name, {"query": "private"})]

    with pytest.raises(ToolAuthorizationError):
        asyncio.run(collect("shell"))
    assert delegate.calls == []
    assert asyncio.run(collect("search")) == [{"type": "delta"}]
    assert runtime.events == [{"type": "tool_streamed", "tool": "search"}]
