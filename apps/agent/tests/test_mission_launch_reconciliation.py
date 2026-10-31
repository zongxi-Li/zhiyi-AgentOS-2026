"""Creation reconciliation against the real SQLite creation/idempotency anchors."""
from test_mission_semantic_commands import api, BODY, HEADERS, create, finished


def reconcile(client, body=None, headers=None):
    return client.post('/agentos/v2/mission-launches/reconcile', json=body or BODY, headers=headers or {})


def test_lookup_is_readonly_and_recovers_a_lost_acceptance(api):
    client, runtime, coordinator, _ = api
    assert reconcile(client).json() == {"status": "NOT_FOUND"}
    accepted = create(client)
    finished(runtime, accepted['runId'])
    async def settle_managed_completion():
        import asyncio
        await asyncio.gather(*tuple(coordinator._tasks.values()))
    client.portal.call(settle_managed_completion)
    before = runtime.workflow_store.get_run(accepted['runId']).model_dump(mode='json')
    receipt = reconcile(client).json()
    assert receipt['status'] == 'CREATED'
    assert (receipt['missionId'], receipt['runId']) == (accepted['missionId'], accepted['runId'])
    assert runtime.workflow_store.get_run(accepted['runId']).model_dump(mode='json') == before
    assert 'legacy goal must not win' not in str(receipt)


def test_mission_created_before_run_preparation_failure_can_be_reconciled(api, monkeypatch):
    client, runtime, _, _ = api
    original = runtime.prepare_run
    monkeypatch.setattr(runtime, 'prepare_run', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('interrupted')))
    assert client.post('/agentos/v2/missions', json=BODY).status_code == 503
    receipt = reconcile(client).json()
    assert receipt['status'] == 'CREATING' and receipt['missionId']
    assert 'runId' not in receipt
    assert reconcile(client, {**BODY, 'title': 'different'}).json()['status'] == 'CONFLICT'
    monkeypatch.setattr(runtime, 'prepare_run', original)
    accepted = create(client)
    assert accepted['missionId'] == receipt['missionId']
    finished(runtime, accepted['runId'])
    assert len(runtime.workflow_store.list_missions().items) == 1


def test_lookup_is_scoped_to_trusted_user_and_tenant_and_returns_no_request(api):
    client, runtime, _, _ = api
    accepted = create(client)
    finished(runtime, accepted['runId'])
    for headers in ({**HEADERS, 'x-authenticated-user-id': 'other', 'x-authenticated-user-subject': 'other'},
                    {**HEADERS, 'x-authenticated-tenant-id': 'other'}):
        assert reconcile(client, headers=headers).json() == {'status': 'NOT_FOUND'}
    conflict = reconcile(client, {**BODY, 'input': {'secret': 'do not disclose'}}).json()
    assert conflict == {'status': 'CONFLICT', 'missionId': accepted['missionId']}


def test_creation_conflict_adds_machine_discriminator_without_changing_legacy_body(api):
    client, runtime, _, _ = api
    accepted = create(client)
    finished(runtime, accepted['runId'])
    conflict = client.post('/agentos/v2/missions', json={**BODY, 'title': 'changed'})
    assert conflict.status_code == 409
    assert conflict.json() == {'detail': 'clientRequestId conflict'}
    assert conflict.headers['x-mission-launch-conflict'] == 'CLIENT_REQUEST_ID_CONFLICT'


def test_semantic_conflict_is_persisted_and_requires_review_without_creating_a_run(api, monkeypatch):
    from app.security.internal_auth import current_trusted_user
    from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal
    client, runtime, _, _ = api
    original = runtime.create_mission

    def independent_initialization(*args, **kwargs):
        task = original(*args, **kwargs)
        actor = current_trusted_user()
        runtime.mission_semantic_service.commit(SemanticPrincipal(actorId=actor.user_id, tenantId=actor.tenant_id),
            MissionSemanticRequest(missionId=task.mission_id, operationId='independent-init', expectedMissionRevision=0,
                                   objective='independent objective', constraints=[], sourceRefs=[]))
        return task

    monkeypatch.setattr(runtime, 'create_mission', independent_initialization)
    conflict = client.post('/agentos/v2/missions', json=BODY)
    assert conflict.status_code == 409, conflict.text
    assert conflict.headers['x-mission-launch-conflict'] == 'MISSION_SEMANTIC_CONFLICT'
    assert reconcile(client).json()['status'] == 'REQUIRES_REVIEW'
    assert len(runtime.workflow_store.list_runs(owner_user_id='owner', owner_tenant_id='tenant').items) == 0


def test_lookup_refuses_requests_without_a_trusted_user(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.agentos_v2 import create_router
    from app.execution.coordinator import RunExecutionCoordinator
    from test_agentos_v2_api import _runtime
    runtime = _runtime(tmp_path)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    with TestClient(app) as client:
        assert reconcile(client).status_code == 401


async def test_trusted_unscoped_user_can_reconcile_their_own_creation(tmp_path):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.api.agentos_v2 import create_router
    from app.execution.coordinator import RunExecutionCoordinator
    from app.security.internal_auth import TrustedUserContext, _trusted_user_context
    from test_agentos_v2_api import _runtime
    runtime = _runtime(tmp_path)
    coordinator = RunExecutionCoordinator(runtime)
    app = FastAPI()
    app.include_router(create_router(runtime, coordinator))
    token = _trusted_user_context.set(TrustedUserContext('owner', 'owner', 'user', None))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            body = {'title': 'unscoped', 'workflowId': 'api-workflow', 'clientRequestId': 'unscoped-operation'}
            accepted = await client.post('/agentos/v2/missions', json=body)
            assert accepted.status_code == 202, accepted.text
            receipt = await client.post('/agentos/v2/mission-launches/reconcile', json=body)
            assert receipt.json()['status'] == 'CREATED'
            assert receipt.json()['runId'] == accepted.json()['runId']
    finally:
        await coordinator.shutdown()
        _trusted_user_context.reset(token)
