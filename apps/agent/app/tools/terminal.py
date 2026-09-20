"""Bounded workspace terminal execution for the Chat tool runtime.

This adapter is intentionally separate from the AgentOS/ACG runtime.  Chat can
opt into it without adding terminal capability to the ACG agent registry.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
from pathlib import Path
from typing import Any

from app.config import settings


_SENSITIVE_ENV = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
_BLOCKED_COMMAND = re.compile(
    r"(?:/run/(?:secrets|kinlin-secrets)|/app/data|/proc(?:/|\s|$)|/sys(?:/|\s|$)|"
    r"\b(?:docker|kubectl|shutdown|reboot|poweroff|mkfs)\b)",
    re.IGNORECASE,
)


class TerminalSecurityError(RuntimeError):
    code = "TERMINAL_SECURITY_ERROR"


class TerminalExecutionError(RuntimeError):
    """A command completed with a non-success terminal result."""

    def __init__(self, code: str, message: str, terminal: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.terminal = terminal


async def _read_limited(stream: asyncio.StreamReader, limit: int) -> tuple[str, bool]:
    chunks: list[bytes] = []
    size = 0
    truncated = False
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        if size < limit:
            allowed = chunk[: max(0, limit - size)]
            chunks.append(allowed)
            size += len(allowed)
        if len(chunk) > max(0, limit - size):
            truncated = True
    return b"".join(chunks).decode("utf-8", errors="replace"), truncated


class WorkspaceTerminalExecutor:
    """Run a command inside a configured workspace with bounded output/time."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = str(
            root
            or settings.TOOL_TERMINAL_ROOT.strip()
            or settings.TOOL_CODEBASE_ROOT.strip()
            or Path.cwd()
        )
        self.root = Path(configured).expanduser().resolve()

    def resolve_cwd(self, requested: str | None) -> Path:
        if not self.root.is_dir():
            raise TerminalSecurityError("configured terminal workspace does not exist")
        raw = str(requested or ".").strip() or "."
        candidate = Path(raw)
        resolved = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise TerminalSecurityError("terminal cwd escapes the configured workspace") from exc
        if not resolved.is_dir():
            raise TerminalSecurityError("terminal cwd is not an existing directory")
        return resolved

    @staticmethod
    def _environment(cwd: Path) -> dict[str, str]:
        environment = {
            str(key): str(value)
            for key, value in os.environ.items()
            if not _SENSITIVE_ENV.search(str(key))
        }
        environment["PWD"] = str(cwd)
        return environment

    async def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout_seconds: float | int | None = None,
    ) -> dict[str, Any]:
        command = str(command or "").strip()
        if not command:
            raise ValueError("terminal command must not be empty")
        if len(command) > 4_000:
            raise ValueError("terminal command is too long")
        if _BLOCKED_COMMAND.search(command):
            raise TerminalSecurityError("terminal command targets a protected system resource")

        resolved_cwd = self.resolve_cwd(cwd)
        requested_timeout = float(
            settings.TOOL_TERMINAL_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        )
        max_timeout = max(0.1, float(settings.TOOL_TERMINAL_MAX_TIMEOUT_SECONDS))
        if requested_timeout <= 0:
            raise ValueError("terminal timeout_seconds must be positive")
        timeout = min(requested_timeout, max_timeout)
        output_limit = max(256, int(settings.TOOL_TERMINAL_MAX_OUTPUT_BYTES))

        process_options: dict[str, Any] = {
            "cwd": str(resolved_cwd),
            "env": self._environment(resolved_cwd),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name != "nt":
            process_options["start_new_session"] = True
        process = await asyncio.create_subprocess_shell(command, **process_options)
        started = asyncio.get_running_loop().time()
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(_read_limited(process.stdout, output_limit))
        stderr_task = asyncio.create_task(_read_limited(process.stderr, output_limit))
        timed_out = False
        try:
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                timed_out = True
                if process.returncode is None:
                    if os.name != "nt" and process.pid:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    await process.wait()
            try:
                stdout, stdout_truncated = await asyncio.wait_for(
                    stdout_task, timeout=2.0 if timed_out else None
                )
                stderr, stderr_truncated = await asyncio.wait_for(
                    stderr_task, timeout=2.0 if timed_out else None
                )
            except asyncio.TimeoutError:
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                stdout, stderr = "", ""
                stdout_truncated = stderr_truncated = True
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise

        result = {
            "command": command,
            "cwd": str(resolved_cwd),
            "exitCode": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timedOut": timed_out,
            "truncated": stdout_truncated or stderr_truncated,
            "durationMs": int((asyncio.get_running_loop().time() - started) * 1000),
        }
        if timed_out:
            raise TerminalExecutionError(
                "TERMINAL_TIMEOUT",
                f"terminal command timed out after {timeout:g}s",
                result,
            )
        if process.returncode != 0:
            raise TerminalExecutionError(
                "TERMINAL_EXIT_NONZERO",
                f"terminal command exited with code {process.returncode}",
                result,
            )
        return result


__all__ = [
    "TerminalExecutionError",
    "TerminalSecurityError",
    "WorkspaceTerminalExecutor",
]
