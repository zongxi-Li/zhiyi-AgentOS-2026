from pathlib import Path
from contextlib import nullcontext
import subprocess
import os
from types import SimpleNamespace

import pytest

from app.execution.workspace_authority import WorkspaceAuthority, canonical_directory
from contracts.tools import ToolExecutionAuthorizationLost


def test_any_existing_directory_including_drive_root_can_be_selected(tmp_path):
    outside = tmp_path / 'outside-startup-root'
    outside.mkdir()
    assert canonical_directory(outside)[0] == os.path.normcase(str(outside.resolve()))
    root = Path(tmp_path.anchor)
    assert canonical_directory(root)[0] == os.path.normcase(str(root.resolve()))
    nested = outside / 'nested'
    nested.mkdir()
    assert canonical_directory(nested / '..') == canonical_directory(outside)


def test_directory_links_select_the_real_directory(tmp_path):
    target, link = tmp_path / 'target', tmp_path / 'alias'
    target.mkdir()
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    assert canonical_directory(link) == canonical_directory(target)


def test_missing_non_directory_and_relative_paths_are_rejected(tmp_path):
    file = tmp_path / 'file.txt'
    file.write_text('text', encoding='utf-8')
    with pytest.raises(PermissionError):
        canonical_directory(file)
    with pytest.raises(OSError):
        canonical_directory(tmp_path / 'missing')
    with pytest.raises(PermissionError):
        canonical_directory('relative/path')


@pytest.mark.parametrize('failure', ['deleted', 'revoked'])
def test_frozen_workspace_loss_returns_control_to_host(tmp_path, failure):
    root = tmp_path / 'workspace'
    root.mkdir()
    canonical, identity = canonical_directory(root)
    row = dict(workspace_id='workspace', grant_id='grant', user_id='user',
               tenant_id='tenant', resource_id='resource', canonical_root=canonical,
               root_identity=identity, revoked=False)
    authority = WorkspaceAuthority.__new__(WorkspaceAuthority)
    authority.resource_id = 'resource'
    connection = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: row))
    authority.connect = lambda: nullcontext(connection)
    run = SimpleNamespace(input=dict(authenticatedUserId='user', authenticatedTenantId='tenant',
        workspaceBinding=dict(workspaceId='workspace', grantId='grant', workspaceRoot=canonical)))
    assert authority.resolve(run).grant_id == 'grant'

    if failure == 'deleted':
        root.rmdir()
    else:
        row['revoked'] = True
    with pytest.raises(ToolExecutionAuthorizationLost) as captured:
        authority.resolve(run)
    assert captured.value.code == 'EXECUTION_AUTHORIZATION_LOST'
