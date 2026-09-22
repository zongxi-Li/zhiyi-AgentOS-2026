"""Real Chat shell capability path through AgentOS and the Local Runtime."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import pytest

from adapters.local_runtime import LocalRuntimeClient
from adapters.local_runtime_http import HttpLocalRuntimeTransport
from app.tools.chat_catalog import ChatToolCatalog
from app.tools.local_runtime import LocalRuntimeToolExecutor
from app.tools.permissions import ApprovalDecision, ChatPermissionService
from app.tools.runtime import SDK_TOOLS, ToolInvocationContext
from components.resource.health import ResourceHealthMonitor
from components.resource.health_store import InMemoryResourceHealthStore
from components.resource.local_runtime import (
    LocalRuntimeHealthProjector,
    LocalRuntimeResourceConfig,
    ensure_local_runtime_resource,
)
from components.resource.service import ResourceService
from components.resource.store import InMemoryResourceStore
from contracts.local_runtime import LocalRuntimeAuthorizationRef


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.mark.skipif(os.name != "nt", reason="PR-8 shell E2E targets Windows Local Runtime")
def test_chat_run_command_reaches_real_windows_runtime_with_approval(tmp_path: Path):
    async def scenario():
        local_root = Path(__file__).resolve().parents[2] / "local-runtime"
        agentos_src = Path(__file__).resolve().parents[2] / "agentOS" / "src"
        port = _free_port()
        resource_id = "chat-shell-e2e-runtime"
        credential_id = "chat-shell-e2e-credential"
        credential_secret = "chat-shell-e2e-secret"
        workspace_id = "chat-shell-e2e-workspace"
        grant_id = "chat-shell-e2e-grant"
        address = f"http://127.0.0.1:{port}/v1/executions"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(local_root), str(agentos_src)))
        environment.update({
            "ZHIYI_LOCAL_RUNTIME_RESOURCE_ID": resource_id,
            "ZHIYI_LOCAL_RUNTIME_ID": "chat-shell-e2e-process",
            "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_ID": credential_id,
            "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET": credential_secret,
            "ZHIYI_LOCAL_RUNTIME_WORKSPACE_ID": workspace_id,
            "ZHIYI_LOCAL_RUNTIME_GRANT_ID": grant_id,
            "ZHIYI_LOCAL_RUNTIME_WORKSPACE_ROOT": str(tmp_path),
            "ZHIYI_LOCAL_RUNTIME_CAPABILITIES": "fs.read,fs.list,fs.write,fs.patch,shell.exec",
            "ZHIYI_LOCAL_RUNTIME_BIND_HOST": "127.0.0.1",
            "ZHIYI_LOCAL_RUNTIME_PORT": str(port),
        })
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        process = subprocess.Popen(
            [sys.executable, "-m", "runtime.main"],
            cwd=str(local_root),
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=creationflags,
        )
        transport = None
        try:
            resource_service = ResourceService(
                store=InMemoryResourceStore(),
                health_monitor=ResourceHealthMonitor(
                    store=InMemoryResourceHealthStore(),
                    heartbeat_timeout=timedelta(seconds=5),
                ),
            )
            registered = ensure_local_runtime_resource(
                resource_service,
                LocalRuntimeResourceConfig(
                    resource_id=resource_id,
                    owner_scope="chat-shell-e2e",
                    execution_endpoint=address,
                    credential_id=credential_id,
                    credential_secret=credential_secret,
                    shell_exec_enabled=True,
                ),
            )
            transport = HttpLocalRuntimeTransport(
                resource_id=resource_id,
                address=address,
                credential_provider=resource_service,
                timeout_seconds=5,
            )
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f"runtime exited early: {process.returncode}")
                try:
                    health = await transport.health()
                    if "shell.exec" in health["capabilities"]:
                        break
                except Exception:
                    await asyncio.sleep(0.1)
            else:
                raise AssertionError("shell-enabled runtime did not become healthy")

            executor = LocalRuntimeToolExecutor(
                resource_service=resource_service,
                client=LocalRuntimeClient(transport),
                health_projector=LocalRuntimeHealthProjector(resource_service, resource_id),
                health_transport=transport,
                resource_id=registered.profile.resource_id,
                authorization=LocalRuntimeAuthorizationRef(grantId=grant_id, workspaceId=workspace_id),
            )
            permission = ChatPermissionService()
            catalog = ChatToolCatalog(
                local_runtime_executor=executor,
                legacy_terminal_enabled=False,
                permission_service=permission,
            )
            assert "run_command" in catalog.TOOL_NAMES
            assert set(SDK_TOOLS["run_command"].params_json_schema["properties"]).isdisjoint({
                "securityProfile", "grantId", "workspaceId", "resourceId", "allowedRoot"
            })
            queue = asyncio.Queue()
            context = ToolInvocationContext(
                catalog,
                frozenset({"run_command"}),
                session_id="chat-shell-session",
                request_id="chat-shell-request",
                permission_event_queue=queue,
            )
            task = asyncio.create_task(context.invoke(
                "run_command",
                {"mode": "shell", "command": "echo chat-shell-e2e", "cwd": "."},
                call_id="chat-shell-call",
            ))
            event, payload = await asyncio.wait_for(queue.get(), timeout=5)
            assert event == "approval_required"
            approval = payload["approval"]
            assert approval["capabilityId"] == "shell.exec"
            assert approval["operation"] == "Run command"
            await permission.resolve(
                approval["approvalId"],
                decision=ApprovalDecision.ALLOW_ONCE,
                session_id="chat-shell-session",
                invocation_id="chat-shell-call",
                capability_id="shell.exec",
                relative_path=".",
            )
            result = json.loads(await asyncio.wait_for(task, timeout=15))
            assert result["ok"] is True
            assert "chat-shell-e2e" in result["data"]["terminal"]["stdout"]
            assert result["data"]["terminal"]["exitCode"] == 0

            cancel_queue = asyncio.Queue()
            cancel_context = ToolInvocationContext(
                catalog,
                frozenset({"run_command"}),
                session_id="chat-shell-cancel-session",
                request_id="chat-shell-cancel",
                permission_event_queue=cancel_queue,
            )
            cancel_task = asyncio.create_task(cancel_context.invoke(
                "run_command",
                {"mode": "shell", "command": "ping 127.0.0.1 -n 30 > nul", "cwd": "."},
                call_id="chat-shell-cancel-call",
            ))
            cancel_event, cancel_payload = await asyncio.wait_for(cancel_queue.get(), timeout=5)
            assert cancel_event == "approval_required"
            cancel_approval = cancel_payload["approval"]
            await permission.resolve(
                cancel_approval["approvalId"],
                decision=ApprovalDecision.ALLOW_ONCE,
                session_id="chat-shell-cancel-session",
                invocation_id="chat-shell-cancel-call",
                capability_id="shell.exec",
                relative_path=".",
            )
            await asyncio.wait_for(cancel_queue.get(), timeout=5)  # approval_resolved
            started_event, _ = await asyncio.wait_for(cancel_queue.get(), timeout=5)
            assert started_event == "execution_started"
            assert await executor.cancel("chat-shell-cancel") is True
            cancelled = json.loads(await asyncio.wait_for(cancel_task, timeout=15))
            assert cancelled["ok"] is False
            assert cancelled["error"] == "EXECUTION_CANCELLED"
        finally:
            if transport is not None:
                await transport.aclose()
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert process.returncode == 0

    asyncio.run(scenario())
