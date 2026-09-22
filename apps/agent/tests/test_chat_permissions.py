import asyncio
from types import SimpleNamespace

import pytest

from app.api import chat
from app.tools.chat_catalog import ChatToolCatalog
from app.tools.contracts import ToolPayload
from app.tools.permissions import (
    ApprovalDecision,
    ApprovalResolutionError,
    ChatPermissionService,
    PermissionDeniedError,
    PermissionPolicy,
    PermissionScope,
    SessionPermissionStore,
)
from app.tools.runtime import ToolInvocationContext
from app.tools.runtime import AgentsToolRuntime
from app.llm.chat_stream import ChatStreamEventType
import app.tools.runtime as runtime_module


class _Executor:
    def __init__(self):
        self.authorization = SimpleNamespace(workspace_id="workspace-main")
        self.calls = []

    async def execute(self, name, arguments, *, call_id):
        self.calls.append((name, dict(arguments), call_id))
        return ToolPayload(summary=f"executed {name}", data={})


def _catalog(service, executor):
    return ChatToolCatalog(
        local_runtime_executor=executor,
        permission_service=service,
        legacy_terminal_enabled=False,
    )


def test_policy_defaults_read_list_and_asks_for_mutations():
    policy = PermissionPolicy()
    grants = SessionPermissionStore()
    assert policy.evaluate(
        PermissionScope(capability_id="fs.read", workspace_id="workspace", relative_path="a.txt"),
        session_id="session",
        session_grants=grants,
    ).value == "allow"
    assert policy.evaluate(
        PermissionScope(capability_id="fs.list", workspace_id="workspace", relative_path="."),
        session_id="session",
        session_grants=grants,
    ).value == "allow"
    assert policy.evaluate(
        PermissionScope(capability_id="fs.write", workspace_id="workspace", relative_path="a.txt"),
        session_id="session",
        session_grants=grants,
    ).value == "ask"
    assert policy.evaluate(
        PermissionScope(capability_id="shell.exec", workspace_id="workspace", relative_path="."),
        session_id="session",
        session_grants=grants,
    ).value == "ask"


def test_ask_suspends_original_call_and_allow_once_preserves_call_id():
    async def scenario():
        service = ChatPermissionService()
        executor = _Executor()
        queue = asyncio.Queue()
        context = ToolInvocationContext(
            _catalog(service, executor),
            frozenset({"write_file"}),
            session_id="session-1",
            permission_event_queue=queue,
        )
        task = asyncio.create_task(
            context.invoke("write_file", {"path": "hello.txt", "content": "A"}, call_id="call-1")
        )
        event, payload = await asyncio.wait_for(queue.get(), timeout=1)
        assert event == "approval_required"
        approval = payload["approval"]
        assert not executor.calls
        assert "workspace-main" not in str(approval)
        assert "allowedRoot" not in str(approval)

        await service.resolve(
            approval["approvalId"],
            decision=ApprovalDecision.ALLOW_ONCE,
            session_id="session-1",
            invocation_id="call-1",
            capability_id="fs.write",
            relative_path="hello.txt",
        )
        resolved_event, resolved_payload = await asyncio.wait_for(queue.get(), timeout=1)
        assert resolved_event == "approval_resolved"
        assert resolved_payload["approval"]["status"] == "approved"
        await task
        assert executor.calls == [("write_file", {"path": "hello.txt", "content": "A"}, "call-1")]

    asyncio.run(scenario())


def test_allow_session_is_ephemeral_and_exactly_scoped():
    async def scenario():
        service = ChatPermissionService()
        executor = _Executor()
        queue = asyncio.Queue()
        catalog = _catalog(service, executor)
        first = ToolInvocationContext(
            catalog,
            frozenset({"write_file"}),
            session_id="session-1",
            permission_event_queue=queue,
        )
        task = asyncio.create_task(
            first.invoke("write_file", {"path": "hello.txt", "content": "A"}, call_id="call-1")
        )
        _, payload = await asyncio.wait_for(queue.get(), timeout=1)
        await service.resolve(
            payload["approval"]["approvalId"],
            decision=ApprovalDecision.ALLOW_SESSION,
            session_id="session-1",
        )
        await asyncio.wait_for(queue.get(), timeout=1)
        await task

        second = ToolInvocationContext(catalog, frozenset({"write_file"}), session_id="session-1")
        await asyncio.wait_for(
            second.invoke("write_file", {"path": "hello.txt", "content": "B"}, call_id="call-2"),
            timeout=1,
        )
        assert len(executor.calls) == 2

        third = ToolInvocationContext(
            catalog,
            frozenset({"write_file"}),
            session_id="session-1",
            permission_event_queue=queue,
        )
        blocked = asyncio.create_task(
            third.invoke("write_file", {"path": "other.txt", "content": "C"}, call_id="call-3")
        )
        _, other_payload = await asyncio.wait_for(queue.get(), timeout=1)
        assert other_payload["approval"]["relativePath"] == "other.txt"
        await service.resolve(
            other_payload["approval"]["approvalId"],
            decision=ApprovalDecision.DENY,
            session_id="session-1",
        )
        await asyncio.wait_for(queue.get(), timeout=1)
        await asyncio.wait_for(blocked, timeout=1)
        assert len(executor.calls) == 2

    asyncio.run(scenario())


def test_wrong_session_or_replayed_approval_is_rejected_before_execution():
    async def scenario():
        service = ChatPermissionService()
        executor = _Executor()
        queue = asyncio.Queue()
        context = ToolInvocationContext(
            _catalog(service, executor),
            frozenset({"write_file"}),
            session_id="owner",
            permission_event_queue=queue,
        )
        task = asyncio.create_task(
            context.invoke("write_file", {"path": "hello.txt", "content": "A"}, call_id="call-1")
        )
        _, payload = await queue.get()
        approval_id = payload["approval"]["approvalId"]
        with pytest.raises(ApprovalResolutionError, match="another session"):
            await service.resolve(approval_id, decision=ApprovalDecision.ALLOW_ONCE, session_id="other")
        assert not executor.calls
        await service.resolve(approval_id, decision=ApprovalDecision.DENY, session_id="owner")
        await queue.get()
        await task
        with pytest.raises(ApprovalResolutionError, match="already"):
            await service.resolve(approval_id, decision=ApprovalDecision.DENY, session_id="owner")

    asyncio.run(scenario())


def test_approval_ttl_expires_fail_closed_without_reaching_executor():
    async def scenario():
        service = ChatPermissionService(approval_ttl_seconds=0.01)
        executor = _Executor()
        queue = asyncio.Queue()
        context = ToolInvocationContext(
            _catalog(service, executor),
            frozenset({"write_file"}),
            session_id="session-expiry",
            permission_event_queue=queue,
        )
        task = asyncio.create_task(
            context.invoke("write_file", {"path": "expired.txt", "content": "A"}, call_id="call-expiry")
        )
        required_event, required_payload = await queue.get()
        assert required_event == "approval_required"
        await asyncio.sleep(0.03)
        resolved_event, resolved_payload = await asyncio.wait_for(queue.get(), timeout=1)
        assert resolved_event == "approval_resolved"
        assert resolved_payload["approval"]["status"] == "expired"
        result = await task
        assert '"error":"APPROVAL_EXPIRED"' in result
        assert not executor.calls
        assert service.pending(required_payload["approval"]["approvalId"]) is None

    asyncio.run(scenario())


def test_invalid_path_is_denied_before_local_runtime_executor():
    async def scenario():
        service = ChatPermissionService()
        executor = _Executor()
        catalog = _catalog(service, executor)
        context = ToolInvocationContext(catalog, frozenset({"write_file"}), session_id="session")
        result = await context.invoke(
            "write_file",
            {"path": "../outside.txt", "content": "must not be written", "allowedRoot": "C:\\"},
            call_id="call-escape",
        )
        assert '"ok":false' in result
        assert context.records[0].error_code == "PERMISSION_SCOPE_INVALID"
        assert not executor.calls

    asyncio.run(scenario())


def test_approval_endpoint_resolves_pending_request_without_grant_authority(monkeypatch):
    async def scenario():
        service = ChatPermissionService()
        events = []

        async def emit(event_type, payload):
            events.append((event_type, payload))

        pending = asyncio.create_task(
            service.authorize(
                tool_name="write_file",
                arguments={"path": "hello.txt", "content": "A"},
                call_id="call-api",
                session_id="session-api",
                workspace_id="workspace-main",
                emit=emit,
            )
        )
        while not events:
            await asyncio.sleep(0)
        approval = events[0][1]["approval"]
        monkeypatch.setattr(chat, "get_chat_permission_service", lambda: service)
        response = await chat.resolve_chat_approval(
            approval["approvalId"],
            chat.ChatApprovalDecisionRequest(
                decision=ApprovalDecision.ALLOW_ONCE,
                sessionId="session-api",
                invocationId="call-api",
                capabilityId="fs.write",
                relativePath="hello.txt",
            ),
        )
        assert response["decision"] == "allow_once"
        await pending
        assert events[-1][0] == "approval_resolved"

    asyncio.run(scenario())


def test_runtime_stream_emits_approval_events_while_original_tool_waits(monkeypatch):
    async def scenario():
        service = ChatPermissionService()
        executor = _Executor()
        catalog = _catalog(service, executor)
        runtime = AgentsToolRuntime(catalog=catalog, allowed_tools={"write_file"})

        class _Client:
            async def close(self):
                return None

        class _Result:
            def __init__(self, context):
                self.context = context
                self.final_output = ""
                self.context_wrapper = SimpleNamespace(usage=SimpleNamespace())

            async def stream_events(self):
                item = SimpleNamespace(
                    call_id="call-stream",
                    raw_item=SimpleNamespace(name="write_file"),
                )
                yield SimpleNamespace(type="run_item_stream_event", name="tool_called", item=item)
                await self.context.invoke(
                    "write_file",
                    {"path": "stream.txt", "content": "A"},
                    call_id="call-stream",
                )
                yield SimpleNamespace(type="run_item_stream_event", name="tool_output", item=item)

        def fake_run_streamed(agent, items, *, context, max_turns, run_config):
            return _Result(context)

        def fake_build_agent_sync(*args, **kwargs):
            return None, _Client(), {"effectiveModel": "test-model"}

        monkeypatch.setattr(runtime, "_build_agent", fake_build_agent_sync)
        monkeypatch.setattr(runtime_module.Runner, "run_streamed", fake_run_streamed)
        monkeypatch.setattr(
            runtime_module,
            "provider_model_capabilities",
            lambda model, base_url: SimpleNamespace(context_window_tokens=1000),
        )

        events = []
        async for event in runtime.stream(
            "write stream.txt",
            model="test-model",
            base_url="https://example.test/v1",
            api_key="test-key",
            request_id="request-stream",
            session_id="session-stream",
        ):
            events.append(event)
            if event.event is ChatStreamEventType.APPROVAL_REQUIRED:
                approval = event.data["approval"]
                await service.resolve(
                    approval["approvalId"],
                    decision=ApprovalDecision.ALLOW_ONCE,
                    session_id="session-stream",
                    invocation_id="call-stream",
                    capability_id="fs.write",
                    relative_path="stream.txt",
                )

        assert [event.event for event in events] == [
            ChatStreamEventType.TOOL_START,
            ChatStreamEventType.APPROVAL_REQUIRED,
            ChatStreamEventType.APPROVAL_RESOLVED,
            ChatStreamEventType.TOOL_RESULT,
            ChatStreamEventType.USAGE,
            ChatStreamEventType.DONE,
        ]
        assert executor.calls == [("write_file", {"path": "stream.txt", "content": "A"}, "call-stream")]

    asyncio.run(scenario())
