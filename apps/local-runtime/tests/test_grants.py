from datetime import datetime, timedelta, timezone

import pytest

from contracts.local_runtime import LocalRuntimeAuthorizationRef, LocalRuntimeCapability
from runtime.errors import AuthorizationError


def test_grant_authority_checks_existence_revocation_expiry_workspace_and_capability(
    tmp_path, runtime_factory
):
    service, store, _resolver = runtime_factory(tmp_path, capabilities={"fs.read"})
    authorization = service.executor.authorizer

    with pytest.raises(AuthorizationError) as missing:
        authorization.authorize(
            LocalRuntimeAuthorizationRef(grantId="missing", workspaceId="workspace_main"),
            LocalRuntimeCapability.FS_READ,
        )
    assert missing.value.code == "GRANT_NOT_FOUND"

    store.issue_grant(
        grant_id="revoked",
        workspace_id="workspace_main",
        capabilities={"fs.read"},
        created_at=datetime.now(timezone.utc),
        revoked=True,
    )
    with pytest.raises(AuthorizationError) as revoked:
        authorization.authorize(
            LocalRuntimeAuthorizationRef(grantId="revoked", workspaceId="workspace_main"),
            LocalRuntimeCapability.FS_READ,
        )
    assert revoked.value.code == "GRANT_REVOKED"

    store.issue_grant(
        grant_id="expired",
        workspace_id="workspace_main",
        capabilities={"fs.read"},
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    with pytest.raises(AuthorizationError) as expired:
        authorization.authorize(
            LocalRuntimeAuthorizationRef(grantId="expired", workspaceId="workspace_main"),
            LocalRuntimeCapability.FS_READ,
        )
    assert expired.value.code == "GRANT_EXPIRED"

    with pytest.raises(AuthorizationError) as mismatch:
        authorization.authorize(
            LocalRuntimeAuthorizationRef(grantId="grant_main", workspaceId="other"),
            LocalRuntimeCapability.FS_READ,
        )
    assert mismatch.value.code == "WORKSPACE_MISMATCH"

    with pytest.raises(AuthorizationError) as denied:
        authorization.authorize(
            LocalRuntimeAuthorizationRef(grantId="grant_main", workspaceId="workspace_main"),
            LocalRuntimeCapability.FS_WRITE,
        )
    assert denied.value.code == "CAPABILITY_DENIED"
