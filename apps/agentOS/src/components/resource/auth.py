"""Resource-level request signing for remote edge/cloud nodes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac

from contracts.resource_signing import (
    build_resource_signature,
    canonical_resource_request as _canonical_request,
)

from .service import ResourcePlane
from .store import ResourceCredentialRecord


class ResourceRequestExpired(ValueError):
    """The signed request timestamp is outside the accepted clock skew."""


class ResourceRequestReplay(ValueError):
    """The signed request nonce has already been consumed."""


class ResourceRequestNotFound(ValueError):
    """The request names an unknown resource."""


class ResourceRequestInvalid(ValueError):
    """The credential or signature does not match the named resource."""


class ResourceRequestAuthenticator:
    """Verify identity, freshness, integrity, and replay protection."""

    def __init__(
        self,
        plane: ResourcePlane,
        *,
        clock_skew: timedelta = timedelta(minutes=5),
    ) -> None:
        if clock_skew <= timedelta(0):
            raise ValueError("clock skew must be positive")
        self.plane = plane
        self.clock_skew = clock_skew

    def authenticate(
        self,
        *,
        resource_id: str,
        credential_id: str,
        method: str,
        path: str,
        timestamp: int,
        nonce: str,
        signature: str,
        body: bytes,
        now: datetime | None = None,
    ) -> ResourceCredentialRecord:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            record = self.plane.runtime_credential(resource_id)
        except KeyError as error:
            raise ResourceRequestNotFound("resource not found") from error
        if record.credential_id != credential_id:
            raise ResourceRequestInvalid("resource credential is invalid")

        try:
            signed_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ResourceRequestExpired("resource request timestamp is invalid") from error
        if abs((current - signed_at).total_seconds()) > self.clock_skew.total_seconds():
            raise ResourceRequestExpired("resource request timestamp is expired")

        expected = hmac.new(
            self.plane.runtime_credential_hmac_key(resource_id, credential_id),
            _canonical_request(
                method=method,
                path=path,
                timestamp=timestamp,
                nonce=nonce,
                body=body,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ResourceRequestInvalid("resource signature is invalid")

        expires_at = signed_at + self.clock_skew
        if not self.plane.consume_nonce(
            resource_id, nonce, expires_at, now=current
        ):
            raise ResourceRequestReplay("resource request nonce was already used")
        return record


class NodeRequestAuthenticator:
    """Verify signed requests for the Node ledger using the same HMAC contract."""

    def __init__(
        self,
        plane: ResourcePlane,
        *,
        clock_skew: timedelta = timedelta(minutes=5),
    ) -> None:
        if clock_skew <= timedelta(0):
            raise ValueError("clock skew must be positive")
        self.plane = plane
        self.clock_skew = clock_skew

    def authenticate(
        self,
        *,
        node_id: str,
        credential_id: str,
        method: str,
        path: str,
        timestamp: int,
        nonce: str,
        signature: str,
        body: bytes,
        now: datetime | None = None,
    ) -> ResourceCredentialRecord:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            record = self.plane.node_credential(node_id)
        except KeyError as error:
            raise ResourceRequestNotFound("node not found") from error
        if record.credential_id != credential_id:
            raise ResourceRequestInvalid("node credential is invalid")

        try:
            signed_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ResourceRequestExpired("node request timestamp is invalid") from error
        if abs((current - signed_at).total_seconds()) > self.clock_skew.total_seconds():
            raise ResourceRequestExpired("node request timestamp is expired")

        expected = hmac.new(
            self.plane.node_credential_hmac_key(node_id, credential_id),
            _canonical_request(
                method=method,
                path=path,
                timestamp=timestamp,
                nonce=nonce,
                body=body,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ResourceRequestInvalid("node signature is invalid")

        expires_at = signed_at + self.clock_skew
        if not self.plane.consume_node_nonce(node_id, nonce, expires_at, now=current):
            raise ResourceRequestReplay("node request nonce was already used")
        return record
