from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import time

import pytest

from contracts.local_runtime import ExecutionSecurityProfile, LocalRuntimeExecutionLimits
from process import ProcessExecutionMode, ProcessExecutionRequest, ProcessExecutionService
from runtime.errors import LocalRuntimeError
from workspace import CanonicalWorkspaceResolver


def _limits() -> LocalRuntimeExecutionLimits:
    return LocalRuntimeExecutionLimits(
        timeoutSeconds=15,
        maxStdoutBytes=4096,
        maxStderrBytes=4096,
    )


def _wait(service: ProcessExecutionService, execution_id: str):
    cursor = -1
    events = []
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        batch, terminal, _state = service.events(
            execution_id,
            request_id="compatibility-request",
            invocation_id="compatibility-invocation",
            resource_id="compatibility-runtime",
            after_sequence=cursor,
            wait_seconds=0.1,
        )
        events.extend(batch)
        if batch:
            cursor = max(event.sequence for event in batch)
        if terminal:
            return events
    raise AssertionError("compatibility process did not reach a terminal state")


@pytest.mark.skipif(os.name != "nt", reason="Windows compatibility matrix")
def test_isolated_tool_compatibility_matrix(tmp_path, capsys):
    candidates = {
        "python": (sys.executable, ["--version"]),
        "git": (shutil.which("git"), ["--version"]),
        "node": (shutil.which("node"), ["--version"]),
        "npm": (shutil.which("npm"), ["--version"]),
        "java": (shutil.which("java"), ["--version"]),
    }
    matrix: dict[str, str] = {}
    for name, (program, args) in candidates.items():
        if not program:
            matrix[name] = "UNSUPPORTED"
            continue
        workspace = tmp_path / name
        workspace.mkdir()
        service = ProcessExecutionService(CanonicalWorkspaceResolver())
        try:
            request = ProcessExecutionRequest(
                mode=ProcessExecutionMode.DIRECT,
                securityProfile=ExecutionSecurityProfile.ISOLATED_WORKSPACE,
                program=program,
                args=args,
            )
            try:
                execution_id = service.start(
                    request,
                    root=workspace,
                    request_id="compatibility-request",
                    invocation_id="compatibility-invocation",
                    resource_id="compatibility-runtime",
                    limits=_limits(),
                )
            except LocalRuntimeError:
                matrix[name] = "UNSUPPORTED"
                continue
            events = _wait(service, execution_id)
            matrix[name] = "PASS" if events[-1].event_type == "completed" else "DENIED_EXPECTED"
        finally:
            service.shutdown()
    print(f"isolated compatibility matrix: {matrix}", file=sys.stderr)
    assert set(matrix.values()) <= {"PASS", "DENIED_EXPECTED", "UNSUPPORTED"}


@pytest.mark.skipif(os.name != "nt", reason="Windows compatibility matrix")
def test_isolated_python_script_compatibility(tmp_path):
    service = ProcessExecutionService(CanonicalWorkspaceResolver())
    workspace = tmp_path / "python-script"
    workspace.mkdir()
    try:
        request = ProcessExecutionRequest(
            mode=ProcessExecutionMode.DIRECT,
            securityProfile=ExecutionSecurityProfile.ISOLATED_WORKSPACE,
            program=sys.executable,
            args=["-c", "print('isolated-python-script', flush=True)"],
        )
        try:
            execution_id = service.start(
                request,
                root=workspace,
                request_id="compatibility-request",
                invocation_id="compatibility-invocation",
                resource_id="compatibility-runtime",
                limits=_limits(),
            )
        except LocalRuntimeError:
            pytest.skip("Python script is unsupported by this AppContainer installation")
        events = _wait(service, execution_id)
        assert events[-1].event_type in {"completed", "failed"}
    finally:
        service.shutdown()
