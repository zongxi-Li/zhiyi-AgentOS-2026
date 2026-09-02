from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from components.resource.service import ResourceService
from components.resource.store import SQLiteResourceStore
from contracts.resource import DeploymentTier, ResourceEndpoint, ResourceProfile, ResourceSnapshot, ResourceType


NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def _service() -> ResourceService:
    resources = ResourceService()
    resources.register(
        ResourceProfile(
            resourceId="edge-auth",
            resourceType=ResourceType.WORKER,
            deploymentTier=DeploymentTier.EDGE,
            capabilities=["vision.infer"],
            ownerScope="tenant-a",
            executionEndpoint=ResourceEndpoint(
                protocol="https",
                address="https://edge-auth.example.test/execute",
            ),
        ),
        ResourceSnapshot(resourceId="edge-auth", availableSlots=1, utilization=0.0),
    )
    return resources


def test_issue_credential_returns_secret_once_and_verifies_without_storing_plaintext() -> None:
    resources = _service()

    issued = resources.issue_credential("edge-auth")

    assert issued.resource_id == "edge-auth"
    assert issued.owner_scope == "tenant-a"
    assert len(issued.secret) >= 32
    verified = resources.verify_credential("edge-auth", issued.credential_id, issued.secret)
    assert verified.resource_id == "edge-auth"
    assert verified.owner_scope == "tenant-a"
    assert issued.secret not in repr(verified)


def test_sqlite_credential_survives_restart_without_persisting_plaintext(tmp_path) -> None:
    db_path = tmp_path / "resources.sqlite3"
    first_store = SQLiteResourceStore(db_path)
    first = ResourceService(store=first_store)
    profile_service = _service()
    first.register(profile_service.profile("edge-auth"), profile_service.snapshot("edge-auth").snapshot)
    issued = first.issue_credential("edge-auth")
    first_store.close()

    assert issued.secret.encode() not in db_path.read_bytes()

    second_store = SQLiteResourceStore(db_path)
    second = ResourceService(store=second_store)
    try:
        verified = second.verify_credential("edge-auth", issued.credential_id, issued.secret)
        assert verified.owner_scope == "tenant-a"
    finally:
        second_store.close()


def test_unknown_or_wrong_secret_is_rejected() -> None:
    resources = _service()
    issued = resources.issue_credential("edge-auth")

    with pytest.raises(ValueError, match="credential"):
        resources.verify_credential("edge-auth", "missing", issued.secret)
    with pytest.raises(ValueError, match="credential"):
        resources.verify_credential("edge-auth", issued.credential_id, "wrong-secret")


def test_nonce_can_be_consumed_only_once_until_expiry() -> None:
    resources = _service()
    expires_at = NOW + timedelta(minutes=5)

    assert resources.consume_nonce("edge-auth", "nonce-1", expires_at, now=NOW) is True
    assert resources.consume_nonce("edge-auth", "nonce-1", expires_at, now=NOW) is False
    assert resources.consume_nonce("edge-auth", "nonce-2", NOW - timedelta(seconds=1), now=NOW) is False
