"""Chat to AgentOS Local Runtime boundary tests."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from app.tools.chat_catalog import ChatToolCatalog
from app.tools.local_runtime import LocalRuntimeToolError, LocalRuntimeToolExecutor
from app.tools.runtime import SDK_TOOLS, ToolInvocationContext
from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeExecutionError,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionResult,
)
from contracts.resource import DeploymentTier, ResourceType


class _HealthProjector:
    def __init__(self, healthy=True):
        self.healthy = healthy
        self.calls = 0

    async def refresh(self, _transport):
        self.calls += 1
        return self.healthy


class _ResourceService:
    def __init__(self, *, candidate=True):
        self.candidate = candidate
        self.calls = []

    def candidates(self, capabilities):
        self.calls.append(list(capabilities))
        if not self.candidate:
            return []
        return [SimpleNamespace(profile=SimpleNamespace(
            resource_id="runtime-1",
            resource_type=ResourceType.WORKER,
            deployment_tier=DeploymentTier.TERMINAL,
            capabilities=["fs.read", "fs.list", "fs.write", "fs.patch"],
        ))]


class _Client:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def execute(self, invocation, **kwargs):
        self.calls.append((invocation, kwargs))
        return self.result or LocalRuntimeExecutionResult(
            requestId="request-1",
            invocationId=invocation.invocation_id,
            status="completed",
            output={"path": invocation.input.get("path", "."), "content": "alpha"},
            startedAt=datetime.now(timezone.utc),
            completedAt=datetime.now(timezone.utc),
        )


def _executor(*, healthy=True, candidate=True, client=None):
    return LocalRuntimeToolExecutor(
        resource_service=_ResourceService(candidate=candidate),
        client=client or _Client(),
        health_projector=_HealthProjector(healthy=healthy),
        health_transport=object(),
        resource_id="runtime-1",
        authorization=LocalRuntimeAuthorizationRef(
            grantId="grant-1", workspaceId="workspace-1"
        ),
        limits=LocalRuntimeExecutionLimits(
            timeoutSeconds=10, maxStdoutBytes=1024, maxStderrBytes=1024
        ),
    )


def test_chat_file_tool_uses_capability_invocation_and_trusted_binding(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    client = _Client()
    executor = _executor(client=client)
    catalog = ChatToolCatalog(
        local_runtime_executor=executor,
        legacy_terminal_enabled=False,
    )
    context = ToolInvocationContext(catalog, frozenset({"read_file"}))

    result = asyncio.run(context.invoke(
        "read_file",
        {"path": "docs/hello.txt", "grantId": "model-must-not-bind"},
        call_id="call-1",
    ))

    assert '"ok":true' in result
    invocation, request = client.calls[0]
    assert invocation.invocation_id == "call-1"
    assert invocation.capability_id == "fs.read"
    assert invocation.input == {"path": "docs/hello.txt"}
    assert request["resource_id"] == "runtime-1"
    assert request["authorization"].grant_id == "grant-1"
    assert request["idempotency_key"] == "chat:call-1"
    assert context.records[0].activity["relativePath"] == "docs/hello.txt"
    forbidden = {"grantId", "workspaceId", "resourceId", "endpoint", "credential", "allowedRoot", "allowedPaths"}
    for tool_name in ("read_file", "list_files", "write_file", "patch_file"):
        properties = set(SDK_TOOLS[tool_name].params_json_schema.get("properties", {}))
        assert properties.isdisjoint(forbidden)


def test_same_chat_call_id_reuses_stable_idempotency_key(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    client = _Client()
    executor = _executor(client=client)

    asyncio.run(executor.execute("write_file", {"path": "a.txt", "content": "A", "overwrite": False}, call_id="call-1"))
    asyncio.run(executor.execute("write_file", {"path": "a.txt", "content": "A", "overwrite": False}, call_id="call-1"))
    asyncio.run(executor.execute("write_file", {"path": "a.txt", "content": "B", "overwrite": False}, call_id="call-2"))

    assert [item[1]["idempotency_key"] for item in client.calls] == [
        "chat:call-1", "chat:call-1", "chat:call-2"
    ]


def test_unhealthy_or_unselected_resource_fails_closed_without_client_call(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    unhealthy_client = _Client()
    with pytest.raises(LocalRuntimeToolError) as unhealthy:
        asyncio.run(_executor(healthy=False, client=unhealthy_client).execute(
            "read_file", {"path": "a.txt"}, call_id="call-1"
        ))
    assert getattr(unhealthy.value, "code") == "LOCAL_RUNTIME_UNAVAILABLE"
    assert unhealthy_client.calls == []

    unavailable_client = _Client()
    with pytest.raises(LocalRuntimeToolError) as unavailable:
        asyncio.run(_executor(candidate=False, client=unavailable_client).execute(
            "read_file", {"path": "a.txt"}, call_id="call-2"
        ))
    assert getattr(unavailable.value, "code") == "LOCAL_RUNTIME_UNAVAILABLE"
    assert unavailable_client.calls == []


def test_runtime_failure_is_recorded_without_legacy_fallback(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    failure = LocalRuntimeExecutionResult(
        requestId="request-1",
        invocationId="call-1",
        status="failed",
        error=LocalRuntimeExecutionError(
            code="PATH_OUTSIDE_WORKSPACE",
            retryable=False,
            message="target is outside workspace",
        ),
        startedAt=datetime.now(timezone.utc),
        completedAt=datetime.now(timezone.utc),
    )
    executor = _executor(client=_Client(result=failure))
    catalog = ChatToolCatalog(local_runtime_executor=executor, legacy_terminal_enabled=False)
    context = ToolInvocationContext(catalog, frozenset({"read_file"}))

    result = asyncio.run(context.invoke("read_file", {"path": "../secret.txt"}, call_id="call-1"))

    assert '"ok":false' in result
    assert context.records[0].error_code == "PATH_OUTSIDE_WORKSPACE"
    assert "terminal" not in catalog.TOOL_NAMES
    assert "LOCAL_RUNTIME" not in catalog.availability().get("terminal", {}).get("provider", "")


def test_file_tools_are_unavailable_without_runtime_and_never_fallback(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    catalog = ChatToolCatalog(local_runtime_executor=None, legacy_terminal_enabled=False)
    with pytest.raises(LocalRuntimeToolError) as error:
        asyncio.run(catalog.execute("read_file", {"path": "a.txt"}, call_id="call-1"))
    assert getattr(error.value, "code") == "LOCAL_RUNTIME_UNAVAILABLE"
    assert "terminal" not in catalog.TOOL_NAMES
