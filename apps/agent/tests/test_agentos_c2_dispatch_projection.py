"""Read-only Dispatch discovery for Workbench; no task creation or private facts."""
import sqlite3

from test_agentos_c2_dispatch_http import database, permitted, endpoint, wait_run
from test_agentos_c2_http import server, PREFIX
from test_agentos_c2_permit_http import ready_resource, trusted_call, snapshot


def test_dispatch_projection_survives_restart_and_is_public_read_only(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        url = PREFIX + '/runs/' + created['runId']
        before = snapshot(runtime)
        control = client.get(url).json()['formalControl']
        assert control['dispatchEnabled'] is True and control['dispatch'] is None
        assert control['permitIssued'] and control['dispatchEligible'] and not control['executionAuthorized']
        assert snapshot(runtime) == before and not agent.calls
        trusted_call(client, ready_resource, runtime, created['runId'])
        ack = client.post(endpoint(created), json=request)
        assert ack.status_code == 202
        assert wait_run(client, created)['status'] == 'completed'
        before = snapshot(runtime)
        receipt = client.get(url).json()['formalControl']['dispatch']
        assert set(receipt) == {'dispatchId', 'runId', 'permitId', 'graphVersion', 'status'}
        assert receipt['dispatchId'] == ack.json()['dispatchId']
        assert snapshot(runtime) == before
    with server(tmp_path, dispatch=False) as (client, runtime, agent):
        control = client.get(url).json()['formalControl']
        assert control['dispatchEnabled'] is False and control['dispatch'] == receipt
        assert not agent.calls


def test_corrupt_dispatch_discovery_fails_closed_without_new_facts(tmp_path, monkeypatch):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        monkeypatch.setattr(runtime._test_coordinator, '_create_permitted_task', lambda c: (_ for _ in ()).throw(RuntimeError('cut')))
        assert client.post(endpoint(created), json=request).status_code == 503
        with sqlite3.connect(runtime.workflow_store.db_path) as conn:
            conn.execute('UPDATE execution_dispatch_commands SET checksum=?', ('0' * 64,))
        before = snapshot(runtime)
        response = client.get(PREFIX + '/runs/' + created['runId'])
        assert response.status_code == 503
        assert 'checksum' not in response.text and 'actor_id' not in response.text
        assert snapshot(runtime) == before and not agent.calls
