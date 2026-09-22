from __future__ import annotations

import os
import sys
import time

import pytest

from contracts.local_runtime import ExecutionSecurityProfile, LocalRuntimeExecutionLimits
from process import ProcessExecutionMode, ProcessExecutionRequest, ProcessExecutionService
from runtime.errors import LocalRuntimeError
from security import ISOLATED_NETWORK_GUARANTEE, probe_appcontainer_support
from workspace import CanonicalWorkspaceResolver


def _limits() -> LocalRuntimeExecutionLimits:
    return LocalRuntimeExecutionLimits(
        timeoutSeconds=10,
        maxStdoutBytes=8192,
        maxStderrBytes=8192,
    )


def _wait_terminal(service: ProcessExecutionService, execution_id: str):
    cursor = -1
    events = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        batch, terminal, _state = service.events(
            execution_id,
            request_id="isolation-request",
            invocation_id="isolation-invocation",
            resource_id="isolation-runtime",
            after_sequence=cursor,
            wait_seconds=0.1,
        )
        events.extend(batch)
        if batch:
            cursor = max(event.sequence for event in batch)
        if terminal:
            return events
    raise AssertionError("isolated process did not reach a terminal state")


@pytest.fixture
def process_service():
    service = ProcessExecutionService(CanonicalWorkspaceResolver())
    try:
        yield service
    finally:
        service.shutdown()


def test_security_profile_is_restricted_and_does_not_accept_identity_fields():
    request = ProcessExecutionRequest(
        mode=ProcessExecutionMode.DIRECT,
        securityProfile=ExecutionSecurityProfile.ISOLATED_WORKSPACE,
        program=sys.executable,
        args=["-c", "print('ok')"],
    )
    assert request.security_profile is ExecutionSecurityProfile.ISOLATED_WORKSPACE
    with pytest.raises(ValueError):
        ProcessExecutionRequest(
            mode=ProcessExecutionMode.DIRECT,
            program=sys.executable,
            args=["-c", "print('must-not-run')"],
            identitySid="S-1-5-18",
        )


def test_appcontainer_probe_and_network_guarantee_are_explicit():
    probe = probe_appcontainer_support()
    if os.name == "nt":
        assert probe.selected is True
        assert "CreateAppContainerToken" in probe.api_surface
    else:
        assert probe.selected is False
    assert ISOLATED_NETWORK_GUARANTEE == "unavailable"


@pytest.mark.skipif(os.name != "nt", reason="AppContainer boundary is Windows-specific")
def test_isolated_workspace_uses_os_boundary_for_workspace_and_outside(tmp_path, process_service):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "input.txt").write_text("workspace", encoding="utf-8")
    (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")
    outside_secret = outside / "secret.txt"
    outside_created = outside / "created.txt"
    code = (
        f'echo generated>"generated.txt"'
        f' & type "{workspace / "input.txt"}"'
        f' & type "{outside_secret}" >nul 2>nul && echo outside-read-allowed || echo outside-read-denied'
        f' & (echo must-not-write>"{outside_created}") 2>nul && echo outside-write-allowed || echo outside-write-denied'
        f' & if defined ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET (echo secret-present) else (echo secret-absent)'
        f' & echo %TEMP%'
    )
    request = ProcessExecutionRequest(
        mode=ProcessExecutionMode.SHELL,
        securityProfile=ExecutionSecurityProfile.ISOLATED_WORKSPACE,
        command=code,
    )
    execution_id = process_service.start(
        request,
        root=workspace,
        request_id="isolation-request",
        invocation_id="isolation-invocation",
        resource_id="isolation-runtime",
        limits=_limits(),
    )
    events = _wait_terminal(process_service, execution_id)
    output = "".join(
        event.data.get("delta", "")
        for event in events
        if event.event_type == "stdout_delta"
    )
    assert events[-1].event_type == "completed", output
    assert "workspace" in output
    assert "outside-read-denied" in output
    assert "outside-write-denied" in output
    assert (workspace / "generated.txt").read_text(encoding="utf-8").strip() == "generated"
    assert not outside_created.exists()
    assert "secret-absent" in output
    assert ".zhiyi-runtime-temp" in output


@pytest.mark.skipif(os.name != "nt", reason="Restricted Token boundary is Windows-specific")
def test_isolated_profile_rejects_elevation_and_network_install_before_launch(tmp_path, process_service):
    with pytest.raises(LocalRuntimeError) as elevation:
        process_service.start(
            ProcessExecutionRequest(
                mode=ProcessExecutionMode.SHELL,
                securityProfile=ExecutionSecurityProfile.ISOLATED_WORKSPACE,
                command="Start-Process cmd.exe -Verb RunAs",
            ),
            root=tmp_path,
            request_id="isolation-request",
            invocation_id="isolation-invocation",
            resource_id="isolation-runtime",
            limits=_limits(),
        )
    assert elevation.value.code == "ELEVATION_NOT_ALLOWED"

    with pytest.raises(LocalRuntimeError) as network:
        process_service.start(
            ProcessExecutionRequest(
                mode=ProcessExecutionMode.DIRECT,
                securityProfile=ExecutionSecurityProfile.ISOLATED_WORKSPACE,
                program="npm",
                args=["install", "some-package"],
            ),
            root=tmp_path,
            request_id="isolation-request",
            invocation_id="isolation-invocation",
            resource_id="isolation-runtime",
            limits=_limits(),
        )
    assert network.value.code == "NETWORK_DENIED"
