"""Chat-only terminal capability and workspace boundary tests."""

import asyncio
import json
import shlex
import sys

import pytest

from app.config import settings
from app.tools.catalog import ReadOnlyToolCatalog
from app.tools.chat_catalog import ChatToolCatalog
from app.tools.terminal import TerminalSecurityError
from app.tools.runtime import ToolInvocationContext


def _python_command(source: str) -> str:
    executable = shlex.quote(sys.executable) if sys.platform != "win32" else sys.executable
    argument = shlex.quote(source) if sys.platform != "win32" else f'"{source}"'
    return f"{executable} -c {argument}"


def test_chat_catalog_adds_terminal_without_expanding_acg_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_TERMINAL_ENABLED", True)
    monkeypatch.setattr(settings, "TOOL_TERMINAL_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "TOOL_CODEBASE_ROOT", "")

    assert "terminal" not in ReadOnlyToolCatalog.TOOL_NAMES
    catalog = ChatToolCatalog()
    assert "terminal" in catalog.TOOL_NAMES
    assert catalog.availability()["terminal"]["available"] is True


def test_chat_terminal_returns_bounded_command_output(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_TERMINAL_ENABLED", True)
    monkeypatch.setattr(settings, "TOOL_TERMINAL_ROOT", str(tmp_path))

    payload = asyncio.run(ChatToolCatalog().execute(
        "terminal",
        {"command": _python_command("print('terminal-ok')")},
    ))

    assert payload.data["terminal"]["stdout"].strip() == "terminal-ok"
    assert payload.data["terminal"]["exitCode"] == 0
    assert payload.data["terminal"]["cwd"] == str(tmp_path.resolve())


def test_chat_terminal_rejects_workspace_escape(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_TERMINAL_ENABLED", True)
    monkeypatch.setattr(settings, "TOOL_TERMINAL_ROOT", str(tmp_path))

    with pytest.raises(TerminalSecurityError, match="escapes"):
        asyncio.run(ChatToolCatalog().execute("terminal", {"command": "echo nope", "cwd": ".."}))


def test_chat_terminal_reports_nonzero_exit_with_output(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    monkeypatch.setattr(settings, "CHAT_TERMINAL_ENABLED", True)
    monkeypatch.setattr(settings, "TOOL_TERMINAL_ROOT", str(tmp_path))

    catalog = ChatToolCatalog()
    context = ToolInvocationContext(catalog, frozenset({"terminal"}))
    payload = json.loads(asyncio.run(context.invoke(
        "terminal",
        {"command": _python_command("import sys; print('failed-output'); sys.exit(3)")},
    )))

    assert payload["terminal"]["exitCode"] == 3
    assert payload["terminal"]["stdout"].strip() == "failed-output"
    assert context.records[0].status == "failed"
    assert context.records[0].terminal["exitCode"] == 3
