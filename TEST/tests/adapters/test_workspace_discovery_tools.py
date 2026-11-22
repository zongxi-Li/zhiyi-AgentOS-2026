"""Discovery chooses useful source reads without inheriting a coverage page."""
import json

import pytest

from adapters.agent.tool_session import AgentToolSession
from adapters.tool.audited_runtime import ToolAuthorizationError
from components.planner.workspace_discovery import build_workspace_discovery_plan
from contracts.planning import TaskImplementationBinding
from contracts.acg.semantic_profile import TaskSemanticProfile
from TEST.tests.adapters.test_unified_tools import GeneralAgent, context_for, node, stack as stack
from TEST.tests.adapters.test_workspace_batch_progress import feedbacks
from TEST.tests.adapters.test_workspace_observation_loop import require_read


def prepare_discovery(runner, step):
    require_read(runner, step, path='.', kind='directory')
    runner.run.mission_id = runner.task.mission_id = 'mission_aabbccddeeff'
    profile = TaskSemanticProfile(primaryGoal='Inspect source before planning',
        workspaceObservations=runner.run.execution_state['workspaceObservations'])
    plan = build_workspace_discovery_plan(runner.run.mission_id, profile, runner.run.input)
    step.logical_role = 'workspace_discovery'
    binding = TaskImplementationBinding(planNodeKey=plan.nodes[-1].key, acgNodeId=step.step_id)
    runner.run.execution_state.update(taskPlan=plan.model_dump(mode='json', by_alias=True),
        taskPlanVersion=1, taskBindings=[binding.model_dump(mode='json', by_alias=True)])


def workspace_context(messages):
    for message in reversed(messages):
        if message.get('role') != 'user':
            continue
        try:
            request = json.loads(message['content'])
        except (TypeError, ValueError):
            continue
        if isinstance(request, dict) and 'workspace' in request:
            return request['workspace']['content']
    pytest.fail('The model did not receive its runtime workspace context')


@pytest.mark.asyncio
@pytest.mark.parametrize('discovery_prefix', [True, False])
async def test_understanding_uses_accepted_discovery_identity_to_enforce_read_only_tools(stack, discovery_prefix):
    agent = GeneralAgent()
    runner, state, step, http = node(stack, agent, [{'answer': 'Requirements and discovery questions'}])
    prepare_discovery(runner, step)
    step.capability = 'task_understanding'
    step.logical_role = 'understanding'
    runner.capability_descriptors['task_understanding'] = agent.capability_catalog.get('task_understanding')
    plan = runner.run.execution_state['taskPlan']
    understanding = plan['nodes'][0]
    if not discovery_prefix:
        understanding['metadata']['source'] = 'ordinary_planning'
    runner.run.execution_state['taskBindings'] = [TaskImplementationBinding(
        planNodeKey=understanding['key'], acgNodeId=step.step_id).model_dump(mode='json', by_alias=True)]
    execute = agent.run

    async def inspect(context):
        advertised = {tool.name for tool in context.tool_runtime.list_tools()}
        expected = {'fs.read', 'fs.list'} if discovery_prefix else {
            'fs.read', 'fs.list', 'fs.write', 'fs.patch', 'shell.exec'}
        assert advertised == expected
        if discovery_prefix:
            with pytest.raises(ToolAuthorizationError):
                await context.tool_runtime.execute('shell.exec', {'command': 'mock only'},
                    operation_key='discovery-understanding-shell')
        return await execute(context)

    agent.run = inspect
    result = await runner(step.step_id, state)
    assert result['outputRef'] and len(http.requests) == 1
    assert not stack.service.requests


@pytest.mark.asyncio
@pytest.mark.parametrize('native_request', [False, True])
async def test_discovery_can_read_source_after_listing_without_batch_submission_feedback(stack, monkeypatch, native_request):
    def inspect(payload):
        workspace = workspace_context(payload['messages'])
        assert workspace['assignedDiscovery'] == {'version': 1, 'phase': 'discovery', 'scopeOrigin': 'inferred'}
        assert not {'assignedAcquisition', 'assignedReview'} & workspace.keys()
        instructions = ' '.join(message['content'] for message in payload['messages'] if message['role'] == 'system')
        assert 'adaptive read-only investigation' in instructions
        assert 'A scope suggestion is a proposal for ACG' in instructions
        assert 'one complete directory listing or one bounded batch' not in instructions
        if native_request:
            assert {tool['function']['name'] for tool in payload['tools']} == {'fs__list', 'fs__read'}
        return [('fs.list', {'path': '.'})]

    def read_source(payload):
        assert not feedbacks(payload['messages'])
        assert payload['messages'][-1]['role'] == 'tool'
        return [('fs.read', {'path': 'note.txt'})]

    def submit_findings(payload):
        assert not feedbacks(payload['messages'])
        assert payload['messages'][-1]['role'] == 'tool'
        assert 'file evidence' in payload['messages'][-1]['content']
        return {'answer': 'Observed root and source; proposed scope and remaining questions accompany the evidence.'}

    def no_coverage_page(*args, **kwargs):
        pytest.fail('Discovery does not acquire or receive progress for a fixed coverage page')

    runner, state, step, http = node(stack, GeneralAgent(), [inspect, read_source, submit_findings])
    prepare_discovery(runner, step)
    monkeypatch.setattr('adapters.agent.tool_session.node_workspace_page_progress', no_coverage_page)
    monkeypatch.setattr('adapters.agent.tool_session.node_workspace_acquisition_progress', no_coverage_page)
    if native_request:
        await runner(step.step_id, state)
    else:
        await AgentToolSession(context_for(runner, step)).generate_json(
            prompt='Explore the selected workspace before forming a detailed plan.', schema=step.output_spec)
    assert [request['capabilityId'] for request in stack.service.requests] == ['fs.list', 'fs.read']
    assert len(http.requests) == 3
    records = runner.value_store.list_node_commits(run_id=runner.run.run_id) if native_request else []
    if native_request:
        assert len(records) == 1


@pytest.mark.asyncio
async def test_discovery_protocol_replays_without_new_model_or_hands_requests(stack):
    runner, _, step, http = node(stack, GeneralAgent(), [
        [('fs.list', {'path': '.'})], [('fs.read', {'path': 'note.txt'})], {'answer': 'Discovery findings and unknowns'}])
    prepare_discovery(runner, step)
    context = context_for(runner, step)
    first = await AgentToolSession(context).generate_json(prompt='Ground the formal plan.', schema=step.output_spec)
    replay = await AgentToolSession(context).generate_json(prompt='Ground the formal plan.', schema=step.output_spec)
    assert first == replay and len(http.requests) == 3 and len(stack.service.requests) == 2
    wal = runner.value_store.get_tool_value(run_id=runner.run.run_id, key=context.commit_id + ':tools:0:model-turn')
    assert wal['workspaceContextVersion'] == 3


@pytest.mark.asyncio
async def test_admitted_legacy_discovery_transcript_keeps_its_original_request_identity(stack, monkeypatch):
    runner, _, step, http = node(stack, GeneralAgent(), [
        [('fs.list', {'path': '.'})], {'answer': 'Partial observations for planning'}])
    prepare_discovery(runner, step)
    context = context_for(runner, step)
    original_get = runner.value_store.get_tool_value
    intercepted = False

    def legacy_delivery(**kwargs):
        nonlocal intercepted
        if not intercepted and kwargs['key'] == context.commit_id + ':tools:0:model-turn':
            intercepted = True
            return {'workspaceContextVersion': 1}
        return original_get(**kwargs)

    # Simulate the previous delivery policy before the real immutable model
    # turns are written. Replay then uses those exact requests and outcomes.
    with monkeypatch.context() as legacy:
        legacy.setattr(runner.value_store, 'get_tool_value', legacy_delivery)
        first = await AgentToolSession(context).generate_json(prompt='Ground the formal plan.', schema=step.output_spec)
    replay = await AgentToolSession(context).generate_json(prompt='Ground the formal plan.', schema=step.output_spec)
    assert first == replay and len(http.requests) == 2 and len(stack.service.requests) == 1
    assert 'assignedDiscovery' not in workspace_context(http.requests[0]['messages'])
    wal = original_get(run_id=runner.run.run_id, key=context.commit_id + ':tools:0:model-turn')
    assert wal['workspaceContextVersion'] == 1
