"""S00-04 public commands on temporary production stores and trusted HTTP boundary."""
import asyncio
import time
import threading
from copy import deepcopy
import pytest
from contracts.workflow import WorkflowStatus
from contracts.mission_semantic import run_intent_basis
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from test_mission_semantic_commands import api, create, edit, BODY, HEADERS, finished
from test_mission_semantic_commands import application, _environment
from fastapi.testclient import TestClient


def path(mission, run):
    return f"/agentos/v2/missions/{mission}/runs/{run}/revision"


def pending_mission(api, monkeypatch):
    client, runtime, coordinator, _ = api
    original = coordinator.submit
    async def hold(_):
        return False
    monkeypatch.setattr(coordinator, "submit", hold)
    first = create(client)
    assert edit(client, first['missionId']).status_code == 200
    return client, runtime, coordinator, first, original


def choice(operation='continue', decision='CONTINUE', source=1, target=2):
    return {'operationId': operation, 'sourceRevision': source, 'targetRevision': target, 'decision': decision}


def test_observe_decide_reopen_and_scoped_replay(api, monkeypatch):
    client, runtime, _, first, _ = pending_mission(api, monkeypatch)
    p = path(first['missionId'], first['runId'])
    before = runtime.workflow_store.get_run(first['runId']).model_dump(mode='json')
    observed = client.get(p).json()
    assert (observed['status'], observed['sourceRevision'], observed['targetRevision'], observed['impact']) == ('REVISION_CHANGED', 1, 2, 'NOT_ANALYZED')
    result = client.post(p, json=choice())
    assert result.status_code == 200, result.text
    assert client.post(p, json=choice()).json() == result.json()
    reopened = SQLiteWorkflowStore(runtime.workflow_store.db_path)
    reopened.enable_existing_mission_semantics()
    assert reopened.list_run_revision_decisions(first['missionId'], first['runId'])[0].model_dump(by_alias=True, mode='json') == result.json()
    assert runtime.workflow_store.get_run(first['runId']).model_dump(mode='json') == before
    second = client.post(f"/agentos/v2/missions/{first['missionId']}/runs", json={'sourceRunId': first['runId'], 'clientRequestId':'bad', 'input':{}, 'rerunReason':'manual'})
    assert second.status_code == 409
    # A different active Run freezes the current revision independently.
    from contracts.mission_semantic import SemanticPrincipal
    _, new = runtime.prepare_run(first['missionId'], semantic_principal=SemanticPrincipal(actorId='owner', tenantId='tenant'),
        workflow_id='semantic-test', defer_acg_planning=True)
    other = client.get(path(first['missionId'], new.run_id)).json()
    assert other['status'] == 'CURRENT' and other['decisions'] == []
    assert client.post(path(first['missionId'], new.run_id), json=choice()).status_code == 409


def test_replan_cancel_then_successor_and_retry_after_submit_failure(api, monkeypatch):
    client, runtime, coordinator, first, original = pending_mission(api, monkeypatch)
    p = path(first['missionId'], first['runId'])
    original_basis = run_intent_basis(runtime.workflow_store.get_run(first['runId']))
    receipt = client.post(p, json=choice('replan', 'REQUEST_REPLAN'))
    assert receipt.status_code == 200
    assert client.post(p + '/replan/apply').status_code == 409
    assert client.post(f"/agentos/v2/runs/{first['runId']}/cancel").status_code == 200
    async def unavailable(_):
        raise RuntimeError('submit failed after durable preparation')
    monkeypatch.setattr(coordinator, 'submit', unavailable)
    assert client.post(p + '/replan/apply').status_code == 503
    # Reconstruct the persistence adapter, preserving exact operation and successor.
    store = SQLiteWorkflowStore(runtime.workflow_store.db_path)
    store.enable_existing_mission_semantics()
    monkeypatch.setattr(runtime, 'workflow_store', store)
    monkeypatch.setattr(coordinator, 'submit', original)
    retry = client.post(p + '/replan/apply')
    assert retry.status_code == 202, retry.text
    successor = finished(runtime, retry.json()['runId'])
    assert run_intent_basis(successor).source_revision == 2
    assert successor.execution_state['parentRunId'] == first['runId']
    assert successor.execution_state['missionRevisionDecision'] == receipt.json()
    assert run_intent_basis(store.get_run(first['runId'])) == original_basis
    assert edit(client, first['missionId'], revision=2, operation='later-r3', objective='r3').status_code == 200
    assert client.post(p + '/replan/apply').json() == retry.json()
    assert run_intent_basis(store.get_run(successor.run_id)).source_revision == 2
    assert client.post(p, json=choice('replan', 'REQUEST_REPLAN')).json() == receipt.json()


def test_stale_choice_concurrent_edit_and_superseded_decision(api, monkeypatch):
    client, runtime, _, first, _ = pending_mission(api, monkeypatch)
    p = path(first['missionId'], first['runId'])
    assert client.post(p, json=choice('replan', 'REQUEST_REPLAN')).status_code == 200
    assert client.post(p, json=choice('replan', 'CONTINUE')).status_code == 409
    assert client.post(p, json=choice('continue')).status_code == 200
    assert client.post(f"/agentos/v2/runs/{first['runId']}/cancel").status_code == 200
    assert client.post(p + '/replan/apply').status_code == 409
    assert client.post(p, json=choice('late')).status_code == 409


def test_revision_changes_during_successor_preparation(api, monkeypatch):
    client, runtime, _, first, _ = pending_mission(api, monkeypatch)
    p = path(first['missionId'], first['runId'])
    assert client.post(p, json=choice('replan', 'REQUEST_REPLAN')).status_code == 200
    assert client.post(f"/agentos/v2/runs/{first['runId']}/cancel").status_code == 200
    original = runtime.workflow_store.save_prepared_run_once
    def race(run):
        from contracts.mission_semantic import MissionSemanticOperation
        runtime.workflow_store.commit_semantics(MissionSemanticOperation(missionId=first['missionId'], operationId='race',
            expectedMissionRevision=2, objective='r3', constraints=[], sourceRefs=[], actorId='owner', tenantId='tenant'))
        return original(run)
    monkeypatch.setattr(runtime.workflow_store, 'save_prepared_run_once', race)
    assert client.post(p + '/replan/apply').status_code == 409
    assert len(runtime.workflow_store.list_all_runs()) == 1


def test_source_soft_deleted_during_successor_preparation(api, monkeypatch):
    client, runtime, _, first, _ = pending_mission(api, monkeypatch)
    p = path(first['missionId'], first['runId'])
    assert client.post(p, json=choice('replan', 'REQUEST_REPLAN')).status_code == 200
    assert client.post(f"/agentos/v2/runs/{first['runId']}/cancel").status_code == 200
    original = runtime.workflow_store.save_prepared_run_once
    def race(run):
        from contracts.workflow import RunRecordState
        runtime.workflow_store.set_run_record_state(first['runId'], RunRecordState.DELETED)
        return original(run)
    monkeypatch.setattr(runtime.workflow_store, 'save_prepared_run_once', race)
    assert client.post(p + '/replan/apply').status_code == 409
    assert len(runtime.workflow_store.list_all_runs()) == 1


@pytest.mark.parametrize('change', [ {'sourceRevision': 9}, {'targetRevision': 1}, {'operationId': ' '},
    {'targetRevision': True}, {'actorId': 'forged'}, {'decision':'AUTO_REWRITE'} ])
def test_invalid_and_stale(api, monkeypatch, change):
    client, _, _, first, _ = pending_mission(api, monkeypatch)
    assert client.post(path(first['missionId'], first['runId']), json={**choice(), **change}).status_code in {409,422}


def test_permissions_and_terminal_run(api):
    client, runtime, _, first_agent = api
    first = create(client)
    finished(runtime, first['runId'])
    edit(client, first['missionId'])
    p = path(first['missionId'], first['runId'])
    assert client.post(p, json=choice()).status_code == 409
    headers = {**HEADERS, 'x-authenticated-user-id': 'intruder', 'x-authenticated-user-subject': 'intruder'}
    assert client.get(p, headers=headers).status_code == 403
    assert client.post(p, json=choice(), headers=headers).status_code == 403
    assert client.post(p + '/continue/apply', headers=headers).status_code == 403


def test_active_node_basis_and_input_unchanged(api, monkeypatch):
    client, runtime, _, first, _ = pending_mission(api, monkeypatch)
    run = runtime.workflow_store.get_run(first['runId'])
    run.status = WorkflowStatus.RUNNING
    run.active_step_ids = ['executing-node']
    runtime.workflow_store.save_run(run)
    before = runtime.workflow_store.get_run(run.run_id).model_dump(mode='json')
    p = path(first['missionId'], first['runId'])
    assert client.post(p, json=choice('replan', 'REQUEST_REPLAN')).status_code == 200
    assert client.post(p + '/replan/apply').status_code == 409
    assert runtime.workflow_store.get_run(run.run_id).model_dump(mode='json') == before


def test_real_executing_node_keeps_old_basis_after_decisions(api, monkeypatch):
    client, runtime, _, agent = api
    entered, release = threading.Event(), threading.Event()
    original = agent.run
    async def slow(context):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        return await original(context)
    monkeypatch.setattr(agent, 'run', slow)
    first = create(client)
    try:
        assert entered.wait(5), 'real executor did not enter Agent'
        run = runtime.workflow_store.get_run(first['runId'])
        basis = run_intent_basis(run)
        inputs, blueprint = deepcopy(run.input), deepcopy(run.acg_blueprint)
        plan = deepcopy(run.execution_state.get('taskPlan'))
        assert edit(client, first['missionId']).status_code == 200
        p = path(first['missionId'], first['runId'])
        assert client.post(p, json=choice()).status_code == 200
        assert client.post(p, json=choice('replan', 'REQUEST_REPLAN')).status_code == 200
        assert client.post(p + '/replan/apply').status_code == 409
        current = runtime.workflow_store.get_run(first['runId'])
        assert run_intent_basis(current) == basis
        assert (current.input, current.acg_blueprint, current.execution_state.get('taskPlan')) == (inputs, blueprint, plan)
    finally:
        release.set()
    assert run_intent_basis(finished(runtime, first['runId'])) == basis


def test_failed_decision_insert_rolls_back_and_retries(api, monkeypatch):
    client, runtime, _, first, _ = pending_mission(api, monkeypatch)
    p = path(first['missionId'], first['runId'])
    with runtime.workflow_store._connect() as conn:
        conn.execute("CREATE TRIGGER fail_decision BEFORE INSERT ON mission_revision_decisions BEGIN SELECT RAISE(ABORT, 'injected'); END")
    assert client.post(p, json=choice()).status_code == 503
    assert client.get(p).json()['decisions'] == []
    with runtime.workflow_store._connect() as conn:
        conn.execute('DROP TRIGGER fail_decision')
    assert client.post(p, json=choice()).status_code == 200
    assert len(client.get(p).json()['decisions']) == 1


def test_cancel_coordinator_still_active_defers_successor(api, monkeypatch):
    client, runtime, coordinator, first, _ = pending_mission(api, monkeypatch)
    p = path(first['missionId'], first['runId'])
    assert client.post(p, json=choice('replan', 'REQUEST_REPLAN')).status_code == 200
    assert client.post(f"/agentos/v2/runs/{first['runId']}/cancel").status_code == 200
    monkeypatch.setattr(coordinator, 'is_active', lambda _: True)
    result = client.post(p + '/replan/apply')
    assert result.status_code == 202 and result.json()['status'] == 'WAITING_CANCELLATION'
    assert len(runtime.workflow_store.list_all_runs()) == 1


def test_full_application_restart_restores_request_and_successor(tmp_path, monkeypatch):
    env = {**_environment(tmp_path), 'AGENTOS_MISSION_SEMANTIC_CONVERGENCE':'true',
        'AGENTOS_ALLOW_LEGACY_MISSION_INTENT':'false'}
    SQLiteWorkflowStore(env['AGENTOS_WORKFLOW_DB_PATH'], enable_mission_semantics=True)
    app = application(env)
    with TestClient(app, headers=HEADERS) as client:
        async def hold(_):
            return False
        monkeypatch.setattr(app.state.boundary[1], 'submit', hold)
        first = create(client)
        edit(client, first['missionId'])
        p = path(first['missionId'], first['runId'])
        result = client.post(p, json=choice('restart', 'REQUEST_REPLAN'))
        assert result.status_code == 200
        assert client.post(f"/agentos/v2/runs/{first['runId']}/cancel").status_code == 200
    app = application(env)
    with TestClient(app, headers=HEADERS) as client:
        assert client.get(p).json()['decisions'] == [result.json()]
        applied = client.post(p + '/restart/apply')
        assert applied.status_code == 202, applied.text
        successor_id = applied.json()['runId']
        finished(app.state.boundary[0], successor_id)
    app = application(env)
    with TestClient(app, headers=HEADERS) as client:
        assert client.post(p + '/restart/apply').json()['runId'] == successor_id
        observed = client.get(p).json()
        assert (observed['decisionStatus'], observed['successorRunId']) == ('SUCCESSOR_CREATED', successor_id)


def test_feature_disabled_public_commands_leave_legacy_create_compatible(tmp_path):
    app = application(_environment(tmp_path))
    with TestClient(app, headers=HEADERS) as client:
        body = {k:v for k,v in BODY.items() if k != 'semantics'}
        first = create(client, body)
        run = finished(app.state.boundary[0], first['runId'])
        assert run_intent_basis(run) is None
        p = path(first['missionId'], first['runId'])
        assert client.get(p).status_code == 409
        assert client.post(p, json=choice()).status_code == 409


def test_multiple_active_runs_have_independent_public_revision_choices(api, monkeypatch):
    client, runtime, coordinator, _ = api
    root = create(client)
    finished(runtime, root['runId'])
    async def hold(_):
        return False
    monkeypatch.setattr(coordinator, 'submit', hold)
    def next_run(key):
        response = client.post(f"/agentos/v2/missions/{root['missionId']}/runs", json={
            'sourceRunId':root['runId'], 'clientRequestId':key, 'rerunReason':'manual',
            'input':{'planningMode':'template_preferred', 'deterministicIntent':True}})
        assert response.status_code == 202, response.text
        return response.json()['runId']
    old = next_run('old')
    edit(client, root['missionId'])
    new = next_run('new')
    oldpath, newpath = path(root['missionId'], old), path(root['missionId'], new)
    assert client.get(oldpath).json()['status'] == 'REVISION_CHANGED'
    assert client.get(newpath).json()['status'] == 'CURRENT'
    assert client.post(oldpath, json=choice('scoped')).status_code == 200
    assert client.get(newpath).json()['decisions'] == []
    assert client.post(newpath, json=choice('scoped')).status_code == 409
    assert (run_intent_basis(runtime.workflow_store.get_run(old)).source_revision,
            run_intent_basis(runtime.workflow_store.get_run(new)).source_revision) == (1,2)
