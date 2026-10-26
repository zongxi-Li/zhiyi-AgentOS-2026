"""Canonical final identity through the real C2/Native chain, deterministic agent.

This contract regression is deliberately separate from live Provider acceptance.
"""
import hashlib
import sqlite3
import pytest
from httpx import ASGITransport, AsyncClient

from test_agentos_c2_dispatch_http import database, delivery_setup, permitted, endpoint, wait_run
from test_agentos_c2_http import server, PREFIX, HEADERS
from test_agentos_c2_permit_http import ready_resource, trusted_call


def final_delivery_setup(runtime, coordinator):
    delivery_setup(runtime, coordinator)
    from examples.contract_review import WORKFLOW_ID
    definition = runtime.workflow_registry.get(WORKFLOW_ID)
    runtime.workflow_registry.register(definition.model_copy(update={
        'planning_nodes': tuple(n.model_copy(update={'logical_role': 'final_synthesis'}) if n.key == 'step:C' else n for n in definition.planning_nodes),
        'steps': tuple(s.model_copy(update={'logical_role': 'final_synthesis'}) if s.step_id == 'C' else s for s in definition.steps),
    }))


@pytest.mark.parametrize('damage', ['fragment', 'checksum', 'length', 'unsealed'])
def test_c2_canonical_final_manifest_survives_reconstruction(tmp_path, damage):
    database(tmp_path)
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        created, request = permitted(client)
        assert not agent.calls
        trusted_call(client, ready_resource, runtime, created['runId'])
        assert client.post(endpoint(created), json=request).status_code == 202
        assert wait_run(client, created)['status'] == 'completed'
        url = PREFIX + '/runs/' + created['runId'] + '/artifacts'
        artifacts = client.get(url).json()['items']
        final = [a for a in artifacts if a['artifactKey'] == 'final' and a['artifactType'] == 'run_deliverable']
        assert len(final) == 1, artifacts
        final = final[0]
        assert final['sealed'] and final['semanticTaskKey'] == 'step:C'
        assert final['originRunId'] == created['runId'] and final['missionId'] == created['missionId']
        content_url = url + '/' + final['manifestId'] + '/download'
        content = client.get(content_url)
        assert content.status_code == 200
        assert hashlib.sha256(content.content).hexdigest() == final['checksum']
        assert len(content.content) == final['byteLength'] > 0
        workspace = client.get(PREFIX + '/missions/' + created['missionId'] + '/workspace', params={'runId': created['runId']}).json()
        assert any(e.get('contentRef') == final['manifestId'] and e.get('artifactKey') == 'final' for e in workspace['entries'])
        # Run reads conceal another owner's existence with the established 404 contract.
        denied = client.get(content_url, headers={'X-Authenticated-User-Id': 'another-owner'})
        assert denied.status_code == 404 and final['checksum'] not in denied.text
        assert agent.calls == ['A', 'B', 'C']
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        stable = client.get(url).json()['items']
        assert [a['manifestId'] for a in stable if a['artifactKey'] == 'final'] == [final['manifestId']]
        assert client.get(content_url).content == content.content
        assert not agent.calls
        marker = b'CORRUPT-FINAL-MUST-NOT-LEAVE-HTTP'
        with sqlite3.connect(runtime.content_manifest_store.path) as conn:
            if damage == 'fragment':
                conn.execute('UPDATE content_fragments SET content=? WHERE manifest_id=? AND sequence=0', (marker, final['manifestId']))
            elif damage == 'checksum':
                conn.execute('UPDATE content_manifests SET checksum=? WHERE manifest_id=?', ('0' * 64, final['manifestId']))
            elif damage == 'length':
                conn.execute('UPDATE content_manifests SET byte_length=byte_length+1 WHERE manifest_id=?', (final['manifestId'],))
            else:
                conn.execute('UPDATE content_manifests SET sealed=0 WHERE manifest_id=?', (final['manifestId'],))
        async def corrupt_download():
            # Observe actual ASGI response bytes even if an error occurs after
            # HTTP headers were sent; a late generator failure is not rejection.
            async with AsyncClient(transport=ASGITransport(app=client.app, raise_app_exceptions=False), base_url='http://testserver', headers=HEADERS) as observer:
                return await observer.get(content_url)
        rejected = trusted_call(client, corrupt_download)
        # Existing access policy hides unsealed manifests as absent (404).
        expected = 404 if damage == 'unsealed' else 503
        assert rejected.status_code == expected and marker not in rejected.content, (
            f'corrupt final streamed before verification: status={rejected.status_code}, marker_exposed={marker in rejected.content}')
        if damage in {'fragment', 'unsealed'}:
            page = client.get(url + '/' + final['manifestId'] + '/fragments')
            assert page.status_code == expected and marker not in page.content
