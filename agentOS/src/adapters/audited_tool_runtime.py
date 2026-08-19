"""工具调用的冻结授权与安全审计包装器。

该包装器在真实工具 delegate 之前检查当前运行的允许工具集合，避免未授权调用产生
任何外部副作用。审计事件刻意不复制 arguments，以免查询词、命令或其它敏感正文进入
Trace；详细参数仍只停留在实际工具的受控边界中。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any

from adapters.tool_adapter import ToolRuntime


class ToolAuthorizationError(PermissionError):
    """工具不在冻结运行 scope 的允许集合时抛出。"""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"tool is not authorized for this run: {tool_name}")
        self.code = "TOOL_NOT_AUTHORIZED"
        self.tool_name = tool_name


class AuditedToolRuntime:
    """将 ToolRuntime 包装为授权前置、只记安全元数据的调用面。"""

    def __init__(self, *, delegate: ToolRuntime, allowed_tools: Iterable[str]) -> None:
        self.delegate = delegate
        self.allowed_tools = frozenset(allowed_tools)
        self.events: list[dict[str, str]] = []

    def scoped(self, allowed_tools: Iterable[str]) -> "AuditedToolRuntime":
        """返回在当前权限集合基础上进一步收缩的新视图，绝不扩大授权。"""
        return AuditedToolRuntime(
            delegate=self.delegate,
            allowed_tools=self.allowed_tools.intersection(allowed_tools),
        )

    async def run(self, text: str, **kwargs: Any) -> Any:
        """保留工具运行时的文本入口；具体编排授权仍由 delegate 自身负责。"""
        return await self.delegate.run(text, **kwargs)

    async def execute(self, name: str, arguments: dict[str, Any], **kwargs: Any) -> Any:
        """先验证授权并记录安全元数据，随后才调用可能产生副作用的 delegate。"""
        if name not in self.allowed_tools:
            raise ToolAuthorizationError(name)
        self.events.append({"type": "tool_called", "tool": name})
        return await self.delegate.execute(name, arguments, **kwargs)

    async def astream_execute(
        self, name: str, arguments: dict[str, Any], **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """授权后转发工具流；取消会自然关闭 delegate 迭代器并终止底层请求。"""
        if name not in self.allowed_tools:
            raise ToolAuthorizationError(name)
        streamer = getattr(self.delegate, "astream_execute", None)
        if not callable(streamer):
            raise RuntimeError("TOOL_STREAM_UNSUPPORTED: tool runtime does not support streaming")
        self.events.append({"type": "tool_streamed", "tool": name})
        async for event in streamer(name, arguments, **kwargs):
            yield event


__all__ = ["AuditedToolRuntime", "ToolAuthorizationError"]
