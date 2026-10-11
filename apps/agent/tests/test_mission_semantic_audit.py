"""Closing audit: existing public rerun recovery and schema capability boundary."""
import time
from test_mission_semantic_commands import api, create, finished, edit


def test_public_rerun_retries_submission_without_duplicate_or_rebinding(api, monkeypatch):
    client, runtime, coordinator, _ = api
    root = create(client)
    finished(runtime, root['runId'])
    original = coordinator.submit
    async def unavailable(_):
        raise RuntimeError('injected scheduler failure after Run persistence')
    monkeypatch.setattr(coordinator, 'submit', unavailable)
    path = f"/agentos/v2/missions/{root['missionId']}/runs"
    body = {'clientRequestId':'retry-rerun', 'sourceRunId':root['runId'], 'rerunReason':'manual',
        'input':{'planningMode':'template_preferred', 'deterministicIntent':True}}
    assert client.post(path, json=body).status_code == 503
    pending = next(r for r in runtime.workflow_store.list_all_runs() if r.run_id != root['runId'])
    assert pending.status.value == 'pending'
    assert client.post(path, json=body).status_code == 503
    assert len(runtime.workflow_store.list_all_runs()) == 2
    assert edit(client, root['missionId']).status_code == 200
    monkeypatch.setattr(coordinator, 'submit', original)
    response = client.post(path, json=body)
    assert response.status_code == 202 and response.json()['runId'] == pending.run_id
    run = finished(runtime, pending.run_id)
    assert run.execution_state['missionIntentBasis']['sourceRevision'] == 1
    assert len(runtime.workflow_store.list_all_runs()) == 2
    assert client.post(path, json={**body,'input':{'changed':True}}).status_code == 409
    from contracts.workflow import RunRecordState
    runtime.workflow_store.set_run_record_state(run.run_id, RunRecordState.DELETED)
    assert client.post(path, json=body).status_code == 404


def test_v1_without_decisions_keeps_semantics_and_requires_explicit_upgrade(api):
    client, runtime, _, _ = api
    root = create(client)
    finished(runtime, root['runId'])
    with runtime.workflow_store._connect() as conn:
        conn.execute('DROP TABLE mission_revision_decisions')
    runtime.workflow_store.enable_existing_mission_semantics()
    base = f"/agentos/v2/missions/{root['missionId']}"
    assert client.get(base+'/semantics').status_code == 200
    assert edit(client, root['missionId']).status_code == 200
    assert client.get(base+f"/runs/{root['runId']}/revision").status_code == 503
    with runtime.workflow_store._connect() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='mission_revision_decisions'").fetchone() is None


def test_failed_step_successor_retries_submission_preserving_old_basis(api, monkeypatch):
    client, runtime, coordinator, agent = api
    original_agent = agent.run
    async def fail(_):
        raise TimeoutError('injected failed node')
    monkeypatch.setattr(agent,'run',fail)
    from test_planning_loop import Planner, attach
    from contracts.runtime_planning import RuntimePlanningDecision
    attach(runtime, Planner(lambda o, p: RuntimePlanningDecision(observationId=o.fingerprint(),
        action='abort' if o.wake_reason == 'failure' else 'complete' if not o.remaining_step_ids else 'continue',
        reason='explicitly abort the failed execution')))
    root = create(client)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        source = runtime.workflow_store.get_run(root['runId'])
        if source.status.value == 'failed':
            break
        time.sleep(.01)
    assert source.status.value == 'failed'
    assert edit(client, root['missionId']).status_code == 200
    original_submit = coordinator.submit
    async def unavailable(_):
        raise RuntimeError('injected failed scheduling')
    monkeypatch.setattr(coordinator,'submit',unavailable)
    p = f"/agentos/v2/runs/{root['runId']}/steps/A/retry"
    body = {'clientRequestId':'step-retry', 'expectedRuntimeRevision':source.runtime_revision, 'mode':'successor_run'}
    response = client.post(p,json=body)
    assert response.status_code == 503, response.text
    pending = next(r for r in runtime.workflow_store.list_all_runs() if r.run_id != source.run_id)
    assert client.post(p,json=body).status_code == 503
    monkeypatch.setattr(agent,'run',original_agent)
    monkeypatch.setattr(coordinator,'submit',original_submit)
    response = client.post(p,json=body)
    assert response.status_code == 202 and response.json()['runId'] == pending.run_id
    successor = finished(runtime,pending.run_id)
    assert successor.execution_state['missionIntentBasis'] == source.execution_state['missionIntentBasis']
    calls = list(agent.calls)
    assert client.post(p,json=body).json()['runId'] == successor.run_id
    assert agent.calls == calls
    assert len(runtime.workflow_store.list_all_runs()) == 2
