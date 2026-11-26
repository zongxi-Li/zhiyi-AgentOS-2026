"""Admitted model memory survives concurrent commits and SQLite restart."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from adapters.agent.tool_session import AgentToolSession
from adapters.model.protocols import StructuredGenerationError
from components.communicator import CommunicatorService
from components.executor.graph import ACGExecutionState
from components.executor.node_runner import ACGNodeRunner
from components.executor.value_store import InMemoryExecutionValueStore, SQLiteExecutionValueStore
from components.memory import MemoryService
from components.memory.store import SQLiteMemoryStore
from contracts.capability import ModelInvocationResponse
from contracts.execution import NodeExecutionPhase, NodeExecutionRecord
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
from adapters.agent.base import AgentOutput, AgentProfile, BaseAgent


ANSWER = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}


class Model:
    provider = 'offline'

    def __init__(self):
        self.requests = []

    async def generate_tool_turn(self, *, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        return ModelInvocationResponse(requestId='offline', provider='offline', model='offline',
            content={'answer': 'Reviewed memory evidence'}, metadata={'finishReason': 'stop'})


class Tools:
    def __init__(self, values):
        self.runtime = SimpleNamespace(execution_value_store=values)

    def list_tools(self):
        return ()


class Reader(BaseAgent):
    def __init__(self, *, crash=False, ready=None, release=None):
        super().__init__(AgentProfile(agentName='reader', domain='general'))
        self.crash, self.ready, self.release = crash, ready, release
        self.inputs = []

    async def run(self, context):
        records = [record.model_dump(by_alias=True, mode='json') for record in context.memory]
        self.inputs.append(records)
        if self.ready is not None:
            self.ready.set()
            await self.release.wait()
        result = await AgentToolSession(context).generate_json(
            prompt=json.dumps({'memory': records}, sort_keys=True), schema=ANSWER)
        if self.crash:
            raise RuntimeError('simulated exit after admitted model turn')
        return AgentOutput(output=result.data, summary='Reviewed')


class Writer(BaseAgent):
    async def run(self, context):
        return AgentOutput(output={'finding': 'atomic lease capacity changed'}, summary='atomic lease capacity changed')


def runner(values, memory, model, reader):
    task = RuntimeMissionRecord(missionId='mission_000000000001', title='Review memory evidence')
    run = RuntimeRunRecord(runId='run-memory', missionId=task.mission_id, workflowId='memory', domain='general', runtimeEngine='acg')
    review = WorkflowStep(stepId='review', name='Review', agentName='reader', goal='Inspect atomic lease capacity',
        input={'memoryPolicy': {'read': True, 'allowedTypes': ['episodic'], 'write': False}}, outputSpec=ANSWER)
    writer = WorkflowStep(stepId='writer', name='Write', agentName='writer')
    return ACGNodeRunner(task=task, run=run,
        workflow=WorkflowDefinition(workflowId='memory', name='Memory review', domain='general', runtimeEngine='acg'),
        steps={'review': review, 'writer': writer}, agents={'review': reader,
            'writer': Writer(AgentProfile(agentName='writer', domain='general'))},
        communicator=CommunicatorService(run_id=run.run_id, mission_id=task.mission_id),
        memory=memory, value_store=values, model_runtime=model, tool_runtime=Tools(values))


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [False, True])
async def test_sqlite_restart_replays_admitted_memory_after_a_parallel_node_commits(tmp_path, monkeypatch, external):
    if external:
        from components.executor import value_store, value_storage
        monkeypatch.setattr(value_store, "store_body", lambda connection, **kwargs:
            value_storage.store_body(connection, threshold=1, **kwargs))
    values = SQLiteExecutionValueStore(db_path=tmp_path / 'values.sqlite3')
    memory_store = SQLiteMemoryStore(db_path=tmp_path / 'memory.sqlite3')
    memory = MemoryService(store=memory_store)
    memory.remember_step_output(run_id='run-memory', step_id='source', output={'finding': 'atomic lease evidence'})
    model = Model()
    ready, release = asyncio.Event(), asyncio.Event()
    first = Reader(crash=True, ready=ready, release=release)
    running = runner(values, memory, model, first)
    state = ACGExecutionState(runId='run-memory')
    reader_task = asyncio.create_task(running('review', state))
    await ready.wait()
    try:
        # This node actually commits its output and memory while review is
        # already admitted; no mock retrieval result or fake success is used.
        await running('writer', state)
    finally:
        release.set()
    with pytest.raises(RuntimeError, match='simulated exit'):
        await reader_task
    assert len(model.requests) == 1
    commit = running._commit_id('run-memory', 'review', 0)
    snapshot = values.get_tool_value(run_id='run-memory', key=commit + ':memory-retrieval')
    wal = values.get_tool_value(run_id='run-memory', key=commit + ':tools:0:model-turn')
    assert snapshot['records'] == first.inputs[0] and len(snapshot['records']) == 1
    assert len(memory.recall_for_step(run_id='run-memory', step_id='review', query='atomic lease')) == 2
    values.close()
    memory_store.close()

    values = SQLiteExecutionValueStore(db_path=tmp_path / 'values.sqlite3')
    memory_store = SQLiteMemoryStore(db_path=tmp_path / 'memory.sqlite3')
    memory = MemoryService(store=memory_store)
    resumed = Reader()
    restored = runner(values, memory, model, resumed)
    try:
        result = await restored('review', ACGExecutionState(runId='run-memory'))
        assert resumed.inputs == first.inputs
        assert len(model.requests) == 1, 'same Attempt must use the admitted model WAL'
        assert values.get_tool_value(run_id='run-memory', key=commit + ':tools:0:model-turn') == wal
        assert result['memoryAccess']['hitRefs'] == snapshot['retrievalEvent']['hitRefs']
        assert result['memoryAccess']['readCount'] == 1

        restored.steps['review'].attempt = 1
        await restored('review', ACGExecutionState(runId='run-memory'))
        assert len(resumed.inputs[-1]) == 2 and len(model.requests) == 2
        next_commit = restored._commit_id('run-memory', 'review', 1)
        assert values.get_tool_value(run_id='run-memory', key=next_commit + ':memory-retrieval')['records'] == resumed.inputs[-1]
    finally:
        values.close()
        memory_store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('changed_memory', [False, True])
async def test_legacy_wal_without_snapshot_keeps_exact_hash_proof_and_never_creates_replacement(changed_memory):
    values, memory, model = InMemoryExecutionValueStore(), MemoryService(), Model()
    first = Reader(crash=True)
    running = runner(values, memory, model, first)
    state = ACGExecutionState(runId='run-memory')
    with pytest.raises(RuntimeError, match='simulated exit'):
        await running('review', state)
    commit = running._commit_id('run-memory', 'review', 0)
    key = commit + ':memory-retrieval'
    frozen = values.get_tool_value(run_id='run-memory', key=key)
    reference = values.put_tool_value(run_id='run-memory', step_id='review', key=key, payload=frozen)
    assert values.delete_references(run_id='run-memory', references=[reference]) == 1
    wal = values.get_tool_value(run_id='run-memory', key=commit + ':tools:0:model-turn')
    if changed_memory:
        memory.remember_step_output(run_id='run-memory', step_id='new-source', output={'finding': 'atomic lease evidence'})
    replay = runner(values, memory, model, Reader())
    if changed_memory:
        with pytest.raises(StructuredGenerationError) as captured:
            await replay('review', state)
        assert captured.value.code == 'TOOL_REPLAY_CONTEXT_CHANGED'
    else:
        await replay('review', state)
    assert len(model.requests) == 1
    assert values.get_tool_value(run_id='run-memory', key=key) is None
    assert values.get_tool_value(run_id='run-memory', key=commit + ':tools:0:model-turn') == wal


@pytest.mark.parametrize('change', ['identity', 'scope', 'type', 'policy', 'schema', 'external_fields'])
def test_memory_snapshot_rejects_wrong_identity_scope_or_type(change):
    values, memory = InMemoryExecutionValueStore(), MemoryService()
    memory.remember_step_output(run_id='run-memory', step_id='source', output={'finding': 'atomic lease evidence'})
    running = runner(values, memory, Model(), Reader())
    step = running.steps['review']
    execution = NodeExecutionRecord(operationId='commit', executionInstanceId='execution', runId='run-memory',
        stepId='review', attemptId='attempt', phase=NodeExecutionPhase.PREPARED)
    policy = running._memory_policy(step.input)
    running._frozen_memory_retrieval(step=step, execution=execution, policy=policy)
    snapshot = values.get_tool_value(run_id='run-memory', key='commit:memory-retrieval')
    if change == 'identity':
        snapshot['identity']['stepId'] = 'another-step'
    elif change == 'scope':
        snapshot['records'][0]['scope'] = 'another-run'
    elif change == 'type':
        snapshot['records'][0]['memoryType'] = 'semantic'
    elif change == 'policy':
        snapshot['policy']['read'] = False
    elif change == 'schema':
        snapshot['schemaVersion'] = True
    else:
        snapshot['request'] = {'invocationId': 'commit:tools:0:call:0'}
    corrupt = InMemoryExecutionValueStore()
    corrupt.put_tool_value(run_id='run-memory', step_id='review', key='commit:memory-retrieval', payload=snapshot)
    running.value_store = corrupt
    with pytest.raises(ValueError, match='memory retrieval snapshot'):
        running._frozen_memory_retrieval(step=step, execution=execution, policy=policy)


def test_admitted_memory_input_requires_the_exact_ledger_step_owner():
    values, memory = InMemoryExecutionValueStore(), MemoryService()
    running = runner(values, memory, Model(), Reader())
    step = running.steps['review']
    execution = NodeExecutionRecord(operationId='commit', executionInstanceId='execution', runId='run-memory',
        stepId='review', attemptId='attempt', phase=NodeExecutionPhase.PREPARED)
    policy = running._memory_policy(step.input)
    running._frozen_memory_retrieval(step=step, execution=execution, policy=policy)
    snapshot = values.get_tool_value(run_id='run-memory', key='commit:memory-retrieval')
    corrupt = InMemoryExecutionValueStore()
    corrupt.put_tool_value(run_id='run-memory', step_id='another-step', key='commit:memory-retrieval', payload=snapshot)
    running.value_store = corrupt
    with pytest.raises(ValueError, match='belongs to step'):
        running._frozen_memory_retrieval(step=step, execution=execution, policy=policy)


def test_expiry_does_not_rewrite_an_already_admitted_memory_snapshot():
    values, memory = InMemoryExecutionValueStore(), MemoryService()
    record = memory.remember_step_output(run_id='run-memory', step_id='source', output={'finding': 'atomic lease evidence'})
    record.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    running = runner(values, memory, Model(), Reader())
    step = running.steps['review']
    execution = NodeExecutionRecord(operationId='commit', executionInstanceId='execution', runId='run-memory',
        stepId='review', attemptId='attempt', phase=NodeExecutionPhase.PREPARED)
    policy = running._memory_policy(step.input)
    admitted, event = running._frozen_memory_retrieval(step=step, execution=execution, policy=policy)
    record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert not memory.recall_for_step(run_id='run-memory', step_id='review', query='atomic lease')
    replayed, replay_event = running._frozen_memory_retrieval(step=step, execution=execution, policy=policy)
    assert replayed == admitted and replay_event == event
