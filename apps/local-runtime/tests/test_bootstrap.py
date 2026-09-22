from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from contracts.local_runtime import LocalRuntimeAuthorizationRef, LocalRuntimeCapability
from grants import GrantAuthorizationService
from runtime.errors import AuthorizationError
from runtime.bootstrap import build_grant_store_from_bootstrap, load_grants_bootstrap
from runtime.main import build_runtime_from_environment
from workspace import CanonicalWorkspaceResolver


def _payload(root, *, grants=None):
    now = datetime.now(timezone.utc)
    return {
        "schemaVersion": 1,
        "workspaces": [{"workspaceId": "workspace-main", "root": str(root)}],
        "grants": grants or [
            {
                "grantId": "grant-valid",
                "workspaceId": "workspace-main",
                "capabilities": [capability.value for capability in (
                    LocalRuntimeCapability.FS_READ,
                    LocalRuntimeCapability.FS_LIST,
                    LocalRuntimeCapability.FS_WRITE,
                    LocalRuntimeCapability.FS_PATCH,
                )],
                "createdAt": now.isoformat(),
            },
            {
                "grantId": "grant-revoked",
                "workspaceId": "workspace-main",
                "capabilities": [LocalRuntimeCapability.FS_READ.value],
                "createdAt": now.isoformat(),
                "revoked": True,
            },
            {
                "grantId": "grant-expired",
                "workspaceId": "workspace-main",
                "capabilities": [LocalRuntimeCapability.FS_READ.value],
                "createdAt": (now - timedelta(hours=2)).isoformat(),
                "expiresAt": (now - timedelta(hours=1)).isoformat(),
            },
        ],
    }


def test_bootstrap_loads_multiple_grants_and_preserves_workspace_authority(tmp_path):
    payload = _payload(tmp_path)
    path = tmp_path / "grants.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    bootstrap = load_grants_bootstrap(path)
    store = build_grant_store_from_bootstrap(bootstrap, resolver=CanonicalWorkspaceResolver())
    authorizer = GrantAuthorizationService(store)

    valid = authorizer.authorize(
        LocalRuntimeAuthorizationRef(grantId="grant-valid", workspaceId="workspace-main"),
        LocalRuntimeCapability.FS_READ,
    )
    assert valid.canonical_root == tmp_path.resolve()

    with pytest.raises(AuthorizationError) as revoked:
        authorizer.authorize(
            LocalRuntimeAuthorizationRef(grantId="grant-revoked", workspaceId="workspace-main"),
            LocalRuntimeCapability.FS_READ,
        )
    assert revoked.value.code == "GRANT_REVOKED"

    with pytest.raises(AuthorizationError) as expired:
        authorizer.authorize(
            LocalRuntimeAuthorizationRef(grantId="grant-expired", workspaceId="workspace-main"),
            LocalRuntimeCapability.FS_READ,
        )
    assert expired.value.code == "GRANT_EXPIRED"


@pytest.mark.parametrize("mutation", [
    lambda payload: payload["grants"].append(dict(payload["grants"][0])),
    lambda payload: payload["grants"][0].update({"workspaceId": "missing-workspace"}),
    lambda payload: payload["grants"][0].update({"capabilities": ["process.unsupported"]}),
    lambda payload: payload["grants"][0].update({"createdAt": "not-a-timestamp"}),
    lambda payload: payload["grants"][0].update({"allowedRoot": "C:\\"}),
])
def test_invalid_bootstrap_fails_closed(tmp_path, mutation):
    payload = _payload(tmp_path)
    mutation(payload)
    path = tmp_path / "invalid-grants.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError):
        load_grants_bootstrap(path)


def test_legacy_single_grant_environment_bootstrap_remains_compatible(tmp_path):
    app = build_runtime_from_environment({
        "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_ID": "credential-test",
        "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET": "secret-test",
        "ZHIYI_LOCAL_RUNTIME_WORKSPACE_ID": "workspace-main",
        "ZHIYI_LOCAL_RUNTIME_GRANT_ID": "grant-main",
        "ZHIYI_LOCAL_RUNTIME_WORKSPACE_ROOT": str(tmp_path),
    })
    try:
        assert app.service.running is True
    finally:
        app.service.stop()
