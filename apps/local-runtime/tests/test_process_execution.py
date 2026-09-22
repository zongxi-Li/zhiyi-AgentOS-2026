from __future__ import annotations

import os
import re
import sys
import time

import pytest

from contracts.local_runtime import LocalRuntimeExecutionLimits
from process import ProcessExecutionMode, ProcessExecutionRequest, ProcessExecutionService
from runtime.errors import LocalRuntimeError
from workspace import CanonicalWorkspaceResolver


def _limits(timeout: float = 5, stdout: int = 4096, stderr: int = 4096):
    return LocalRuntimeExecutionLimits(
        timeoutSeconds=timeout,
        maxStdoutBytes=stdout,
        maxStderrBytes=stderr,
    )


def _direct(code: str, **kwargs) -> ProcessExecutionRequest:
    return ProcessExecutionRequest(
        mode=ProcessExecutionMode.DIRECT,
        program=sys.executable,
        args=["-c", code],
        **kwargs,
    )


def _wait_terminal(service: ProcessExecutionService, execution_id: str, *, request_id: str, invocation_id: str):
    cursor = -1
    events = []
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        batch, terminal, _state = service.events(
            execution_id,
            request_id=request_id,
            invocation_id=invocation_id,
            resource_id="runtime-test",
            after_sequence=cursor,
            wait_seconds=0.1,
        )
        events.extend(batch)
        if batch:
            cursor = max(event.sequence for event in batch)
        if terminal:
            return events
    raise AssertionError("process did not reach a terminal state")


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    try:
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259
    finally:
        kernel32.CloseHandle(handle)


@pytest.fixture
def process_service():
    service = ProcessExecutionService(CanonicalWorkspaceResolver())
    try:
        yield service
    finally:
        service.shutdown()


def test_direct_process_emits_incremental_stdout_and_stderr_and_nonzero_exit(tmp_path, process_service):
    request_id = "request-process-output"
    invocation_id = "invocation-process-output"
    request = _direct(
        "import sys; print('alpha', flush=True); print('warn', file=sys.stderr, flush=True); print('omega', flush=True); sys.exit(3)"
    )
    execution_id = process_service.start(
        request,
        root=tmp_path,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        limits=_limits(),
    )
    events = _wait_terminal(process_service, execution_id, request_id=request_id, invocation_id=invocation_id)

    assert [event.sequence for event in events] == sorted(event.sequence for event in events)
    assert events[0].event_type == "started"
    assert any(event.event_type == "stdout_delta" and "alpha" in event.data["delta"] for event in events)
    assert any(event.event_type == "stderr_delta" and "warn" in event.data["delta"] for event in events)
    assert events[-1].event_type == "failed"
    assert events[-1].data["code"] == "PROCESS_EXIT_NONZERO"


def test_shell_mode_is_structured_and_policy_checked(tmp_path, process_service):
    request_id = "request-process-shell"
    invocation_id = "invocation-process-shell"
    request = ProcessExecutionRequest(mode=ProcessExecutionMode.SHELL, command="echo shell-ok")
    execution_id = process_service.start(
        request,
        root=tmp_path,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        limits=_limits(),
    )
    events = _wait_terminal(process_service, execution_id, request_id=request_id, invocation_id=invocation_id)
    output = "".join(event.data.get("delta", "") for event in events if event.event_type == "stdout_delta")
    assert "shell-ok" in output
    assert events[-1].event_type == "completed"


def test_output_is_bounded_and_invalid_cwd_is_rejected(tmp_path, process_service):
    request_id = "request-process-bound"
    invocation_id = "invocation-process-bound"
    execution_id = process_service.start(
        _direct("print('x' * 10000, flush=True)"),
        root=tmp_path,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        limits=_limits(stdout=64, stderr=64),
    )
    events = _wait_terminal(process_service, execution_id, request_id=request_id, invocation_id=invocation_id)
    output_events = [event for event in events if event.event_type == "stdout_delta"]
    assert sum(event.data.get("bytes", 0) for event in output_events) <= 64
    assert any(event.data.get("truncated") for event in output_events)

    with pytest.raises(LocalRuntimeError) as invalid:
        process_service.start(
            _direct("print('must-not-run')", cwd="../"),
            root=tmp_path,
            request_id="request-invalid-cwd",
            invocation_id="invocation-invalid-cwd",
            resource_id="runtime-test",
            limits=_limits(),
        )
    assert invalid.value.code == "PATH_OUTSIDE_WORKSPACE"

    with pytest.raises(LocalRuntimeError) as absolute:
        process_service.start(
            _direct("print('must-not-run')", cwd=str(tmp_path)),
            root=tmp_path,
            request_id="request-absolute-cwd",
            invocation_id="invocation-absolute-cwd",
            resource_id="runtime-test",
            limits=_limits(),
        )
    assert absolute.value.code == "PATH_INVALID"


def test_policy_denies_destructive_commands_before_process_creation(tmp_path, process_service):
    request = _direct("").model_copy(update={"program": "git", "args": ["clean", "-fdx"]})
    with pytest.raises(LocalRuntimeError) as denied:
        process_service.start(
            request,
            root=tmp_path,
            request_id="request-denied",
            invocation_id="invocation-denied",
            resource_id="runtime-test",
            limits=_limits(),
        )
    assert denied.value.code == "COMMAND_DENIED"


def test_sensitive_runtime_environment_is_not_inherited(tmp_path, process_service, monkeypatch):
    monkeypatch.setenv("ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET", "must-not-leak")
    monkeypatch.setenv("ZHIYI_LOCAL_RUNTIME_HMAC_KEY", "must-not-leak")
    request_id = "request-process-env"
    invocation_id = "invocation-process-env"
    code = "import os; print(os.getenv('ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET', 'missing'), flush=True); print(os.getenv('ZHIYI_LOCAL_RUNTIME_HMAC_KEY', 'missing'), flush=True)"
    execution_id = process_service.start(
        _direct(code),
        root=tmp_path,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        limits=_limits(),
    )
    events = _wait_terminal(process_service, execution_id, request_id=request_id, invocation_id=invocation_id)
    output = "".join(event.data.get("delta", "") for event in events if event.event_type == "stdout_delta")
    assert "must-not-leak" not in output
    assert output.count("missing") == 2


def test_timeout_terminates_the_process_tree(tmp_path, process_service):
    request_id = "request-process-timeout"
    invocation_id = "invocation-process-timeout"
    execution_id = process_service.start(
        _direct("import time; time.sleep(60)"),
        root=tmp_path,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        limits=_limits(timeout=0.2),
    )
    events = _wait_terminal(process_service, execution_id, request_id=request_id, invocation_id=invocation_id)
    assert events[-1].event_type == "failed"
    assert events[-1].data["code"] == "EXECUTION_TIMEOUT"


def test_cancel_terminates_parent_and_child_process_tree(tmp_path, process_service):
    if os.name != "nt":
        pytest.skip("true process-tree containment check is Windows-specific")
    request_id = "request-process-tree"
    invocation_id = "invocation-process-tree"
    code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(child.pid, flush=True); time.sleep(60)"
    )
    execution_id = process_service.start(
        _direct(code),
        root=tmp_path,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        limits=_limits(timeout=30),
    )
    child_pid = None
    parent_pid = None
    cursor = -1
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and child_pid is None:
        events, _terminal, _state = process_service.events(
            execution_id,
            request_id=request_id,
            invocation_id=invocation_id,
            resource_id="runtime-test",
            after_sequence=cursor,
            wait_seconds=0.1,
        )
        text = "".join(event.data.get("delta", "") for event in events if event.event_type == "stdout_delta")
        match = re.search(r"\b(\d+)\b", text)
        if match:
            child_pid = int(match.group(1))
            parent_pid = process_service.supervisor._get(execution_id).process.pid
        if events:
            cursor = max(event.sequence for event in events)
    assert child_pid is not None and parent_pid is not None
    assert _pid_alive(parent_pid)
    assert _pid_alive(child_pid)

    assert process_service.cancel(
        execution_id,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
    ) in {"cancelling", "cancelled"}
    events = _wait_terminal(process_service, execution_id, request_id=request_id, invocation_id=invocation_id)
    assert events[-1].event_type == "cancelled"
    time.sleep(0.2)
    assert not _pid_alive(parent_pid)
    assert not _pid_alive(child_pid)


def test_shutdown_terminates_running_process_tree(tmp_path, process_service):
    request_id = "request-process-shutdown"
    invocation_id = "invocation-process-shutdown"
    execution_id = process_service.start(
        _direct("import time; time.sleep(60)"),
        root=tmp_path,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        limits=_limits(timeout=30),
    )
    time.sleep(0.2)
    process_service.shutdown()
    events, terminal, state = process_service.events(
        execution_id,
        request_id=request_id,
        invocation_id=invocation_id,
        resource_id="runtime-test",
        after_sequence=-1,
    )
    assert terminal is True
    assert state == "cancelled"
    assert events[-1].event_type == "cancelled"
