"""Tool catalog exposed only through the regular Chat API."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.tools.catalog import ReadOnlyToolCatalog
from app.tools.contracts import ToolPayload
from app.tools.terminal import WorkspaceTerminalExecutor


class ChatToolCatalog(ReadOnlyToolCatalog):
    """Read-only tools plus an explicitly enabled workspace terminal."""

    TOOL_NAMES = (*ReadOnlyToolCatalog.TOOL_NAMES, "terminal")

    def __init__(self) -> None:
        super().__init__()
        self._terminal_executor = WorkspaceTerminalExecutor()

    def availability(self, provider: str | None = None) -> dict[str, dict[str, Any]]:
        result = super().availability(provider)
        result["terminal"] = {
            "available": bool(settings.TOOL_RUNTIME_ENABLED)
            and bool(settings.CHAT_TERMINAL_ENABLED)
            and self._terminal_executor.root.is_dir(),
            "provider": "chat-workspace",
            "readOnly": False,
            "scope": "configured workspace",
        }
        return result

    async def _terminal(self, arguments: dict[str, Any], **_: Any) -> ToolPayload:
        result = await self._terminal_executor.execute(
            str(arguments.get("command") or ""),
            cwd=str(arguments.get("cwd") or "."),
            timeout_seconds=arguments.get("timeout_seconds"),
        )
        return ToolPayload(
            summary=f"terminal command completed (exit code {result['exitCode']})",
            data={"terminal": result},
        )


__all__ = ["ChatToolCatalog"]
