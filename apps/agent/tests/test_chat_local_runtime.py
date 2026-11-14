"""Chat to AgentOS Local Runtime boundary tests."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from app.tools.chat_catalog import ChatToolCatalog
from app.tools.local_runtime import LocalRuntimeToolError, LocalRuntimeToolExecutor
from app.tools.runtime import SDK_TOOLS, ToolInvocationContext
from app.tools.permissions import ApprovalDecision, ChatPermissionService
from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeExecutionError,
    LocalRuntimeExecutionLimits,
    LocalRuntimeExecutionResult,
)
from components.resource.application.resource_plane import ResourcePlane
from contracts.resource import Placement, RuntimeKind, RuntimeProfile


def test_chat_composition_uses_the_authenticated_users_current_workspace(monkeypatch):
    from app.security import internal_auth
    from app.tools import runtime as tool_runtime
    template = _executor()
    actor = SimpleNamespace(user_id='current-user')
    selected = LocalRuntimeAuthorizationRef(grantId='selected-grant', workspaceId='selected-workspace')

    def resolve_current(current):
        assert current is actor
        return selected

    execution = SimpleNamespace(local_runtime_client=template.client,
        resource_plane=template.resource_plane, local_runtime_resource=SimpleNamespace(
            profile=SimpleNamespace(runtime_id=template.resource_id)),
        local_runtime_health_projector=template.health_projector,
        local_runtime_transport=template.health_transport,
        local_runtime_authorization=template.authorization,
        workspace_authority=SimpleNamespace(resolve_current=resolve_current))
    monkeypatch.setattr(internal_auth, 'current_trusted_user', lambda: actor)
    monkeypatch.setattr(tool_runtime, '_chat_runtime', None)
    catalog = tool_runtime.configure_chat_tool_runtime(execution).catalog
    catalog.permission_service = None
    asyncio.run(catalog.execute('read_file', {'path': 'note.txt'}, call_id='current-workspace'))
    assert template.client.calls[0][1]['authorization'] == selected
    assert catalog._local_runtime_executor.authorization == template.authorization


@pytest.mark.asyncio
async def test_background_command_reuses_approved_execution_and_enforces_output_ownership(monkeypatch):
    monkeypatch.setattr(settings, 'TOOL_RUNTIME_ENABLED', True)
    release = asyncio.Event()
    class Client(_ShellClient):
        async def stream_events(self, **kwargs):
            yield SimpleNamespace(event_type='stdout_delta', data={'delta': 'first output'})
            await release.wait()
            yield SimpleNamespace(event_type='completed', data={'exitCode': 7})
    client = Client()
    executor = _executor(client=client)
    executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
    events = []
    async def sink(name, data):
        events.append(name)
    catalog = ChatToolCatalog(local_runtime_executor=executor, legacy_terminal_enabled=False)
    running = await catalog.execute('run_command', {'command': 'synthetic', 'yield_time_ms': 0},
        call_id='background-one', session_id='session', request_id='request', permission_event_sink=sink)
    assert running.data['status'] == 'running'
    identity = running.data['executionId']
    partial = await catalog.execute('get_command_output', {'execution_id': identity}, session_id='session')
    assert partial.data['terminal']['stdout'] == 'first output'
    with pytest.raises(ValueError, match='COMMAND_JOB_UNKNOWN'):
        await catalog.execute('get_command_output', {'execution_id': identity}, session_id='other-session')
    with pytest.raises(ValueError, match='COMMAND_CURSOR_INVALID'):
        await catalog.execute('get_command_output', {'execution_id': identity, 'after': 9999}, session_id='session')
    catalog.detach_commands('request')
    previous_events = len(events)
    release.set()
    final = await catalog.execute('get_command_output', {'execution_id': identity,
        'after': partial.data['outputCursor'], 'wait_ms': 1000}, session_id='session')
    assert final.data['status'] == 'completed'
    assert final.data['terminal']['exitCode'] == 7
    assert len(client.calls) == 1
    assert len(events) == previous_events
    assert client.calls[0][0].input['securityProfile'] == 'host_approved'


@pytest.mark.asyncio
async def test_background_command_denial_and_invalid_wait_never_start_execution(monkeypatch):
    monkeypatch.setattr(settings, 'TOOL_RUNTIME_ENABLED', True)
    executor = _executor(client=_ShellClient())
    executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
    async def deny(**kwargs):
        raise PermissionError('denied')
    catalog = ChatToolCatalog(local_runtime_executor=executor, legacy_terminal_enabled=False,
        permission_service=SimpleNamespace(authorize=deny))
    with pytest.raises(PermissionError):
        await catalog.execute('run_command', {'command': 'synthetic', 'yield_time_ms': 0}, call_id='denied', session_id='session')
    assert executor.client.calls == []
    catalog.permission_service = None
    with pytest.raises(ValueError, match='COMMAND_WAIT_INVALID'):
        await catalog.execute('run_command', {'command': 'synthetic', 'yield_time_ms': float('nan')}, call_id='invalid', session_id='session')
    assert executor.client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_tool', [True, False])
async def test_command_cancellation_reaches_the_original_runtime_and_closes_waiters(monkeypatch, cancel_tool):
    monkeypatch.setattr(settings, 'TOOL_RUNTIME_ENABLED', True)
    release, accepted = asyncio.Event(), asyncio.Event()
    class Client(_ShellClient):
        async def stream_events(self, **kwargs):
            accepted.set()
            await release.wait()
            yield SimpleNamespace(event_type='cancelled', data={})
        async def cancel(self, **kwargs):
            self.cancel_calls.append(kwargs)
            release.set()
            return 'cancelling'
    client = Client()
    executor = _executor(client=client)
    executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
    catalog = ChatToolCatalog(local_runtime_executor=executor, legacy_terminal_enabled=False)
    running = asyncio.create_task(catalog.execute('run_command', {'command': 'synthetic',
        'yield_time_ms': 0 if cancel_tool else 10000}, call_id='cancel-me', session_id='session', request_id='request'))
    await accepted.wait()
    if cancel_tool:
        handle = await running
        cancelled = await catalog.execute('cancel_command', {'execution_id': handle.data['executionId']}, session_id='session')
        assert cancelled.data['status'] == 'cancelled'
    else:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert len(client.calls) == 1
    assert client.cancel_calls[0]['execution_id'] == 'execution-1'
    assert executor._active == {}


def test_dynamic_workspace_is_pinned_before_permission_wait():
    first_client, second_client = _Client(), _Client()
    first, second = _executor(client=first_client), _executor(client=second_client)
    second.authorization = LocalRuntimeAuthorizationRef(grantId="grant-2", workspaceId="workspace-2")
    selected = [first]
    approval_scopes = []

    async def approve(**kwargs):
        approval_scopes.append(kwargs["workspace_id"])
        selected[0] = second

    catalog = ChatToolCatalog(local_runtime_executor=first,
        permission_service=SimpleNamespace(authorize=approve),
        workspace_executor_factory=lambda: selected[0], legacy_terminal_enabled=False)

    async def scenario():
        await catalog.execute("read_file", {"path": "note.txt"}, call_id="dynamic-1")
        await catalog.execute("read_file", {"path": "note.txt"}, call_id="dynamic-2")

    asyncio.run(scenario())
    assert approval_scopes == ["workspace-1", "workspace-2"]
    assert first_client.calls[0][1]["authorization"].workspace_id == "workspace-1"
    assert second_client.calls[0][1]["authorization"].workspace_id == "workspace-2"


class _HealthProjector:
    def __init__(self, healthy=True):
        self.healthy = healthy
        self.calls = 0

    async def refresh(self, _transport):
        self.calls += 1
        return self.healthy


_FILE_CAPABILITIES = ("fs.read", "fs.list", "fs.write", "fs.patch")


def _resource_plane(capabilities=_FILE_CAPABILITIES) -> ResourcePlane:
    plane = ResourcePlane()
    plane.ensure_node("node:device:chat", placement=Placement.DEVICE)
    plane.register_runtime(RuntimeProfile(
        runtimeId="runtime-1",
        kind=RuntimeKind.EXECUTION_BACKEND,
        nodeId="node:device:chat",
        placement=Placement.DEVICE,
        capabilities=list(capabilities),
    ))
    plane.heartbeat_runtime("runtime-1")
    return plane


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






class _ShellClient:
    def __init__(self):
        self.calls = []
        self.cancel_calls = []

    async def execute(self, invocation, **kwargs):
        self.calls.append((invocation, kwargs))
        return LocalRuntimeExecutionResult(
            requestId="runtime-request-1",
            invocationId=invocation.invocation_id,
            status="accepted",
            output={"executionId": "execution-1", "state": "running"},
            startedAt=datetime.now(timezone.utc),
            completedAt=datetime.now(timezone.utc),
        )

    async def stream_events(self, **_kwargs):
        for event_type, data in (
            ("started", {}),
            ("stdout_delta", {"delta": "hello\n", "bytes": 6}),
            ("stderr_delta", {"delta": "", "bytes": 0}),
            ("completed", {"exitCode": 0}),
        ):
            yield SimpleNamespace(
                event_type=event_type,
                data=data,
            )

    async def cancel(self, **kwargs):
        self.cancel_calls.append(kwargs)
        return "cancelling"


def _executor(*, healthy=True, candidate=True, client=None):
    return LocalRuntimeToolExecutor(
        resource_plane=(_resource_plane() if candidate else ResourcePlane()),
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


def test_chat_catalog_only_advertises_runtime_granted_file_capabilities(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    plane = _resource_plane(("fs.read", "fs.list"))
    executor = LocalRuntimeToolExecutor(
        resource_plane=plane,
        client=_Client(),
        health_projector=_HealthProjector(),
        health_transport=object(),
        resource_id="runtime-1",
        authorization=LocalRuntimeAuthorizationRef(
            grantId="grant-1", workspaceId="workspace-1"
        ),
    )
    catalog = ChatToolCatalog(local_runtime_executor=executor, legacy_terminal_enabled=False)

    assert "read_file" in catalog.TOOL_NAMES
    assert "list_files" in catalog.TOOL_NAMES
    assert "write_file" not in catalog.TOOL_NAMES
    assert "patch_file" not in catalog.TOOL_NAMES
    assert catalog.availability()["write_file"]["available"] is False
    assert catalog.availability()["patch_file"]["available"] is False


def test_command_timeout_receipt_is_not_reported_as_a_crash():
    class TimeoutClient(_ShellClient):
        async def stream_events(self, **kwargs):
            yield SimpleNamespace(event_type='failed', data={'exitCode': 1, 'timedOut': True})
    executor = _executor(client=TimeoutClient())
    executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
    with pytest.raises(LocalRuntimeToolError) as error:
        asyncio.run(executor.execute('run_command', {'command': 'sleep', 'timeout': 900},
            call_id='timeout', request_id='request'))
    assert error.value.code == 'COMMAND_TIMEOUT'
    assert error.value.terminal['timedOut'] is True
    assert error.value.terminal['terminationReason'] == 'timeout'
    assert '900s' in str(error.value)
    assert error.value.terminal['effectiveTimeoutSeconds'] is None
    assert error.value.terminal['timeoutConfirmed'] is False
    assert 'effective deadline was not reported' in str(error.value)


def test_timeout_in_immediate_failed_receipt_keeps_termination_details():
    class Client(_ShellClient):
        async def execute(self, invocation, **kwargs):
            return LocalRuntimeExecutionResult(requestId='r', invocationId=invocation.invocation_id,
                status='failed', output={'exitCode': 1, 'timedOut': True, 'stderr': 'partial output'},
                error={'code': 'EXECUTION_TIMEOUT', 'message': 'deadline', 'retryable': False},
                startedAt=datetime.now(timezone.utc), completedAt=datetime.now(timezone.utc))
    executor = _executor(client=Client())
    executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
    with pytest.raises(LocalRuntimeToolError) as error:
        asyncio.run(executor.execute('run_command', {'command': 'sleep', 'timeout': 0.1}, call_id='fast'))
    assert error.value.code == 'COMMAND_TIMEOUT'
    assert error.value.terminal['timedOut'] is True
    assert error.value.terminal['stderr'] == 'partial output'
    assert error.value.terminal['effectiveTimeoutSeconds'] is None
    assert error.value.terminal['requestedTimeoutSeconds'] == 0.1


@pytest.mark.parametrize('immediate', [False, True])
def test_actual_deadline_from_receipt_overrides_requested_budget(immediate):
    receipt = {'exitCode': 1, 'timedOut': True, 'effectiveTimeoutSeconds': 600,
        'timeoutSource': 'backend_policy', 'terminationMessage': 'stale deadline (1800s)'}
    class Client(_ShellClient):
        async def execute(self, invocation, **kwargs):
            if not immediate:
                return await super().execute(invocation, **kwargs)
            return LocalRuntimeExecutionResult(requestId='r', invocationId=invocation.invocation_id,
                status='failed', output=receipt, error={'code': 'COMMAND_TIMEOUT', 'message': 'timeout', 'retryable': False},
                startedAt=datetime.now(timezone.utc), completedAt=datetime.now(timezone.utc))
        async def stream_events(self, **kwargs):
            yield SimpleNamespace(event_type='failed', data=receipt)
    executor = _executor(client=Client())
    executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
    with pytest.raises(LocalRuntimeToolError) as error:
        asyncio.run(executor.execute('run_command', {'command': 'sleep', 'timeout': 1800}, call_id='actual'))
    terminal = error.value.terminal
    assert terminal['requestedTimeoutSeconds'] == 1800
    assert terminal['effectiveTimeoutSeconds'] == 600
    assert terminal['timeoutConfirmed'] is True
    assert terminal['timeoutSource'] == 'backend_policy'
    assert 'backend deadline (600s)' in str(error.value)
    assert 'requested 1800s' in str(error.value)


@pytest.mark.parametrize('timeout', [True, 0, -1, float('nan'), float('inf'), '900', 'invalid'])
def test_invalid_command_timeout_is_rejected_before_execution(timeout):
    client = _ShellClient()
    executor = _executor(client=client)
    executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
    with pytest.raises(LocalRuntimeToolError) as error:
        asyncio.run(executor.execute('run_command', {'command': 'echo', 'timeout': timeout}, call_id='bad'))
    assert error.value.code == 'COMMAND_TIMEOUT_INVALID'
    assert client.calls == []


@pytest.mark.asyncio
async def test_timeout_over_real_hands_http_terminates_process(monkeypatch, tmp_path):
    """Chat invocation -> job -> envelope -> signed HTTP -> real PowerShell -> receipt."""
    import json
    import shutil
    import subprocess
    import time
    from pathlib import Path
    from adapters.hands_http import HandsHttpTransport
    from adapters.local_runtime import LocalRuntimeClient
    hands = Path(__file__).resolve().parents[2] / 'agentOS' / 'src' / 'hands'
    node = shutil.which('node')
    tsx = hands / 'node_modules' / 'tsx' / 'dist' / 'cli.mjs'
    if not node or not tsx.exists() or not shutil.which('pwsh'):
        pytest.skip('real Hands test requires Node, local tsx and PowerShell')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (tmp_path / 'keys.json').write_text(json.dumps({'credentials': [
        {'credentialId': 'timeout-test', 'secret': 'isolated-timeout-test-secret'}]}))
    (tmp_path / 'grants.json').write_text(json.dumps({'grants': [{
        'grantId': 'grant-1', 'workspaceId': 'workspace-1', 'canonicalRoot': str(workspace.resolve()),
        'capabilities': ['shell.exec'], 'allowedCallers': ['timeout-test']}]}))
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'workspaceRoot': str(workspace), 'credentialsFile': 'keys.json',
        'grantsFile': 'grants.json', 'dataDir': 'ledger', 'port': 0}))
    # Import tsx in this process: its CLI may fork, leaving a service behind
    # when Windows terminates only the launcher during fixture cleanup.
    process = subprocess.Popen([node, '--import', 'tsx', 'hands/service-main.ts', '--config', str(config)],
        cwd=hands, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    transport = None
    try:
        ready = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 30)
        assert ready.startswith('READY '), ready
        address = json.loads(ready[6:])
        transport = HandsHttpTransport(resource_id='runtime-1',
            address=f"http://127.0.0.1:{address['port']}/v1/executions",
            credential_provider=SimpleNamespace(current_signing_credential=lambda _: (
                'timeout-test', 'isolated-timeout-test-secret')))
        executor = _executor(client=LocalRuntimeClient(transport))
        executor.resource_plane = _resource_plane((*_FILE_CAPABILITIES, 'shell.exec'))
        monkeypatch.setattr(settings, 'TOOL_RUNTIME_ENABLED', True)
        context = ToolInvocationContext(ChatToolCatalog(local_runtime_executor=executor,
            legacy_terminal_enabled=False), frozenset({'run_command', 'get_command_output'}))
        started = time.monotonic()
        response = json.loads(await context.invoke('run_command', {'command':
            "Start-Sleep -Seconds 8; Set-Content should-not-exist.txt late", 'timeout': 0.5,
            'yield_time_ms': 0}, call_id='real-timeout'))
        assert response['ok'], response
        result = response['data']
        # Polling for output must not disable the process deadline.
        assert result['status'] == 'running', result
        while result['status'] == 'running':
            assert time.monotonic() - started < 7, result
            response = json.loads(await context.invoke('get_command_output', {
                'execution_id': result['executionId'], 'after': result['outputCursor'], 'wait_ms': 1000},
                call_id='poll'))
            assert response['ok'], response
            result = response['data']
        assert result['status'] == 'failed', result
        assert result['errorCode'] == 'COMMAND_TIMEOUT', result
        assert result['terminal']['timedOut'] is True
        assert result['terminal']['effectiveTimeoutSeconds'] == 0.5
        assert result['terminal']['terminationReason'] == 'timeout'
        assert not (workspace / 'should-not-exist.txt').exists()
        record = await transport.query_execution(result['executionId'])
        assert record['receipt']['output']['timedOut'] is True
        assert record['receipt']['output']['effectiveTimeoutSeconds'] == 0.5
        # A long requested budget must survive resource resolution unchanged.
        completed = await executor.execute('run_command', {'command': 'Write-Output long-budget-ok',
            'timeout': 1800}, call_id='long-budget-http', request_id='long-budget-http')
        terminal = completed.data['terminal']
        assert terminal['requestedTimeoutSeconds'] == 1800
        assert terminal['effectiveTimeoutSeconds'] == 1800
        assert terminal['timeoutConfirmed'] is True
        assert terminal['exitCode'] == 0
    finally:
        if transport:
            await transport.aclose()
        process.terminate()
        await asyncio.to_thread(process.wait, timeout=10)


def test_run_command_uses_host_approved_local_runtime_and_streams_events(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
    plane = _resource_plane((*_FILE_CAPABILITIES, "shell.exec"))
    client = _ShellClient()
    executor = LocalRuntimeToolExecutor(
        resource_plane=plane,
        client=client,
        health_projector=_HealthProjector(),
        health_transport=object(),
        resource_id="runtime-1",
        authorization=LocalRuntimeAuthorizationRef(grantId="grant-1", workspaceId="workspace-1"),
        limits=LocalRuntimeExecutionLimits(timeoutSeconds=10, maxStdoutBytes=1024, maxStderrBytes=1024),
    )
    catalog = ChatToolCatalog(local_runtime_executor=executor, legacy_terminal_enabled=False)
    assert "run_command" in catalog.TOOL_NAMES
    assert catalog.availability()["run_command"]["capabilityId"] == "shell.exec"
    schema = set(SDK_TOOLS["run_command"].params_json_schema.get("properties", {}))
    assert schema.isdisjoint({"securityProfile", "grantId", "workspaceId", "resourceId", "allowedRoot"})

    events = []

    async def sink(event_type, payload):
        events.append((event_type, payload))

    result = asyncio.run(executor.execute(
        "run_command",
        {"mode": "shell", "command": "echo hello", "cwd": "."},
        call_id="call-shell",
        request_id="chat-request",
        event_sink=sink,
    ))

    invocation, request = client.calls[0]
    assert invocation.capability_id == "shell.exec"
    assert invocation.input["securityProfile"] == "host_approved"
    assert "grantId" not in invocation.input
    assert request["authorization"].grant_id == "grant-1"
    assert result.data["terminal"]["stdout"] == "hello\n"
    assert [event[0] for event in events] == [
        "execution_started", "stdout_delta", "stderr_delta", "execution_completed"
    ]

    # The model may emit optional fields as null; null timeout must not fail.
    asyncio.run(executor.execute(
        "run_command",
        {"mode": "shell", "command": "echo hello", "cwd": ".", "timeout": None},
        call_id="call-shell-null-timeout",
        request_id="chat-request-null-timeout",
        event_sink=sink,
    ))
    assert "timeout" not in client.calls[1][0].input
    assert request['limits'].timeout_seconds is None
    assert client.calls[1][1]['limits'].timeout_seconds is None
    asyncio.run(executor.execute('run_command', {'command': 'echo hello', 'timeout': 900},
        call_id='long-budget', request_id='chat-request', event_sink=sink))
    assert client.calls[2][1]['limits'].timeout_seconds == 900
    assert 'timeout' not in client.calls[2][0].input
    context = ToolInvocationContext(catalog, frozenset({'run_command'}))
    assert context.invocation_timeout('run_command') is None
    assert context.sdk_tools()[0].timeout_seconds is None

    with pytest.raises(LocalRuntimeToolError, match="system-controlled"):
        asyncio.run(executor.execute(
            "run_command",
            {"mode": "shell", "command": "echo blocked", "cwd": ".", "securityProfile": "isolated_workspace"},
            call_id="call-forbidden",
        ))


def test_run_command_permission_is_one_time_and_exposes_no_host_authority(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "TOOL_RUNTIME_ENABLED", True)
        plane = _resource_plane((*_FILE_CAPABILITIES, "shell.exec"))
        executor = LocalRuntimeToolExecutor(
            resource_plane=plane,
            client=_ShellClient(),
            health_projector=_HealthProjector(),
            health_transport=object(),
            resource_id="runtime-1",
            authorization=LocalRuntimeAuthorizationRef(grantId="grant-1", workspaceId="workspace-1"),
        )
        permission = ChatPermissionService()
        catalog = ChatToolCatalog(
            local_runtime_executor=executor,
            legacy_terminal_enabled=False,
            permission_service=permission,
        )
        queue = asyncio.Queue()
        context = ToolInvocationContext(
            catalog,
            frozenset({"run_command"}),
            session_id="chat-session",
            request_id="chat-request",
            permission_event_queue=queue,
        )
        task = asyncio.create_task(context.invoke(
            "run_command",
            {"mode": "shell", "command": "echo approved", "cwd": "."},
            call_id="call-shell",
        ))
        event, payload = await queue.get()
        assert event == "approval_required"
        approval = payload["approval"]
        assert approval["capabilityId"] == "shell.exec"
        assert approval["operation"] == "Run command"
        assert approval["riskNotice"]
        assert "grantId" not in approval and "resourceId" not in approval
        await permission.resolve(
            approval["approvalId"],
            decision=ApprovalDecision.ALLOW_ONCE,
            session_id="chat-session",
            invocation_id="call-shell",
            capability_id="shell.exec",
            relative_path=".",
        )
        await task

    asyncio.run(scenario())
