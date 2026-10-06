"""Real Chat tool-runtime to independent Local Runtime HTTP smoke test."""

from __future__ import annotations

import os
import json
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
from app.tools.runtime import AgentsToolRuntime
from components.resource.health import ResourceHealthMonitor
from components.resource.health_store import InMemoryResourceHealthStore
from components.resource.local_runtime import (
    LocalRuntimeHealthProjector,
    LocalRuntimeResourceConfig,
    ensure_local_runtime_resource,
)
from components.resource.service import ResourcePlane
from components.resource.store import InMemoryResourceStore
from contracts.local_runtime import LocalRuntimeAuthorizationRef


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(transport: HttpLocalRuntimeTransport, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"local runtime exited before health became available: {process.returncode}")
        try:
            import asyncio

            asyncio.run(transport.health())
            return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("local runtime health did not become available")


def test_chat_agents_runtime_reaches_independent_local_runtime(tmp_path):
    local_root = Path(__file__).resolve().parents[2] / "local-runtime"
    agentos_src = Path(__file__).resolve().parents[2] / "agentOS" / "src"
    port = _free_port()
    resource_id = "chat-e2e-runtime"
    credential_id = "chat-e2e-credential"
    credential_secret = "chat-e2e-secret"
    workspace_id = "chat-e2e-workspace"
    grant_id = "chat-e2e-grant"
    address = f"http://127.0.0.1:{port}/v1/executions"

    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(local_root), str(agentos_src)))
    environment.update({
        "ZHIYI_LOCAL_RUNTIME_RESOURCE_ID": resource_id,
        "ZHIYI_LOCAL_RUNTIME_ID": "chat-e2e-runtime-process",
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

    import asyncio

    transport = None
    try:
        plane = ResourcePlane(
            store=InMemoryResourceStore(),
            health_monitor=ResourceHealthMonitor(
                store=InMemoryResourceHealthStore(),
                heartbeat_timeout=timedelta(seconds=5),
            ),
        )
        registered = ensure_local_runtime_resource(
            plane,
            LocalRuntimeResourceConfig(
                resource_id=resource_id,
                owner_scope="chat-e2e",
                execution_endpoint=address,
                credential_id=credential_id,
                credential_secret=credential_secret,
            ),
        )
        transport = HttpLocalRuntimeTransport(
            resource_id=resource_id,
            address=address,
            credential_provider=plane,
            timeout_seconds=5,
        )
        _wait_for_health(transport, process)
        executor = LocalRuntimeToolExecutor(
            resource_plane=plane,
            client=LocalRuntimeClient(transport),
            health_projector=LocalRuntimeHealthProjector(plane, resource_id),
            health_transport=transport,
            resource_id=registered.profile.runtime_id,
            authorization=LocalRuntimeAuthorizationRef(
                grantId=grant_id,
                workspaceId=workspace_id,
            ),
        )
        catalog = ChatToolCatalog(
            local_runtime_executor=executor,
            legacy_terminal_enabled=False,
        )
        runtime = AgentsToolRuntime(catalog=catalog)

        asyncio.run(runtime.execute(
            "write_file",
            {"path": "hello.txt", "content": "alpha\nbeta\n", "overwrite": False},
        ))
        read = asyncio.run(runtime.execute("read_file", {"path": "hello.txt"}))
        assert json.loads(read.text)["data"]["result"]["content"] == "alpha\nbeta\n"
        asyncio.run(runtime.execute(
            "patch_file",
            {
                "path": "hello.txt",
                "patch": "@@ -1,2 +1,2 @@\n alpha\n-beta\n+gamma\n",
            },
        ))
        final = asyncio.run(runtime.execute("read_file", {"path": "hello.txt"}))
        listed = asyncio.run(runtime.execute("list_files", {"path": "."}))
        assert json.loads(final.text)["data"]["result"]["content"] == "alpha\ngamma\n"
        assert any(item["path"] == "hello.txt" for item in json.loads(listed.text)["data"]["result"]["entries"])
        assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"
        assert "terminal" not in catalog.TOOL_NAMES
    finally:
        if transport is not None:
            asyncio.run(transport.aclose())
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
