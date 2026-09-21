"""HTTP transport for the low-level Local Runtime execution contract.

This adapter is intentionally separate from the existing high-level remote
execution adapter: it carries the Local Runtime request/result contract only.
"""

from __future__ import annotations

import json
import secrets
from time import time
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from contracts.local_runtime import LocalRuntimeExecutionRequest, LocalRuntimeExecutionResult
from contracts.resource_signing import build_resource_signature


class LocalRuntimeCredentialProvider(Protocol):
    def current_signing_credential(self, resource_id: str) -> tuple[str, str]: ...


class LocalRuntimeTransportError(RuntimeError):
    """A transport/protocol failure, distinct from a runtime domain result."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class HttpLocalRuntimeTransport:
    """Sign and send Local Runtime envelopes over the selected HTTP endpoint."""

    def __init__(
        self,
        *,
        resource_id: str,
        address: str,
        credential_provider: LocalRuntimeCredentialProvider,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not resource_id.strip():
            raise ValueError("local runtime resource_id is required")
        parsed = urlsplit(address.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("local runtime address must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("local runtime address must not contain inline credentials")
        if timeout_seconds <= 0:
            raise ValueError("local runtime timeout must be positive")
        if credential_provider is None:
            raise ValueError("local runtime credential provider is required")
        self.resource_id = resource_id.strip()
        self.address = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path or "/v1/executions", parsed.query, parsed.fragment)
        )
        self._path = urlsplit(self.address).path or "/"
        self._health_address = urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))
        self.credential_provider = credential_provider
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def execute(self, request: LocalRuntimeExecutionRequest) -> LocalRuntimeExecutionResult:
        if request.resource_id != self.resource_id:
            raise LocalRuntimeTransportError("RESOURCE_MISMATCH", "request resource does not match transport")
        body = json.dumps(
            request.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = self._signed_headers(body, request.idempotency_key)
        try:
            response = await self._client.post(
                self.address,
                content=body,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LocalRuntimeTransportError(
                "TRANSPORT_UNAVAILABLE", "local runtime request timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise LocalRuntimeTransportError(
                "TRANSPORT_UNAVAILABLE", "local runtime is unavailable", retryable=True
            ) from exc
        payload = self._decode_response(response)
        if response.status_code < 200 or response.status_code >= 300:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = str(error.get("code") or "TRANSPORT_HTTP_ERROR") if isinstance(error, dict) else "TRANSPORT_HTTP_ERROR"
            raise LocalRuntimeTransportError(
                code,
                "local runtime rejected the request",
                retryable=response.status_code >= 500,
            )
        try:
            result = LocalRuntimeExecutionResult.model_validate(payload)
        except Exception as exc:
            raise LocalRuntimeTransportError(
                "TRANSPORT_RESPONSE_INVALID", "local runtime response is invalid"
            ) from exc
        if result.request_id != request.request_id or result.invocation_id != request.invocation_id:
            raise LocalRuntimeTransportError(
                "TRANSPORT_CORRELATION_MISMATCH", "local runtime response correlation mismatch"
            )
        return result

    async def health(self) -> dict[str, Any]:
        """Probe the non-sensitive health endpoint for ResourceService projection."""
        try:
            response = await self._client.get(self._health_address, timeout=self.timeout_seconds)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            raise LocalRuntimeTransportError(
                "TRANSPORT_UNAVAILABLE", "local runtime health is unavailable", retryable=True
            ) from exc
        payload = self._decode_response(response)
        if response.status_code < 200 or response.status_code >= 300:
            raise LocalRuntimeTransportError(
                "TRANSPORT_UNAVAILABLE", "local runtime health is unavailable", retryable=True
            )
        if not isinstance(payload, dict):
            raise LocalRuntimeTransportError(
                "TRANSPORT_RESPONSE_INVALID", "local runtime health response is invalid"
            )
        return payload

    def _signed_headers(self, body: bytes, idempotency_key: str) -> dict[str, str]:
        try:
            credential_id, secret = self.credential_provider.current_signing_credential(self.resource_id)
        except Exception as exc:
            raise LocalRuntimeTransportError(
                "AUTHENTICATION_FAILED", "local runtime credential is unavailable"
            ) from exc
        if not str(credential_id).strip() or not str(secret).strip():
            raise LocalRuntimeTransportError(
                "AUTHENTICATION_FAILED", "local runtime credential is unavailable"
            )
        timestamp = int(time())
        nonce = secrets.token_urlsafe(24)
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Resource-Credential": credential_id,
            "X-Resource-Timestamp": str(timestamp),
            "X-Resource-Nonce": nonce,
            "X-Resource-Signature": build_resource_signature(
                secret,
                method="POST",
                path=self._path,
                timestamp=timestamp,
                nonce=nonce,
                body=body,
            ),
        }

    @staticmethod
    def _decode_response(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise LocalRuntimeTransportError(
                "TRANSPORT_RESPONSE_INVALID", "local runtime response is not valid JSON"
            ) from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = [
    "HttpLocalRuntimeTransport",
    "LocalRuntimeCredentialProvider",
    "LocalRuntimeTransportError",
]
