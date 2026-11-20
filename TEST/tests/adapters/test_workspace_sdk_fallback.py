"""Legacy JSON models use the shared SDK without an action-count ceiling."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from adapters.tool.audited_runtime import AuditedToolRuntime
from adapters.model.protocols import StructuredGenerationError, StructuredGenerationResult
from components.executor.value_store import SQLiteExecutionValueStore
from packs.workspace import TOOLS, WorkspaceDeveloper


def action(name, **arguments):
    return {'tool': name, 'arguments': arguments, 'summary': name}


class LegacyModel:
    def __init__(self, script):
        self.script = iter(script)
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        candidate = next(self.script)
        if isinstance(candidate, Exception):
            raise candidate
        return StructuredGenerationResult(data=candidate, provider='test', model='legacy-json')


class ReceiptTools:
    def __init__(self, store):
        self.runtime = SimpleNamespace(execution_value_store=store)
        self.effects, self.files = {}, {}

    async def execute(self, name, arguments, *, operation_key, **kwargs):
        if operation_key in self.effects:
            return self.effects[operation_key]
        data = {'status': 'completed'}
        if name == 'write_file':
            self.files[arguments['path']] = arguments['content']
        elif name == 'read_file':
            data['content'] = self.files[arguments['path']]
        elif name == 'run_tests':
            data.update(exitCode=0, stdout='verified by test fixture')
        result = SimpleNamespace(data=data, record={'tool': name, 'status': 'completed'})
        self.effects[operation_key] = result
        return result


@pytest.fixture
def fixture(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / 'values.sqlite3')
    tools = ReceiptTools(store)

    def context(model):
        return SimpleNamespace(
            tool_runtime=AuditedToolRuntime(delegate=tools, allowed_tools=TOOLS), model_runtime=model,
            mission_intent_basis=SimpleNamespace(objective='Implement and verify the full requested task'),
            run=SimpleNamespace(run_id='run-legacy-sdk'),
            step=SimpleNamespace(step_id='developer', name='implement'), commit_id='commit-legacy-sdk',
        )

    yield context, tools
    store.close()


@pytest.mark.parametrize('batch', [False, True])
def test_legacy_actions_pass_old_turn_and_batch_ceilings_and_replay_without_new_effects(fixture, batch):
    context, tools = fixture
    writes = [action('write_file', path=f'file-{index}.py', contentLines=[f'value = {index}'])
              for index in range(40)]
    candidates = [{'actions': writes}] if batch else [{'actions': [write]} for write in writes]
    model = LegacyModel([*candidates, {'actions': [action('run_tests', path='.')]}])
    agent = WorkspaceDeveloper()

    result = asyncio.run(agent.run(context(model)))

    assert len(result.output['workspace_changes']) == 40
    assert result.output['test_results'][-1]['exitCode'] == 0
    assert len(model.calls) == (2 if batch else 41)
    before = dict(tools.effects)
    replay = asyncio.run(agent.run(context(model)))
    assert len(replay.output['workspace_changes']) == 40
    assert tools.effects == before
    assert len(model.calls) == (2 if batch else 41)


def test_legacy_json_corrections_continue_for_distinct_malformed_candidates(fixture):
    context, _ = fixture
    model = LegacyModel([
        *[StructuredGenerationError('MODEL_OUTPUT_INVALID_JSON', 'invalid JSON',
            audit={'candidateFingerprint': f'{index:064x}'}) for index in range(4)],
        {'actions': [action('write_file', path='fixed.py', contentLines=['pass']), action('run_tests', path='.')]},
    ])

    result = asyncio.run(WorkspaceDeveloper().run(context(model)))

    assert result.output['test_results'][-1]['exitCode'] == 0
    assert len(model.calls) == len(result.model_invocations) == 5
    assert 'could not be parsed' in model.calls[-1]['prompt']


@pytest.mark.parametrize('malformed_json', [False, True])
def test_legacy_repeated_invalid_completion_stops_for_no_progress(fixture, malformed_json):
    context, tools = fixture
    candidate = StructuredGenerationError('MODEL_OUTPUT_INVALID_JSON', 'invalid JSON',
        audit={'candidateFingerprint': 'a' * 64}) if malformed_json else {
            'actions': [action('finish')],
        }
    model = LegacyModel([candidate, candidate])

    with pytest.raises(StructuredGenerationError) as caught:
        asyncio.run(WorkspaceDeveloper().run(context(model)))

    assert caught.value.code == 'AGENT_NO_PROGRESS'
    assert len(model.calls) == len(caught.value.audit['modelInvocations']) == 2
    assert tools.effects == {}
