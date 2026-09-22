from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import importlib.util
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

LOCAL_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
AGENTOS_SRC = LOCAL_RUNTIME_ROOT.parent / "agentOS" / "src"
AGENTOS_ROOT = LOCAL_RUNTIME_ROOT.parent / "agentOS"
AGENT_APP = LOCAL_RUNTIME_ROOT.parent / "agent" / "app"
if str(AGENTOS_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTOS_ROOT))
if str(AGENT_APP) not in sys.path:
    sys.path.insert(0, str(AGENT_APP))

import httpx
import pytest

from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeCapability,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionRequest,
)

_TRANSPORT_SPEC = importlib.util.spec_from_file_location(
    "agentos_local_runtime_http",
    AGENTOS_SRC / "adapters" / "local_runtime_http.py",
)
assert _TRANSPORT_SPEC is not None and _TRANSPORT_SPEC.loader is not None
_TRANSPORT_MODULE = importlib.util.module_from_spec(_TRANSPORT_SPEC)
_TRANSPORT_SPEC.loader.exec_module(_TRANSPORT_MODULE)
HttpLocalRuntimeTransport = _TRANSPORT_MODULE.HttpLocalRuntimeTransport


RESOURCE_ID = "zhiyi-local-runtime-e2e"
CREDENTIAL_ID = "credential-e2e"
SECRET = "e2e-secret-not-printed"


class _CredentialProvider:
    def current_signing_credential(self, resource_id: str) -> tuple[str, str]:
        assert resource_id == RESOURCE_ID
        return CREDENTIAL_ID, SECRET


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(capability: LocalRuntimeCapability, input_data: dict, *, grant_id: str = "grant-valid"):
    return LocalRuntimeExecutionRequest(
        protocolVersion="1",
        requestId=f"request-{time.time_ns()}",
        invocationId=f"invocation-{time.time_ns()}",
        resourceId=RESOURCE_ID,
        capabilityId=capability,
        authorization=LocalRuntimeAuthorizationRef(
            grantId=grant_id,
            workspaceId="workspace-e2e",
        ),
        input=input_data,
        limits=LocalRuntimeExecutionLimits(
            timeoutSeconds=10,
            maxStdoutBytes=8192,
            maxStderrBytes=8192,
        ),
        idempotencyKey=f"idempotency-{time.time_ns()}",
    )


def _write_bootstrap(path: Path, root: Path) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "schemaVersion": 1,
        "workspaces": [{"workspaceId": "workspace-e2e", "root": str(root)}],
        "grants": [
            {
                "grantId": "grant-valid",
                "workspaceId": "workspace-e2e",
                "capabilities": [capability.value for capability in LocalRuntimeCapability],
                "createdAt": now.isoformat(),
            },
            {
                "grantId": "grant-revoked",
                "workspaceId": "workspace-e2e",
                "capabilities": [LocalRuntimeCapability.SHELL_EXEC.value],
                "createdAt": now.isoformat(),
                "revoked": True,
            },
            {
                "grantId": "grant-expired",
                "workspaceId": "workspace-e2e",
                "capabilities": [LocalRuntimeCapability.SHELL_EXEC.value],
                "createdAt": (now - timedelta(hours=2)).isoformat(),
                "expiresAt": (now - timedelta(hours=1)).isoformat(),
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _start_runtime(tmp_path: Path):
    port = _free_port()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bootstrap = tmp_path / "grants.json"
    _write_bootstrap(bootstrap, workspace)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(LOCAL_RUNTIME_ROOT), str(AGENTOS_SRC)))
    environment.update({
        "ZHIYI_LOCAL_RUNTIME_RESOURCE_ID": RESOURCE_ID,
        "ZHIYI_LOCAL_RUNTIME_ID": "runtime-e2e",
        "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_ID": CREDENTIAL_ID,
        "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET": SECRET,
        "ZHIYI_LOCAL_RUNTIME_GRANTS_FILE": str(bootstrap),
        "ZHIYI_LOCAL_RUNTIME_BIND_HOST": "127.0.0.1",
        "ZHIYI_LOCAL_RUNTIME_PORT": str(port),
    })
    creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    process = subprocess.Popen(
        [sys.executable, "-m", "runtime.main"],
        cwd=LOCAL_RUNTIME_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    address = f"http://127.0.0.1:{port}/v1/executions"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            process.communicate()
            raise AssertionError("independent local runtime failed to start")
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.3)
            health = response.json()
            if response.status_code == 200 and health.get("status") == "online":
                assert health["runtimeId"] == "runtime-e2e"
                assert health["resourceId"] == RESOURCE_ID
                assert health["protocolVersion"] == "1"
                assert "shell.exec" not in health["capabilities"]
                return process, address, workspace
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=5)
    raise AssertionError("independent local runtime did not become healthy")


async def _run_e2e(tmp_path: Path) -> None:
    process, address, workspace = _start_runtime(tmp_path)
    transport = HttpLocalRuntimeTransport(
        resource_id=RESOURCE_ID,
        address=address,
        credential_provider=_CredentialProvider(),
        timeout_seconds=5,
    )
    try:
        valid = _request(
            LocalRuntimeCapability.SHELL_EXEC,
            {
                "mode": "direct",
                "program": sys.executable,
                "args": ["-c", "import sys; print('alpha', flush=True); print('beta', file=sys.stderr, flush=True)"],
                "cwd": ".",
            },
        )
        accepted = await transport.execute(valid)
        assert accepted.status == "accepted"
        execution_id = accepted.output["executionId"]
        events = [event async for event in transport.stream_events(
            execution_id=execution_id,
            request_id=valid.request_id,
            invocation_id=valid.invocation_id,
        )]
        assert events[0].event_type == "started"
        assert any(event.event_type == "stdout_delta" and "alpha" in event.data.get("delta", "") for event in events)
        assert any(event.event_type == "stderr_delta" and "beta" in event.data.get("delta", "") for event in events)
        assert events[-1].event_type == "completed"

        revoked = _request(
            LocalRuntimeCapability.SHELL_EXEC,
            {"mode": "direct", "program": sys.executable, "args": ["-c", "print('must-not-run')"]},
            grant_id="grant-revoked",
        )
        revoked_result = await transport.execute(revoked)
        assert revoked_result.status == "failed"
        assert revoked_result.error.code == "GRANT_REVOKED"

        expired = _request(
            LocalRuntimeCapability.SHELL_EXEC,
            {"mode": "direct", "program": sys.executable, "args": ["-c", "print('must-not-run')"]},
            grant_id="grant-expired",
        )
        expired_result = await transport.execute(expired)
        assert expired_result.status == "failed"
        assert expired_result.error.code == "GRANT_EXPIRED"

        long_request = _request(
            LocalRuntimeCapability.SHELL_EXEC,
            {"mode": "direct", "program": sys.executable, "args": ["-c", "import time; time.sleep(60)"]},
        )
        long_result = await transport.execute(long_request)
        assert await transport.cancel(
            execution_id=long_result.output["executionId"],
            request_id=long_request.request_id,
            invocation_id=long_request.invocation_id,
        ) in {"cancelling", "cancelled"}
        cancelled = [event async for event in transport.stream_events(
            execution_id=long_result.output["executionId"],
            request_id=long_request.request_id,
            invocation_id=long_request.invocation_id,
        )]
        assert cancelled[-1].event_type == "cancelled"

        process.send_signal(signal.CTRL_BREAK_EVENT if hasattr(signal, "CTRL_BREAK_EVENT") else signal.SIGTERM)
        return_code = process.wait(timeout=10)
        assert return_code == 0
    finally:
        await transport.aclose()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.asyncio
async def test_independent_windows_runtime_process_execution_e2e(tmp_path):
    if os.name != "nt":
        pytest.skip("independent runtime process E2E is Windows-specific")
    await _run_e2e(tmp_path)


@pytest.mark.asyncio
async def test_independent_windows_isolated_workspace_e2e(tmp_path):
    if os.name != "nt":
        pytest.skip("independent runtime process E2E is Windows-specific")
    process, address, workspace = _start_runtime(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "input.txt").write_text("workspace", encoding="utf-8")
    (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")
    transport = HttpLocalRuntimeTransport(
        resource_id=RESOURCE_ID,
        address=address,
        credential_provider=_CredentialProvider(),
        timeout_seconds=30,
    )
    try:
        command = (
            f'echo generated>"generated.txt"'
            f' & type "{workspace / "input.txt"}"'
            f' & type "{outside / "secret.txt"}" >nul 2>nul && echo outside-read-allowed || echo outside-read-denied'
            f' & (echo must-not-write>"{outside / "created.txt"}") 2>nul && echo outside-write-allowed || echo outside-write-denied'
        )
        request = _request(
            LocalRuntimeCapability.SHELL_EXEC,
            {
                "mode": "shell",
                "securityProfile": "isolated_workspace",
                "command": command,
                "cwd": ".",
            },
        )
        accepted = await transport.execute(request)
        assert accepted.status == "accepted"
        events = [event async for event in transport.stream_events(
            execution_id=accepted.output["executionId"],
            request_id=request.request_id,
            invocation_id=request.invocation_id,
        )]
        output = "".join(
            event.data.get("delta", "")
            for event in events
            if event.event_type == "stdout_delta"
        )
        assert events[-1].event_type == "completed", output
        assert "workspace" in output
        assert "outside-read-denied" in output
        assert "outside-write-denied" in output
        assert (workspace / "generated.txt").exists()
        assert not (outside / "created.txt").exists()
    finally:
        await transport.aclose()
        if process.poll() is None:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                pytest.fail("isolated runtime required terminate/kill fallback", pytrace=False)
            assert return_code == 0
        else:
            assert process.returncode == 0
