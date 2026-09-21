"""Tool catalog exposed only through the regular Chat API."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.tools.catalog import ReadOnlyToolCatalog
from app.tools.contracts import ToolPayload, ToolUnavailableError
from app.tools.local_runtime import LocalRuntimeToolError, LocalRuntimeToolExecutor
from app.tools.terminal import WorkspaceTerminalExecutor


class ChatToolCatalog(ReadOnlyToolCatalog):
    """Chat tools backed by AgentOS, with legacy terminal compatibility only."""

    FILE_TOOL_NAMES = ("read_file", "list_files", "write_file", "patch_file")
    TOOL_NAMES = (*ReadOnlyToolCatalog.TOOL_NAMES, *FILE_TOOL_NAMES, "terminal")
    supports_call_id = True

    def __init__(
        self,
        *,
        local_runtime_executor: LocalRuntimeToolExecutor | None = None,
        legacy_terminal_enabled: bool | None = None,
    ) -> None:
        super().__init__()
        self._local_runtime_executor = local_runtime_executor
        self._legacy_terminal_enabled = (
            bool(settings.CHAT_TERMINAL_ENABLED)
            if legacy_terminal_enabled is None
            else bool(legacy_terminal_enabled)
        )
        self._terminal_executor = (
            WorkspaceTerminalExecutor() if self._legacy_terminal_enabled else None
        )
        names = [*ReadOnlyToolCatalog.TOOL_NAMES, *self.FILE_TOOL_NAMES]
        if self._legacy_terminal_enabled:
            names.append("terminal")
        # Keep the class-level tuple for compatibility, but let production
        # composition explicitly remove the legacy tool from this catalog.
        self.TOOL_NAMES = tuple(names)

    def availability(self, provider: str | None = None) -> dict[str, dict[str, Any]]:
        result = super().availability(provider)
        for name, capability_id in {
            "read_file": "fs.read",
            "list_files": "fs.list",
            "write_file": "fs.write",
            "patch_file": "fs.patch",
        }.items():
            result[name] = {
                "available": bool(settings.TOOL_RUNTIME_ENABLED) and self._local_runtime_executor is not None,
                "provider": "agentos-local-runtime",
                "readOnly": False,
                "scope": "trusted workspace",
                "capabilityId": capability_id,
            }
        if self._legacy_terminal_enabled and self._terminal_executor is not None:
            result["terminal"] = {
                "available": bool(settings.TOOL_RUNTIME_ENABLED)
                and self._terminal_executor.root.is_dir(),
                "provider": "chat-workspace-legacy",
                "readOnly": False,
                "scope": "configured workspace",
                "legacy": True,
            }
        return result

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        role_id: str | None = None,
        provider: str | None = None,
        call_id: str | None = None,
    ) -> ToolPayload:
        if name in self.FILE_TOOL_NAMES:
            if not settings.TOOL_RUNTIME_ENABLED:
                raise ToolUnavailableError(f"local runtime tool is unavailable: {name}")
            if self._local_runtime_executor is None:
                raise LocalRuntimeToolError(
                    "LOCAL_RUNTIME_UNAVAILABLE", "Local Runtime is unavailable."
                )
            del role_id, provider
            return await self._local_runtime_executor.execute(
                name,
                arguments,
                call_id=str(call_id or ""),
            )
        if name == "terminal" and not self._legacy_terminal_enabled:
            raise ToolUnavailableError("legacy container terminal is disabled")
        return await super().execute(
            name,
            arguments,
            role_id=role_id,
            provider=provider,
        )

    async def _read_file(self, arguments: dict[str, Any], *, call_id: str | None = None, **_: Any) -> ToolPayload:
        return await self.execute("read_file", arguments, call_id=call_id)

    async def _list_files(self, arguments: dict[str, Any], *, call_id: str | None = None, **_: Any) -> ToolPayload:
        return await self.execute("list_files", arguments, call_id=call_id)

    async def _write_file(self, arguments: dict[str, Any], *, call_id: str | None = None, **_: Any) -> ToolPayload:
        return await self.execute("write_file", arguments, call_id=call_id)

    async def _patch_file(self, arguments: dict[str, Any], *, call_id: str | None = None, **_: Any) -> ToolPayload:
        return await self.execute("patch_file", arguments, call_id=call_id)

    async def _terminal(self, arguments: dict[str, Any], **_: Any) -> ToolPayload:
        if self._terminal_executor is None:
            raise ToolUnavailableError("legacy container terminal is disabled")
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
