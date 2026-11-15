"""PR-TOOL-01: real ACG nodes, model Function Calling, signed mock Hands HTTP.

No shell commands run on the host. Only the external Hands service is mocked;
NodeRunner, model adapters, authorization, binder, transport and receipt checks
are the production implementations.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from adapters.agent_tools import AgentToolSession
from adapters.audited_tool_runtime import AuditedToolRuntime, ToolAuthorizationError
from adapters.guarded_model import GuardedModelRuntime
from adapters.guarded_tool import GuardedToolRuntime
from adapters.hands_http import HandsHttpTransport, receipt_checksum
from adapters.model.native import NativeGeneralAgent
from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from adapters.openai_runtime import OpenAICompatibleRuntime
from app.tools.formal_workspace import FormalWorkspaceTools
from app.tools.permissions import ChatPermissionService, PermissionDecision
from components.communicator import CommunicatorService
from components.executor.graph import ACGExecutionState
from components.executor.node_runner import ACGNodeRunner
from components.executor.value_store import SQLiteExecutionValueStore
from components.memory import MemoryService
from components.resource.application.resource_plane import ResourcePlane
from components.resource.contracts.resource_signing import build_resource_signature
from components.resource.runtime.local_runtime import (
    LocalRuntimeHealthProjector, LocalRuntimeResourceConfig, ensure_local_runtime_resource,
)
from components.resource.scheduler.binder import ResourceBinder
from contracts.capability import CapabilityKind, CapabilityManifest
from contracts.local_runtime import LocalRuntimeAuthorizationRef
from contracts.tools import hands_tools
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
from packs.workspace import WorkspaceDeveloper, OUTPUT as WORKSPACE_OUTPUT
from service.agents.base import AgentRunContext, AgentProfile


NAMES = {'fs.read', 'fs.list', 'fs.write', 'fs.patch', 'shell.exec'}
ANSWER = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}


class GeneralAgent(NativeGeneralAgent):
    def __init__(self):
        super().__init__()
        self.profile = AgentProfile(agentName='general', domain='general')


class ResearchAgent(GeneralAgent):
    def __init__(self):
        super().__init__()
        self.profile = AgentProfile(agentName='research', domain='general')


class ModelHTTP:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.requests = []

    async def post_json(self, *, payload, **kwargs):
        self.requests.append(copy.deepcopy(payload))
        turn = next(self.turns)
        if callable(turn):
            turn = turn(payload)
        message = {'role': 'assistant', 'content': json.dumps(turn)}
        reason = 'stop'
        if isinstance(turn, list):
            message = {'role': 'assistant', 'content': None, 'reasoning_content': 'inspect evidence',
                'tool_calls': [{'id': f'call-{i}', 'type': 'function', 'function': {
                    'name': name.replace('.', '__'), 'arguments': arguments if isinstance(arguments, str)
                    else json.dumps(arguments)}} for i, (name, arguments) in enumerate(turn)]}
            reason = 'tool_calls'
        return {'choices': [{'finish_reason': reason, 'message': message}],
                'usage': {'prompt_tokens': 5, 'completion_tokens': 2}}


def model(turns):
    http = ModelHTTP(turns)
    adapter = OpenAICompatibleRuntime(manifest=CapabilityManifest(capabilityId='test-model',
        kind=CapabilityKind.MODEL, displayName='test', provider='test', capabilities=['mock'],
        metadata={'modelCapabilities': {'mock': {'features': {'tools': True}}}}), transport=http)
    registry = ModelCompatibilityRegistry()
    registry.register(adapter)
    return GuardedModelRuntime(delegate=RegisteredModelRuntime(registry=registry, provider='test', model='mock')), http


class Allow:
    def evaluate(self, *args, **kwargs):
        return PermissionDecision.ALLOW


class Deny:
    def evaluate(self, *args, **kwargs):
        return PermissionDecision.DENY


class HandsService:
    def __init__(self):
        self.requests = []
        self.files = {}
        self.nonces = set()
        self.bad_receipt = False
        self.failed = False
        self.started = asyncio.Event()
        self.release = None
        self.peak_slots = 0
        self.stack = None
        self.ledger = {}
        self.execution_count = 0

    async def __call__(self, incoming):
        if incoming.url.path == '/v1/health':
            return httpx.Response(200, json={'ok': True, 'capabilities': sorted(NAMES)})
        headers = incoming.headers
        signature = build_resource_signature('test-secret', method=incoming.method, path=incoming.url.raw_path.decode(),
            timestamp=int(headers['x-resource-timestamp']), nonce=headers['x-resource-nonce'], body=incoming.content)
        assert headers['x-resource-signature'] == signature
        assert headers['x-resource-nonce'] not in self.nonces
        self.nonces.add(headers['x-resource-nonce'])
        if incoming.method == 'GET':
            return httpx.Response(200, json={'events': []})
        wire = json.loads(incoming.content)
        self.requests.append(wire)
        self.peak_slots = max(self.peak_slots, self.stack.resource_binder.coordinator.active_slots('hands'))
        self.started.set()
        if self.release:
            await self.release.wait()
        scope = wire['authorization']
        if scope['grantId'] != 'grant-' + scope['workspaceId']:
            return httpx.Response(403, json={'error': {'code': 'GRANT_REJECTED'}})
        digest = json.dumps(wire, sort_keys=True)
        if wire['idempotencyKey'] in self.ledger:
            previous_digest, previous_result = self.ledger[wire['idempotencyKey']]
            if digest != previous_digest:
                return httpx.Response(409, json={'error': {'code': 'IDEMPOTENCY_KEY_CONFLICT'}})
            return httpx.Response(200, json=previous_result)
        self.execution_count += 1
        args, name = wire['input'], wire['capabilityId']
        key = scope['workspaceId'], args.get('path')
        output = {'path': args.get('path')}
        if name == 'fs.read':
            output['text'] = self.files.get(key, 'file evidence')
        elif name == 'fs.list':
            output['entries'] = [{'name': 'note.txt', 'type': 'file', 'target': {'displayPath': 'C:/private/root/note.txt'}}]
        elif name == 'fs.write':
            self.files[key] = args['content']
        elif name == 'fs.patch':
            self.files[key] = self.files.get(key, '').replace(args['oldText'], args['newText'])
        else:
            output = {'exitCode': 0, 'stdout': {'text': 'test passed', 'truncated': False},
                      'workdir': 'C:/private/root', 'executedBy': {'path': 'C:/private/pwsh.exe'}}
        now = datetime.now(timezone.utc).isoformat()
        receipt = {key: wire[key] for key in ('requestId', 'invocationId', 'capabilityId', 'idempotencyKey', 'identity')}
        receipt.update(grantId=scope['grantId'], status='failed' if self.failed else 'completed',
                       startedAt=now, completedAt=now, output=output)
        if self.failed:
            receipt['error'] = {'code': 'CONTROLLED_FAILURE', 'retryable': False, 'message': 'test failure'}
        receipt['checksum'] = 'invalid' if self.bad_receipt else receipt_checksum(receipt)
        result = {'executionId': wire['invocationId'],
            'state': 'FAILED' if self.failed else 'COMPLETED', 'receipt': receipt}
        self.ledger[wire['idempotencyKey']] = digest, result
        return httpx.Response(200, json=result)


@pytest_asyncio.fixture
async def stack(monkeypatch, tmp_path):
    service = HandsService()
    plane = ResourcePlane()
    registered = ensure_local_runtime_resource(plane, LocalRuntimeResourceConfig(resource_id='hands',
        owner_scope='test', execution_endpoint='http://hands.test/v1/executions', capacity=3,
        credential_id='test-credential', credential_secret='test-secret', shell_exec_enabled=True))
    client = httpx.AsyncClient(transport=httpx.MockTransport(service))
    transport = HandsHttpTransport(resource_id='hands', address='http://hands.test/v1/executions',
        credential_provider=plane, client=client)
    runtime = SimpleNamespace(resource_plane=plane, local_runtime_resource=registered,
        local_runtime_transport=transport, local_runtime_health_projector=LocalRuntimeHealthProjector(plane, 'hands'),
        execution_value_store=SQLiteExecutionValueStore(db_path=tmp_path/'values.sqlite3'), resource_binder=ResourceBinder(plane),
        workspace_authority=SimpleNamespace(resolve=lambda run: LocalRuntimeAuthorizationRef(
            workspaceId=run.input.get('workspace', 'one'), grantId='grant-'+run.input.get('workspace', 'one'))))
    service.stack = runtime
    permissions = ChatPermissionService(policy=Allow())
    monkeypatch.setattr('app.tools.formal_workspace.get_chat_permission_service', lambda: permissions)
    tools = AuditedToolRuntime(delegate=GuardedToolRuntime(delegate=FormalWorkspaceTools(runtime, None)), allowed_tools=[])
    yield SimpleNamespace(runtime=runtime, tools=tools, service=service, permissions=permissions)
    await client.aclose()
    runtime.execution_value_store.close()


def node(stack, agent, turns=None, *, workspace='one', run_id=None):
    task = RuntimeMissionRecord(missionId='mission', title='Read evidence and answer')
    run = RuntimeRunRecord(missionId=task.mission_id, workflowId='flow', domain='general', runtimeEngine='acg',
        **({'runId': run_id} if run_id else {}), input={'workspace': workspace})
    output = WORKSPACE_OUTPUT if isinstance(agent, WorkspaceDeveloper) else ANSWER
    step = WorkflowStep(stepId=agent.profile.agent_name, name='read evidence', agentName=agent.profile.agent_name,
        capability='information_extraction', outputSpec=output)
    workflow = WorkflowDefinition(workflowId='flow', name='flow', domain='general', runtimeEngine='acg')
    runtime, http = model(turns or [{'answer': 'direct'}])
    runner = ACGNodeRunner(task=task, run=run, workflow=workflow, steps={step.step_id: step},
        agents={step.step_id: agent}, communicator=CommunicatorService(run_id=run.run_id, mission_id=task.mission_id),
        memory=MemoryService(), value_store=stack.runtime.execution_value_store,
        tool_runtime=stack.tools, model_runtime=runtime,
        capability_descriptors={'information_extraction': agent.capability_catalog.get('information_extraction')
                                if isinstance(agent, NativeGeneralAgent) else None},
        invocation_guard=lambda *_: None)
    state = ACGExecutionState(runId=run.run_id)
    return runner, state, step, http


def context_for(runner, step):
    context = AgentRunContext(task=runner.task, run=runner.run, workflow=runner.workflow, step=step,
        memory=[], modelRuntime=runner.model_runtime, commitId='commit:'+runner.run.run_id+':'+step.step_id,
        attemptId='attempt:'+step.step_id)
    context.tool_runtime = runner.tool_runtime.bind_context(context, lambda: None)
    return context


@pytest.mark.asyncio
@pytest.mark.parametrize('agent_type', [GeneralAgent, ResearchAgent, WorkspaceDeveloper])
async def test_three_agent_types_discover_identical_native_catalog_at_node_boundary(stack, agent_type, monkeypatch):
    original = agent_type()
    original.profile.allowed_tools = []
    expected = hands_tools()
    run_agent = original.run
    async def inspect_and_run(context):
        assert context.tool_runtime.list_tools() == expected
        assert {tool.name for tool in expected} == NAMES
        assert all(context.tool_runtime.describe(tool.name) == tool for tool in expected)
        return await run_agent(context)
    original.run = inspect_and_run
    monkeypatch.setenv('AGENTOS_WORKSPACE_TEST_PYTHON', sys.executable)
    turns = [[('fs.write', {'path': 'sample.py', 'content': 'source'})],
             [('shell.exec', {'runner': 'pytest'})], {'answer': 'catalog matched'}]
    runner, state, step, _ = node(stack, original, turns)
    await runner(step.step_id, state)
    assert len(stack.service.requests) >= 2


@pytest.mark.asyncio
async def test_all_five_tools_use_formal_signed_transport_and_verified_receipts(stack):
    runner, _, step, _ = node(stack, GeneralAgent())
    context = context_for(runner, step)
    calls = [('fs.write', {'path': 'note.txt', 'content': 'before'}),
             ('fs.read', {'path': 'note.txt', 'versioned': True}), ('fs.list', {'path': '.'}),
             ('fs.patch', {'path': 'note.txt', 'oldText': 'before', 'newText': 'after', 'replaceAll': True}),
             ('shell.exec', {'command': 'mock-only command', 'workdir': '.'})]
    for index, (name, arguments) in enumerate(calls):
        result = await context.tool_runtime.execute(name, arguments, operation_key=f'op-{index}')
        assert result.data['status'] == 'completed'
        assert result.as_tool_result().name == name
        assert result.record['stepId'] == step.step_id
        assert result.record['runId'] == runner.run.run_id
        assert result.record['attemptId'] == context.attempt_id
        assert stack.runtime.execution_value_store.get_output(run_id=runner.run.run_id,
            output_ref=result.record['receiptRef'])['checksum'] == result.record['receiptChecksum']
    assert {request['capabilityId'] for request in stack.service.requests} == NAMES
    assert stack.service.files['one', 'note.txt'] == 'after'
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('agent_type', [GeneralAgent, ResearchAgent])
async def test_model_tool_call_result_and_final_agent_output_through_acg_node(stack, agent_type):
    runner, state, step, http = node(stack, agent_type(), [[('fs.read', {'path': 'note.txt'})],
        lambda payload: {'answer': json.loads(payload['messages'][-1]['content'])['output']['content']}])
    result = await runner(step.step_id, state)
    assert stack.runtime.execution_value_store.get_output(run_id=runner.run.run_id,
        output_ref=result['outputRef']) == {'answer': 'file evidence'}
    assert len(http.requests) == 2
    assert {entry['function']['name'] for entry in http.requests[0]['tools']} == {name.replace('.', '__') for name in NAMES}
    messages = http.requests[1]['messages']
    assert messages[-1]['role'] == 'tool'
    assert json.loads(messages[-1]['content'])['output']['content'] == 'file evidence'
    assert messages[-2]['reasoning_content'] == 'inspect evidence'
    assert 'grant-one' not in json.dumps(messages)
    assert len(stack.service.requests) == 1
    # Commit replay must not call the model or execute tools again.
    await runner(step.step_id, state)
    assert len(http.requests) == 2 and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_direct_final_answer_requires_no_tool_execution(stack):
    runner, state, step, http = node(stack, GeneralAgent())
    await runner(step.step_id, state)
    assert len(http.requests) == 1 and stack.service.requests == []


@pytest.mark.asyncio
async def test_native_tool_node_streams_before_committing_and_replays_without_new_requests(stack, monkeypatch):
    from runtime.live_events import RuntimeEventBroker
    broker = RuntimeEventBroker()
    monkeypatch.setattr('adapters.agent_tools.runtime_event_broker', broker)
    monkeypatch.setattr('adapters.model.native.runtime_event_broker', broker)
    runner, state, step, http = node(stack, GeneralAgent(), [[('fs.list', {'path': '.'})], {'answer': 'live answer'}])
    release = asyncio.Event()
    async def stream_json(*, payload, **kwargs):
        raw = await http.post_json(payload=payload, **kwargs)
        message = raw['choices'][0]['message']
        if message.get('tool_calls'):
            yield {'choices': [{'delta': {'reasoning_content': 'PRIVATE'}}]}
            for index, call in enumerate(message['tool_calls']):
                yield {'choices': [{'delta': {'tool_calls': [{'index': index, **call}]}}]}
        else:
            content = message['content']
            split = len(content) // 2
            yield {'choices': [{'delta': {'content': content[:split]}}]}
            await release.wait()
            yield {'choices': [{'delta': {'content': content[split:]}}]}
        yield {'choices': [{'delta': {}, 'finish_reason': raw['choices'][0]['finish_reason']}]}
        yield {'choices': [], 'usage': raw['usage']}
    http.stream_json = stream_json
    queue = asyncio.Queue()
    broker._queues[runner.run.run_id].add(queue)
    task = asyncio.create_task(runner(step.step_id, state))
    events = []
    try:
        while not any(event.event_type == 'model.output.delta' for event in events):
            events.append(await asyncio.wait_for(queue.get(), 3))
        assert not task.done()
        assert len(stack.service.requests) == 1
        assert http.requests[1]['messages'][-2]['reasoning_content'] == 'PRIVATE'
        release.set()
        result = await task
        while not queue.empty():
            events.append(queue.get_nowait())
        assert stack.runtime.execution_value_store.get_output(run_id=runner.run.run_id, output_ref=result['outputRef']) == {'answer': 'live answer'}
        assert 'PRIVATE' not in json.dumps([event.model_dump(mode='json') for event in events])
        await runner(step.step_id, state)
        assert len(http.requests) == 2 and len(stack.service.requests) == 1
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_sequential_turns_and_multiple_calls_preserve_model_order(stack):
    runner, state, step, http = node(stack, GeneralAgent(), [
        [('fs.write', {'path': 'n', 'content': 'a'}), ('fs.list', {'path': '.'})],
        [('fs.patch', {'path': 'n', 'oldText': 'a', 'newText': 'b'})],
        [('fs.read', {'path': 'n'}), ('shell.exec', {'command': 'mock'})], {'answer': 'b'}])
    await runner(step.step_id, state)
    assert [request['capabilityId'] for request in stack.service.requests] == ['fs.write', 'fs.list', 'fs.patch', 'fs.read', 'shell.exec']
    assert json.loads(http.requests[-1]['messages'][-2]['content'])['output']['content'] == 'b'
    serialized = json.dumps(http.requests[-1]['messages'])
    assert all(value not in serialized for value in ['test-secret', 'grant-one', 'private/root', 'receiptChecksum', 'handsReceipt'])


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', ['{bad json', [], {'path': 42}, {'path': 'n', 'grantId': 'forged'}])
async def test_bad_arguments_return_explicit_error_to_model_without_dispatch(stack, arguments):
    runner, state, step, http = node(stack, GeneralAgent(), [[('fs.read', arguments)], {'answer': 'invalid input handled'}])
    await runner(step.step_id, state)
    assert stack.service.requests == []
    assert json.loads(http.requests[1]['messages'][-1]['content'])['error']['code'] == 'TOOL_ARGUMENTS_INVALID'


@pytest.mark.asyncio
async def test_failed_execution_returns_error_and_allows_reasoning(stack):
    stack.service.failed = True
    runner, state, step, http = node(stack, GeneralAgent(), [[('fs.read', {'path': 'n'})], {'answer': 'failure handled'}])
    await runner(step.step_id, state)
    result = json.loads(http.requests[1]['messages'][-1]['content'])
    assert result['status'] == 'failed' and result['error']['code'] == 'CONTROLLED_FAILURE'
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
async def test_action_budget_checks_entire_batch_before_dispatch(stack):
    runner, _, step, http = node(stack, GeneralAgent(), [[('fs.read', {'path': 'n'})],
        [('fs.list', {'path': '.'}), ('fs.read', {'path': 'n'})]])
    session = AgentToolSession(context_for(runner, step), max_actions=2)
    with pytest.raises(RuntimeError, match='budget'):
        await session.generate_json(prompt='read', schema=ANSWER)
    assert len(stack.service.requests) == 1 and len(http.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['../escape', 'C:/private/root', '/etc/passwd'])
async def test_workspace_escape_is_rejected_before_transport(stack, path):
    runner, _, step, _ = node(stack, GeneralAgent())
    context = context_for(runner, step)
    with pytest.raises(RuntimeError):
        await context.tool_runtime.execute('fs.read', {'path': path}, operation_key='invalid')
    assert stack.service.requests == []


@pytest.mark.asyncio
async def test_permission_denial_cannot_dispatch_or_obtain_a_lease(stack):
    stack.permissions.policy = Deny()
    runner, _, step, _ = node(stack, GeneralAgent())
    with pytest.raises(RuntimeError):
        await context_for(runner, step).tool_runtime.execute('shell.exec', {'command': 'mock'}, operation_key='denied')
    assert stack.service.requests == []
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
async def test_unknown_outcome_is_terminal_and_quarantines_resource(stack):
    stack.service.bad_receipt = True
    runner, state, step, http = node(stack, GeneralAgent(), [[('fs.read', {'path': 'n'})], {'answer': 'must not run'}])
    with pytest.raises(RuntimeError, match='settlement'):
        await runner(step.step_id, state)
    assert len(http.requests) == 1
    assert stack.runtime.resource_plane.runtime('hands').enabled is False
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 1


@pytest.mark.asyncio
async def test_three_concurrent_nodes_have_independent_context_grants_and_leases(stack, monkeypatch):
    monkeypatch.setenv('AGENTOS_WORKSPACE_TEST_PYTHON', sys.executable)
    stack.service.release = asyncio.Event()
    triples = [node(stack, kind(), [[('fs.write', {'path': 'same.txt', 'content': kind.__name__})],
        [('shell.exec', {'runner': 'pytest', 'path': '.'})], {'answer': 'ok'}], workspace=str(i), run_id=f'run-{i}')
        for i, kind in enumerate([GeneralAgent, ResearchAgent, WorkspaceDeveloper])]
    tasks = [asyncio.create_task(runner(step.step_id, state)) for runner, state, step, _ in triples]
    await stack.service.started.wait()
    for _ in range(50):
        if len(stack.service.requests) == 3:
            break
        await asyncio.sleep(.01)
    assert len(stack.service.requests) == 3
    assert stack.service.peak_slots == 3
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 3
    stack.service.release.set()
    await asyncio.gather(*tasks)
    assert len({request['identity']['stepId'] for request in stack.service.requests}) == 3
    for request in stack.service.requests:
        run_id = request['identity']['runId']
        expected_workspace = run_id.removeprefix('run-')
        assert request['authorization'] == {'grantId': 'grant-'+expected_workspace, 'workspaceId': expected_workspace}
        assert request['identity']['commitId'] in request['invocationId']
    assert len({request['invocationId'] for request in stack.service.requests}) == len(stack.service.requests)
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
async def test_cancellation_stops_node_before_followup_model_turn(stack):
    runner, state, step, http = node(stack, GeneralAgent(), [[('fs.read', {'path': 'n'})], {'answer': 'never'}])
    started = asyncio.Event()
    async def blocked(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    stack.runtime.local_runtime_transport.execute_with_identity = blocked
    task = asyncio.create_task(runner(step.step_id, state))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(http.requests) == 1
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
async def test_session_deadline_cleans_up_lease_and_stops_model(stack):
    runner, _, step, http = node(stack, GeneralAgent(), [[('fs.read', {'path': 'n'})], {'answer': 'never'}])
    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()
    stack.runtime.local_runtime_transport.execute_with_identity = blocked
    with pytest.raises(TimeoutError):
        await AgentToolSession(context_for(runner, step)).generate_json(prompt='read', schema=ANSWER, timeout_seconds=.05)
    assert len(http.requests) == 1
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


def test_discovery_does_not_remove_legacy_tool_authorization():
    class Delegate:
        list_tools = staticmethod(hands_tools)
    runtime = AuditedToolRuntime(delegate=Delegate(), allowed_tools=['legacy'])
    narrowed = runtime.scoped([])
    assert {tool.name for tool in narrowed.list_tools()} == NAMES
    with pytest.raises(ToolAuthorizationError):
        asyncio.run(narrowed.execute('legacy', {}))
    mutated = narrowed.list_tools()
    mutated[0].parameters['properties'].clear()
    assert narrowed.describe('fs.read').parameters['properties']


@pytest.mark.asyncio
async def test_frozen_skill_manifest_cannot_hide_hands(stack):
    from contracts.compiled_acg import SkillManifest, SkillRule
    runner, state, step, _ = node(stack, GeneralAgent(), [[('fs.read', {'path': 'n'})], {'answer': 'ok'}])
    runner.skill_manifest = SkillManifest(rules=(SkillRule(stepId=step.step_id,
        skillNodeId='old-skill', toolName='legacy-tool'),))
    await runner(step.step_id, state)
    assert stack.service.requests[0]['capabilityId'] == 'fs.read'


@pytest.mark.asyncio
async def test_revoked_execution_permit_stops_conversation_before_hands(stack):
    from runtime.acg_execution import ExecutionRunCancelled
    runner, state, step, http = node(stack, GeneralAgent(), [[('fs.read', {'path': 'n'})], {'answer': 'never'}])
    checks = []
    def guard(*args):
        checks.append(True)
        if len(checks) > 2:
            raise ExecutionRunCancelled('permit revoked')
    runner.invocation_guard = guard
    with pytest.raises(ExecutionRunCancelled):
        await runner(step.step_id, state)
    assert len(http.requests) == 1 and stack.service.requests == []


@pytest.mark.asyncio
async def test_grant_revocation_after_approval_still_blocks_execution(stack):
    runner, _, step, _ = node(stack, GeneralAgent())
    def revoked(run):
        raise PermissionError('grant revoked')
    async def approve_then_revoke(**kwargs):
        stack.runtime.workspace_authority.resolve = revoked
    stack.permissions.authorize = approve_then_revoke
    with pytest.raises(RuntimeError):
        await context_for(runner, step).tool_runtime.execute('fs.read', {'path': 'n'}, operation_key='revoked')
    assert stack.service.requests == []


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_user_approval(stack):
    class Ask:
        def evaluate(self, *args, **kwargs):
            return PermissionDecision.ASK
    stack.permissions.policy = Ask()
    runner, state, step, http = node(stack, GeneralAgent(), [[('shell.exec', {'command': 'mock'})], {'answer': 'never'}])
    task = asyncio.create_task(runner(step.step_id, state))
    for _ in range(50):
        if stack.permissions._pending:
            break
        await asyncio.sleep(.01)
    assert stack.permissions._pending
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not stack.permissions._pending
    assert stack.service.requests == [] and len(http.requests) == 1


@pytest.mark.asyncio
async def test_user_approval_wait_does_not_exhaust_the_model_and_tool_work_budget(stack):
    from app.tools.permissions import ApprovalDecision
    class Ask:
        def evaluate(self, *args, **kwargs):
            return PermissionDecision.ASK
    stack.permissions.policy = Ask()
    runner, _, step, http = node(stack, GeneralAgent(), [[('shell.exec', {'command': 'mock'})], {'answer': 'approved'}])
    session = AgentToolSession(context_for(runner, step))
    task = asyncio.create_task(session.generate_json(prompt='inspect', schema=ANSWER, timeout_seconds=.25))
    for _ in range(100):
        if stack.permissions._pending:
            break
        await asyncio.sleep(.005)
    assert stack.permissions._pending
    approval_id, pending = next(iter(stack.permissions._pending.items()))
    await asyncio.sleep(.35)
    assert not task.done() and not stack.service.requests
    request = pending.request
    await stack.permissions.resolve(approval_id, decision=ApprovalDecision.ALLOW_ONCE,
        session_id=request.session_id, invocation_id=request.invocation_id,
        capability_id=request.capability_id, relative_path=request.relative_path)
    result = await asyncio.wait_for(task, 2)
    assert result.data == {'answer': 'approved'}
    assert len(stack.service.requests) == 1 and len(http.requests) == 2
    assert not stack.runtime.formal_tool_pending


@pytest.mark.asyncio
async def test_cancellation_during_model_generation(stack):
    runner, state, step, http = node(stack, GeneralAgent())
    entered = asyncio.Event()
    async def blocked(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    runner.model_runtime.delegate.generate_tool_turn = blocked
    task = asyncio.create_task(runner(step.step_id, state))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stack.service.requests == [] and http.requests == []


@pytest.mark.asyncio
async def test_workspace_does_not_count_arbitrary_shell_exit_zero_as_passing_tests(stack):
    runner, state, step, _ = node(stack, WorkspaceDeveloper(), [[('fs.write', {'path': 'n', 'content': 'source'})],
        [('shell.exec', {'command': 'mock-echo'})], {}])
    with pytest.raises(RuntimeError, match='UNVERIFIED'):
        await runner(step.step_id, state)


@pytest.mark.asyncio
async def test_production_model_setup_enables_declared_tool_calling():
    from app.execution.wiring import build_model_setup
    registry = ModelCompatibilityRegistry()
    runtime = SimpleNamespace(model_registry=registry)
    config = {'AGENTOS_MODELS': json.dumps([{'capabilityId': 'setup-model', 'provider': 'deepseek',
        'models': ['deepseek-test'], 'baseUrl': 'https://model.invalid/v1'}])}
    setup = build_model_setup(runtime, environment=config)
    try:
        await setup.start()
        bound = RegisteredModelRuntime(registry=registry, provider='deepseek', model='deepseek-test')
        assert bound.supports_tool_calling
    finally:
        await setup.close()


@pytest.mark.asyncio
async def test_remote_payload_does_not_claim_a_tool_gateway(stack):
    from adapters.resource_execution import build_remote_execution_payload
    runner, _, step, _ = node(stack, GeneralAgent())
    payload = build_remote_execution_payload(context_for(runner, step))
    assert {'toolRuntime', 'tools', 'grantId', 'credential', 'toolGateway'}.isdisjoint(payload)


@pytest.mark.asyncio
async def test_foreign_workspace_grant_is_rejected_by_formal_transport(stack):
    runner, _, step, _ = node(stack, GeneralAgent())
    stack.runtime.workspace_authority.resolve = lambda _: LocalRuntimeAuthorizationRef(workspaceId='one', grantId='grant-two')
    with pytest.raises(RuntimeError):
        await context_for(runner, step).tool_runtime.execute('fs.read', {'path': 'n'}, operation_key='foreign')
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
async def test_tool_decision_and_receipt_replay_without_repeating_model_or_side_effect(stack):
    runner, _, step, http = node(stack, GeneralAgent(), [[('fs.write', {'path': 'n', 'content': 'once'})],
        [('fs.read', {'path': 'n'})], {'answer': 'once'}])
    context = context_for(runner, step)
    first = await AgentToolSession(context).generate_json(prompt='write once', schema=ANSWER)
    requests = len(stack.service.requests)
    second = await AgentToolSession(context).generate_json(prompt='write once', schema=ANSWER)
    assert first == second
    assert len(http.requests) == 3 and len(stack.service.requests) == requests == 2
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
async def test_tool_replay_cannot_change_frozen_arguments(stack):
    runner, _, step, _ = node(stack, GeneralAgent())
    context = context_for(runner, step)
    await context.tool_runtime.execute('fs.write', {'path': 'n', 'content': 'once'}, operation_key='stable')
    with pytest.raises(RuntimeError):
        await context.tool_runtime.execute('fs.write', {'path': 'n', 'content': 'changed'}, operation_key='stable')
    assert stack.service.files['one', 'n'] == 'once' and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_resume_after_precommit_fault_reuses_tool_decisions_and_receipts(stack):
    runner, state, step, http = node(stack, GeneralAgent(), [[('fs.write', {'path': 'n', 'content': 'once'})],
        {'answer': 'once'}])
    def crash(stage):
        if stage == 'after_values':
            raise RuntimeError('simulated crash before node commit')
    runner._fault_hook = crash
    with pytest.raises(RuntimeError, match='simulated crash'):
        await runner(step.step_id, state)
    runner._fault_hook = None
    result = await runner(step.step_id, state)
    assert result['outputRef']
    assert len(http.requests) == 2 and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_retrieval_preserves_existing_search_and_can_autonomously_use_hands(stack):
    from contracts.compiled_acg import EvidenceManifest, EvidenceRule
    class Search:
        calls = []
        async def execute(self, name, arguments, **kwargs):
            self.calls.append(name)
            return SimpleNamespace(text=json.dumps({'ok': True, 'data': {'results': []}}), sources=[], tool_executions=[])
    search = Search()
    stack.tools.delegate.delegate.fallback = search
    stack.tools = AuditedToolRuntime(delegate=stack.tools.delegate, allowed_tools=['knowledge_search', 'web_search'])
    runner, state, step, http = node(stack, ResearchAgent(), [[('fs.read', {'path': 'n'})], {'answer': 'evidence'}])
    step.capability = 'information_retrieval'
    runner.evidence_manifest = EvidenceManifest(rules=(EvidenceRule(
        stepId=step.step_id, evidenceNodeId='retrieval-evidence', access='produce',
        evidenceType='retrieved', source='task-input'),))
    runner.capability_descriptors[step.capability] = ResearchAgent().capability_catalog.get(step.capability)
    await runner(step.step_id, state)
    assert search.calls[0] == 'knowledge_search'
    assert stack.service.requests[0]['capabilityId'] == 'fs.read' and len(http.requests) == 2


@pytest.mark.asyncio
async def test_unknown_tool_name_returns_error_without_invocation(stack):
    runner, state, step, http = node(stack, GeneralAgent(), [[('fake.tool', {})], {'answer': 'unavailable'}])
    await runner(step.step_id, state)
    assert stack.service.requests == []
    assert json.loads(http.requests[1]['messages'][-1]['content'])['error']['code'] == 'TOOL_ARGUMENTS_INVALID'


@pytest.mark.asyncio
async def test_wire_name_collision_fails_before_model_or_tool_dispatch(stack):
    from contracts.tools import ToolDefinition
    runner, _, step, http = node(stack, GeneralAgent())
    context = context_for(runner, step)
    context.tool_runtime.list_tools = lambda: (
        ToolDefinition(name='a.b', source='hands', description='', parameters={}),
        ToolDefinition(name='a__b', source='other', description='', parameters={}))
    with pytest.raises(ValueError, match='unique'):
        await AgentToolSession(context).generate_json(prompt='test', schema=ANSWER)
    assert http.requests == [] and stack.service.requests == []


@pytest.mark.asyncio
async def test_crash_after_hands_side_effect_before_result_wal_uses_service_idempotency(stack):
    runner, _, step, _ = node(stack, GeneralAgent())
    context = context_for(runner, step)
    original = stack.runtime.execution_value_store.put_tool_value
    class SimulatedCrash(BaseException):
        pass
    def crash_before_result(**kwargs):
        if kwargs['key'].endswith(':result'):
            raise SimulatedCrash()
        return original(**kwargs)
    stack.runtime.execution_value_store.put_tool_value = crash_before_result
    with pytest.raises(SimulatedCrash):
        await context.tool_runtime.execute('fs.write', {'path': 'n', 'content': 'once'}, operation_key='crash-window')
    stack.runtime.execution_value_store.put_tool_value = original
    result = await context.tool_runtime.execute('fs.write', {'path': 'n', 'content': 'once'}, operation_key='crash-window')
    assert result.data['status'] == 'completed'
    assert len(stack.service.requests) == 2 and stack.service.execution_count == 1
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0
