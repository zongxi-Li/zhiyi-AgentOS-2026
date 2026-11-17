"""Frozen acquisition batches report verified progress within the SDK conversation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from adapters.agent_tools import AgentToolSession
from adapters.hands_http import receipt_checksum
from adapters.model_adapter import StructuredGenerationError
from contracts.execution_evidence import (
    evaluate_run_workspace_observations,
    node_workspace_acquisition_progress,
)
from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan
from test_unified_tools import GeneralAgent, context_for, node, stack as stack
from test_workspace_observation_loop import project_result, require_read


LIST_ROOT = {'operation': 'list', 'path': '.'}
READ_NOTE = {'operation': 'read', 'path': 'note.txt'}


def freeze_batch(runner, step, targets):
    require_read(runner, step, path='.', kind='directory')
    # These fixtures predate the semantic identity contract. Keep the current
    # Run, Mission and accepted plan on the same formal identity for this path.
    runner.run.mission_id = runner.task.mission_id = 'mission_aabbccddeeff'
    step.logical_role = 'workspace_acquisition'
    step.goal = 'Free text is not the authority for the assigned acquisition paths.'
    task = PlannedTask(key='workspace_read:batch', title='Acquire this batch',
        objective='Acquire the frozen batch and report its remaining scope.',
        logicalRole='workspace_acquisition', capabilityRequirements=('information_extraction',),
        constraints=[{'workspaceReview': {'coverageFingerprint': 'a' * 64, 'targets': deepcopy(targets)}}],
        metadata={'source': 'workspace_review', 'taskType': 'workspace_acquisition'})
    plan = TaskPlan(missionId=runner.run.mission_id, planVersion=1, nodes=(task,))
    binding = TaskImplementationBinding(planNodeKey=task.key, acgNodeId=step.step_id)
    runner.run.execution_state.update(taskPlan=plan.model_dump(mode='json', by_alias=True),
        taskPlanVersion=plan.plan_version, taskBindings=[binding.model_dump(mode='json', by_alias=True)])


def feedbacks(messages):
    result = []
    for message in messages:
        if message.get('role') != 'user' or not isinstance(message.get('content'), str):
            continue
        try:
            value = json.loads(message['content'])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('requestType') == 'WorkspaceAcquisitionProgress':
            result.append(value)
    return result


@pytest.mark.asyncio
async def test_complete_listing_batch_prompts_partial_submission_without_claiming_file_read(stack):
    def submit_partial(payload):
        messages = feedbacks(payload['messages'])
        assert len(messages) == 1 and payload['messages'][-1]['role'] == 'user'
        progress = messages[0]['progress']
        assert progress['batchComplete'] is True
        assert progress['verifiedTargets'] == [LIST_ROOT] and progress['remainingTargets'] == []
        assert progress['verifiedListingCount'] == 1 and progress['verifiedReadCount'] == 0
        assert progress['evidenceStatus'] == 'receipt_verified_not_committed'
        assert progress['remainingScope'][0]['complete'] is False
        assert progress['remainingScope'][0]['missingReads'] == ['note.txt']
        assert 'partial' in json.dumps(messages[0]).lower()
        return {'answer': 'Listed this directory; note.txt remains unread for the next ACG batch.'}

    runner, state, step, http = node(stack, GeneralAgent(), [
        [('fs.list', {'path': '.'})], submit_partial])
    freeze_batch(runner, step, [LIST_ROOT])
    result = await runner(step.step_id, state)
    project_result(runner, step, result)

    assert len(http.requests) == 2 and len(stack.service.requests) == 1
    assert evaluate_run_workspace_observations(runner.run, runner.value_store) == (
        'workspace_observation_incomplete:0',)
    assert 'grant-one' not in json.dumps(feedbacks(http.requests[1]['messages']))


@pytest.mark.asyncio
@pytest.mark.parametrize('defect', ['failed', 'partial', 'uncorrelated'])
async def test_unverified_batch_observations_do_not_mark_targets_acquired(stack, defect):
    runner, _, step, _ = node(stack, GeneralAgent())
    freeze_batch(runner, step, [LIST_ROOT])
    if defect == 'failed':
        stack.service.failed = True
    elif defect == 'partial':
        async def partial_response(request):
            response = await stack.service(request)
            payload = response.json()
            if 'receipt' in payload:
                payload['receipt']['output']['partial'] = True
                payload['receipt']['checksum'] = receipt_checksum(payload['receipt'])
            return httpx.Response(response.status_code, json=payload)

        stack.runtime.local_runtime_transport._client._transport = httpx.MockTransport(partial_response)
    context = context_for(runner, step)
    observed = await context.tool_runtime.execute('fs.list', {'path': '.'}, operation_key='batch-observation')
    record = dict(observed.record)
    if defect == 'uncorrelated':
        record['attemptId'] = 'different-attempt'

    progress = node_workspace_acquisition_progress(context, runner.value_store, [record])

    assert progress['batchComplete'] is False
    assert progress['verifiedTargets'] == [] and progress['remainingTargets'] == [LIST_ROOT]
    assert progress['verifiedListingCount'] == progress['verifiedReadCount'] == 0
    assert evaluate_run_workspace_observations(runner.run, runner.value_store) == (
        'workspace_observation_incomplete:0',)


@pytest.mark.asyncio
async def test_repeated_listing_preserves_pending_read_and_deduplicates_identical_feedback(stack):
    def repeat_listing(payload):
        messages = feedbacks(payload['messages'])
        assert len(messages) == 1
        progress = messages[0]['progress']
        assert progress['verifiedTargets'] == [LIST_ROOT] and progress['remainingTargets'] == [READ_NOTE]
        assert progress['batchComplete'] is False and progress['verifiedReadCount'] == 0
        return [('fs.list', {'path': '.'})]

    def acquire_contents(payload):
        # The second identical list is still a directory observation. It does
        # not add another progress message or satisfy the file-read target.
        assert len(feedbacks(payload['messages'])) == 1
        assert payload['messages'][-1]['role'] == 'tool'
        return [('fs.read', {'path': 'note.txt'})]

    def complete(payload):
        messages = feedbacks(payload['messages'])
        assert len(messages) == 2
        assert messages[-1]['progress']['batchComplete'] is True
        assert messages[-1]['progress']['verifiedReadCount'] == 1
        assert messages[-1]['progress']['verifiedListingCount'] == 1
        return {'answer': 'Listed this directory and inspected note.txt.'}

    runner, state, step, http = node(stack, GeneralAgent(), [
        [('fs.list', {'path': '.'})], repeat_listing, acquire_contents, complete])
    freeze_batch(runner, step, [LIST_ROOT, READ_NOTE])
    result = await runner(step.step_id, state)
    project_result(runner, step, result)

    assert len(http.requests) == 4
    assert [request['capabilityId'] for request in stack.service.requests] == ['fs.list', 'fs.list', 'fs.read']
    assert evaluate_run_workspace_observations(runner.run, runner.value_store) == ()


@pytest.mark.asyncio
async def test_progress_transcript_replays_without_new_model_or_tool_calls_and_is_hash_bound(stack):
    runner, _, step, http = node(stack, GeneralAgent(), [
        [('fs.list', {'path': '.'})], {'answer': 'Partial batch submitted to ACG; contents remain unread.'}])
    freeze_batch(runner, step, [LIST_ROOT])
    context = context_for(runner, step)
    first = await AgentToolSession(context).generate_json(prompt='Acquire the frozen batch.', schema=step.output_spec)
    second = await AgentToolSession(context).generate_json(prompt='Acquire the frozen batch.', schema=step.output_spec)

    assert first == second
    assert len(http.requests) == 2 and len(stack.service.requests) == 1
    assert len(feedbacks(http.requests[1]['messages'])) == 1

    # A different frozen scope changes the actual progress transcript. The
    # existing cached model decision must reject that new request identity.
    runner.run.execution_state['taskPlan']['nodes'][0]['constraints'][0]['workspaceReview']['targets'].append(READ_NOTE)
    with pytest.raises(StructuredGenerationError) as captured:
        await AgentToolSession(context).generate_json(prompt='Acquire the frozen batch.', schema=step.output_spec)
    assert captured.value.code == 'TOOL_REPLAY_CONTEXT_CHANGED'
    assert len(http.requests) == 2 and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_legacy_wal_replays_unchanged_and_first_uncached_turn_receives_progress(stack, monkeypatch):
    def interrupted(payload):
        assert not feedbacks(payload['messages'])
        raise asyncio.CancelledError('offline process stopped before completion')

    def continue_with_progress(payload):
        messages = feedbacks(payload['messages'])
        assert len(messages) == 1 and messages[0]['progress']['batchComplete'] is True
        return {'answer': 'Submit the verified directory batch; file contents remain unread.'}

    runner, _, step, http = node(stack, GeneralAgent(), [
        [('fs.list', {'path': '.'})], [('fs.list', {'path': '.'})], interrupted, continue_with_progress])
    freeze_batch(runner, step, [LIST_ROOT])
    context = context_for(runner, step)
    with monkeypatch.context() as legacy:
        legacy.setattr('adapters.agent_tools.node_workspace_acquisition_progress', lambda *_: None)
        with pytest.raises(asyncio.CancelledError):
            await AgentToolSession(context).generate_json(prompt='Acquire the frozen batch.', schema=step.output_spec)

    result = await AgentToolSession(context).generate_json(prompt='Acquire the frozen batch.', schema=step.output_spec)

    assert result.data['answer'].startswith('Submit the verified directory batch')
    assert len(http.requests) == 4 and len(stack.service.requests) == 2
    assert not feedbacks(http.requests[1]['messages'])
    assert len(feedbacks(http.requests[-1]['messages'])) == 1
