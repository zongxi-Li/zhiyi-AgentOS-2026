"""Tool catalog exposed only through the regular Chat API."""

from __future__ import annotations

from typing import Any, Awaitable, Callable
import asyncio

from app.config import settings
from app.tools.catalog import ReadOnlyToolCatalog
from app.tools.contracts import ToolPayload, ToolUnavailableError
from app.tools.local_runtime import LocalRuntimeToolError, LocalRuntimeToolExecutor
from app.tools.permissions import ChatApprovalMode, ChatPermissionService
from app.tools.terminal import WorkspaceTerminalExecutor
from app.tools.command_jobs import CommandJobs


class ChatToolCatalog(ReadOnlyToolCatalog):
    """Chat tools backed by AgentOS, with legacy terminal compatibility only."""

    FILE_TOOL_NAMES = ("read_file", "list_files", "write_file", "patch_file")
    COMMAND_TOOL_NAMES = ("run_command", "get_command_output", "cancel_command")
    TOOL_NAMES = (*ReadOnlyToolCatalog.TOOL_NAMES, *FILE_TOOL_NAMES, "terminal", "read_archived_tool_result")
    supports_call_id = True
    supports_permission_events = True

    def __init__(
        self,
        *,
        local_runtime_executor: LocalRuntimeToolExecutor | None = None,
        legacy_terminal_enabled: bool | None = None,
        permission_service: ChatPermissionService | None = None,
        workspace_executor_factory: Callable[[], LocalRuntimeToolExecutor] | None = None,
    ) -> None:
        super().__init__()
        self._command_jobs = CommandJobs()
        self._local_runtime_executor = local_runtime_executor
        self._workspace_executor_factory = workspace_executor_factory
        # Composition roots explicitly inject the Chat policy. Keeping the
        # default empty preserves the unbound catalog's existing behavior.
        self.permission_service = permission_service
        self._workspace_id = (
            str(getattr(getattr(local_runtime_executor, "authorization", None), "workspace_id", ""))
            if local_runtime_executor is not None
            else ""
        )
        self._legacy_terminal_enabled = (
            bool(settings.CHAT_TERMINAL_ENABLED)
            if legacy_terminal_enabled is None
            else bool(legacy_terminal_enabled)
        )
        self._terminal_executor = (
            WorkspaceTerminalExecutor() if self._legacy_terminal_enabled else None
        )
        supports_shell = self._supports_capability("shell.exec")
        names = [*ReadOnlyToolCatalog.TOOL_NAMES, 'read_archived_tool_result']
        if self._local_runtime_executor is not None:
            names.extend(
                name
                for name in self.FILE_TOOL_NAMES
                if self._supports_capability(self._file_capability(name))
            )
        if supports_shell:
            names.extend(self.COMMAND_TOOL_NAMES)
        if self._legacy_terminal_enabled:
            names.append("terminal")
        # Keep the class-level tuple for compatibility, but let production
        # composition explicitly remove the legacy tool from this catalog.
        self.TOOL_NAMES = tuple(names)

    def availability(self, provider: str | None = None) -> dict[str, dict[str, Any]]:
        result = super().availability(provider)
        result['read_archived_tool_result'] = {'available': bool(settings.TOOL_RUNTIME_ENABLED),
            'provider': 'oscode-journal', 'readOnly': True, 'scope': 'authenticated conversation route'}
        for name, capability_id in {
            "read_file": "fs.read",
            "list_files": "fs.list",
            "write_file": "fs.write",
            "patch_file": "fs.patch",
            }.items():
            result[name] = {
                "available": bool(settings.TOOL_RUNTIME_ENABLED)
                and self._local_runtime_executor is not None
                and self._supports_capability(capability_id),
                "provider": "agentos-local-runtime",
                "readOnly": False,
                "scope": "trusted workspace",
                "capabilityId": capability_id,
            }
        result["run_command"] = {
            "available": bool(settings.TOOL_RUNTIME_ENABLED)
            and self._local_runtime_executor is not None
            and self._supports_capability("shell.exec"),
            "provider": "agentos-local-runtime",
            "readOnly": False,
            "scope": "current Windows user (approval required)",
            "capabilityId": "shell.exec",
            "securityProfile": "host_approved",
        }
        for name in ('get_command_output', 'cancel_command'):
            result[name] = {**result['run_command'], 'readOnly': name == 'get_command_output'}
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

    @staticmethod
    def _file_capability(tool_name: str) -> str:
        return {
            "read_file": "fs.read",
            "list_files": "fs.list",
            "write_file": "fs.write",
            "patch_file": "fs.patch",
        }[tool_name]

    def _supports_capability(self, capability_id: str) -> bool:
        if self._local_runtime_executor is None:
            return False
        checker = getattr(self._local_runtime_executor, "supports_capability", None)
        if checker is None:
            # Keep lightweight test and integration doubles compatible with the
            # original execute-only Local Runtime tool contract.
            return True
        return bool(checker(capability_id))

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        role_id: str | None = None,
        provider: str | None = None,
        call_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        approval_mode: ChatApprovalMode = "ask",
        protocol_session=None,
        permission_event_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ToolPayload:
        if name == 'read_archived_tool_result':
            from app.llm.chat_session import conversation_scope
            session = protocol_session
            if (not settings.TOOL_RUNTIME_ENABLED or session is None or session.projection_store is None
                    or conversation_scope(session.context_id) != session.session_id.split(':')[0]):
                raise ToolUnavailableError('Authenticated protocol journal is unavailable')
            reference = str(arguments.get('reference') or '')
            if not reference.startswith('journal:'):
                raise ValueError('ARCHIVED_RESULT_REFERENCE_INVALID')
            data = await asyncio.to_thread(session.projection_store.result, reference[8:],
                                          arguments.get('offset', 0), arguments.get('limit', 8192))
            return ToolPayload(summary='Archived original tool result (bounded read)', data=data)
        if name in (*self.FILE_TOOL_NAMES, *self.COMMAND_TOOL_NAMES):
            if not settings.TOOL_RUNTIME_ENABLED:
                raise ToolUnavailableError(f"local runtime tool is unavailable: {name}")
            if self._local_runtime_executor is None:
                raise LocalRuntimeToolError(
                    "LOCAL_RUNTIME_UNAVAILABLE", "Local Runtime is unavailable."
                )
            executor = self._workspace_executor_factory() if self._workspace_executor_factory else self._local_runtime_executor
            workspace_id = executor.authorization.workspace_id if self._workspace_executor_factory else self._workspace_id
            from app.security.internal_auth import current_trusted_user
            actor = current_trusted_user()
            owner = (getattr(actor, 'user_id', ''), getattr(actor, 'tenant_id', ''), workspace_id, str(session_id or ''))
            if name == 'get_command_output':
                return await self._command_jobs.output(str(arguments.get('execution_id') or ''), owner=owner,
                    after=arguments.get('after', 0), wait_ms=arguments.get('wait_ms', 0))
            if name == 'cancel_command':
                job = self._command_jobs.owned(str(arguments.get('execution_id') or ''), owner)
                if not job.task.done():
                    await executor.cancel(f'{job.request_id}:{job.call_id}')
                result = await self._command_jobs.output(job.execution_id, owner=owner, after=job.cursor, wait_ms=1000)
                result.data['cancellationRequested'] = True
                return result
            if self.permission_service is not None:
                await self.permission_service.authorize(
                    tool_name=name,
                    arguments=arguments,
                    call_id=str(call_id or ""),
                    session_id=str(session_id or ""),
                    workspace_id=workspace_id,
                    emit=permission_event_sink,
                    approval_mode=approval_mode,
                )
            del role_id, provider
            executor_kwargs: dict[str, Any] = {"call_id": str(call_id or "")}
            if name in self.COMMAND_TOOL_NAMES:
                executor_kwargs.update({
                    "request_id": str(request_id or session_id or call_id or ""),
                    "event_sink": permission_event_sink,
                })
            if name == 'run_command':
                async def execute(sink):
                    return await executor.execute(name, arguments, **{**executor_kwargs, 'event_sink': sink})
                return await self._command_jobs.start(execute, owner=owner,
                    request_id=executor_kwargs['request_id'], call_id=str(call_id or ''),
                    sink=permission_event_sink, yield_ms=arguments.get('yield_time_ms', 1000))
            return await executor.execute(
                name,
                arguments,
                **executor_kwargs,
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

    async def cancel(self, request_id: str) -> bool:
        if self._local_runtime_executor is None:
            return False
        cancel = getattr(self._local_runtime_executor, "cancel", None)
        if cancel is None:
            return False
        return await cancel(request_id)

    def detach_commands(self, request_id: str) -> None:
        self._command_jobs.detach(request_id)


__all__ = ["ChatToolCatalog"]
