import json

import pytest

from contracts.local_runtime import LocalRuntimeCapability
from grants.projected import ProjectedGrantStore
from helpers import make_request
from runtime.errors import AuthorizationError
from runtime.main import build_runtime_from_environment


def publish(path, root, *, revoked=False, caller='caller'):
    path.write_text(json.dumps({'grants': [dict(grantId='dynamic', workspaceId='selected',
        canonicalRoot=str(root), capabilities=['fs.read', 'fs.write', 'shell.exec'],
        allowedCallers=[caller], revoked=revoked)]}), encoding='utf-8')


@pytest.mark.asyncio
async def test_running_python_host_follows_live_workspace_grants_and_revocation(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir(); second.mkdir()
    (first / 'note.txt').write_text('first', encoding='utf-8')
    (second / 'note.txt').write_text('second', encoding='utf-8')
    projection = tmp_path / 'grants.json'
    publish(projection, first)
    app = build_runtime_from_environment({
        'ZHIYI_LOCAL_RUNTIME_CREDENTIAL_ID': 'caller',
        'ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET': 'test-secret-with-at-least-32-characters',
        'ZHIYI_LOCAL_RUNTIME_WORKSPACE_PROJECTION': str(projection),
        'ZHIYI_LOCAL_RUNTIME_CAPABILITIES': 'fs.read,fs.write',
    })
    try:
        async def read():
            return await app.service.execute(make_request(LocalRuntimeCapability.FS_READ,
                {'path': 'note.txt'}, grant_id='dynamic', workspace_id='selected'))
        assert (await read()).output['content'] == 'first'
        publish(projection, second)
        assert (await read()).output['content'] == 'second'
        publish(projection, second, revoked=True)
        assert (await read()).error.code == 'GRANT_REVOKED'
    finally:
        app.service.stop()


def test_projection_cannot_expand_host_capabilities_or_other_callers(tmp_path):
    path = tmp_path / 'grants.json'
    publish(path, tmp_path)
    store = ProjectedGrantStore(path, 'caller', {'fs.read'})
    assert store.get_grant('dynamic').allowed_capabilities == frozenset({'fs.read'})
    publish(path, tmp_path, caller='someone-else')
    assert store.get_grant('dynamic') is None
    path.write_text('broken', encoding='utf-8')
    with pytest.raises(AuthorizationError, match='denied'):
        store.get_grant('dynamic')
