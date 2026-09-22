"""Chat permission approval over the real AgentOS-to-Windows Local Runtime path."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

from adapters.local_runtime import LocalRuntimeClient
from adapters.local_runtime_http import HttpLocalRuntimeTransport
from app.tools.chat_catalog import ChatToolCatalog
from app.tools.local_runtime import LocalRuntimeToolExecutor
from app.tools.permissions import ApprovalDecision, ChatPermissionService
from app.tools.runtime import ToolInvocationContext
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


async def _wait_for_health_async(transport: HttpLocalRuntimeTransport, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"local runtime exited before health became available: {process.returncode}")
        try:
            await transport.health()
            return
        except Exception:
            await asyncio.sleep(0.1)
    raise AssertionError("local runtime health did not become available")


def test_chat_approval_reaches_real_local_runtime_after_decision(tmp_path):
    local_root = Path(__file__).resolve().parents[2] / "local-runtime"
    agentos_src = Path(__file__).resolve().parents[2] / "agentOS" / "src"
    port = _free_port()
    resource_id = "chat-approval-e2e-runtime"
    credential_id = "chat-approval-e2e-credential"
    credential_secret = "chat-approval-e2e-secret"
    workspace_id = "chat-approval-e2e-workspace"
    grant_id = "chat-approval-e2e-grant"
    address = f"http://127.0.0.1:{port}/v1/executions"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(local_root), str(agentos_src)))
    environment.update({
        "ZHIYI_LOCAL_RUNTIME_RESOURCE_ID": resource_id,
        "ZHIYI_LOCAL_RUNTIME_ID": "chat-approval-e2e-process",
        "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_ID": credential_id,
        "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET": credential_secret,
        "ZHIYI_LOCAL_RUNTIME_WORKSPACE_ID": workspace_id,
        "ZHIYI_LOCAL_RUNTIME_GRANT_ID": grant_id,
        "ZHIYI_LOCAL_RUNTIME_WORKSPACE_ROOT": str(tmp_path),
        "ZHIYI_LOCAL_RUNTIME_BIND_HOST": "127.0.0.1",
        "ZHIYI_LOCAL_RUNTIME_PORT": str(port),
    })
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "runtime.main"],
        cwd=str(local_root),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        creationflags=creationflags,
    )

    async def scenario():
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
                owner_scope="chat-approval-e2e",
                execution_endpoint=address,
                credential_id=credential_id,
                credential_secret=credential_secret,
            ),
        )
        transport = HttpLocalRuntimeTransport(
            resource_id=resource_id,
            address=address,
            credential_provider=resource_service,
            timeout_seconds=5,
        )
        await _wait_for_health_async(transport, process)
        executor = LocalRuntimeToolExecutor(
            resource_service=resource_service,
            client=LocalRuntimeClient(transport),
            health_projector=LocalRuntimeHealthProjector(resource_service, resource_id),
            health_transport=transport,
            resource_id=registered.profile.resource_id,
            authorization=LocalRuntimeAuthorizationRef(
                grantId=grant_id,
                workspaceId=workspace_id,
            ),
        )
        permission_service = ChatPermissionService()
        catalog = ChatToolCatalog(
            local_runtime_executor=executor,
            permission_service=permission_service,
            legacy_terminal_enabled=False,
        )
        events = asyncio.Queue()
        context = ToolInvocationContext(
            catalog,
            frozenset({"read_file", "list_files", "write_file", "patch_file"}),
            session_id="chat-approval-session",
            permission_event_queue=events,
            max_calls=8,
        )

        first = asyncio.create_task(
            context.invoke(
                "write_file",
                {"path": "approval.txt", "content": "alpha\n", "overwrite": False},
                call_id="chat-call-1",
            )
        )
        event_name, event_payload = await events.get()
        assert event_name == "approval_required"
        approval = event_payload["approval"]
        assert not (tmp_path / "approval.txt").exists()
        await permission_service.resolve(
            approval["approvalId"],
            decision=ApprovalDecision.ALLOW_ONCE,
            session_id="chat-approval-session",
            invocation_id="chat-call-1",
            capability_id="fs.write",
            relative_path="approval.txt",
        )
        assert (await events.get())[0] == "approval_resolved"
        first_result = json.loads(await first)
        assert first_result["ok"] is True
        assert (tmp_path / "approval.txt").read_text(encoding="utf-8") == "alpha\n"

        second = asyncio.create_task(
            context.invoke(
                "write_file",
                {"path": "approval.txt", "content": "beta\n", "overwrite": True},
                call_id="chat-call-2",
            )
        )
        _, second_payload = await events.get()
        await permission_service.resolve(
            second_payload["approval"]["approvalId"],
            decision=ApprovalDecision.ALLOW_SESSION,
            session_id="chat-approval-session",
            invocation_id="chat-call-2",
            capability_id="fs.write",
            relative_path="approval.txt",
        )
        assert (await events.get())[0] == "approval_resolved"
        assert json.loads(await second)["ok"] is True

        third = await context.invoke(
            "write_file",
            {"path": "approval.txt", "content": "gamma\n", "overwrite": True},
            call_id="chat-call-3",
        )
        assert json.loads(third)["ok"] is True

        read = json.loads(await context.invoke("read_file", {"path": "approval.txt"}, call_id="chat-call-4"))
        listed = json.loads(await context.invoke("list_files", {"path": "."}, call_id="chat-call-5"))
        assert read["data"]["result"]["content"] == "gamma\n"
        assert any(item["path"] == "approval.txt" for item in listed["data"]["result"]["entries"])

        denied = asyncio.create_task(
            context.invoke(
                "patch_file",
                {
                    "path": "approval.txt",
                    "patch": "@@ -1 +1 @@\n-gamma\n+denied\n",
                },
                call_id="chat-call-6",
            )
        )
        _, denied_payload = await events.get()
        before = (tmp_path / "approval.txt").read_text(encoding="utf-8")
        await permission_service.resolve(
            denied_payload["approval"]["approvalId"],
            decision=ApprovalDecision.DENY,
            session_id="chat-approval-session",
            invocation_id="chat-call-6",
            capability_id="fs.patch",
            relative_path="approval.txt",
        )
        assert (await events.get())[0] == "approval_resolved"
        denied_result = json.loads(await denied)
        assert denied_result["ok"] is False
        assert denied_result["error"] == "PERMISSION_DENIED"
        assert (tmp_path / "approval.txt").read_text(encoding="utf-8") == before
        await transport.aclose()

    try:
        asyncio.run(scenario())
    finally:
        if process.poll() is None:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGTERM)
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
