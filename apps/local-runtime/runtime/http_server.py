"""HTTP composition root for the independent Local Runtime.

Importing this module does not bind a socket. ``main`` is the only process
entrypoint that creates a listener.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock
from typing import Callable, Mapping

from contracts.local_runtime import (
    LOCAL_RUNTIME_PROTOCOL_VERSION,
    LocalRuntimeExecutionError,
    LocalRuntimeExecutionRequest,
    LocalRuntimeExecutionResult,
)
from contracts.resource_signing import build_resource_signature

from runtime.credentials import RuntimeCredentialStore
from runtime.errors import LocalRuntimeError, RuntimeLifecycleError
from runtime.identity import LocalRuntimeIdentity
from runtime.service import LocalRuntimeService


EXECUTION_PATH = "/v1/executions"
HEALTH_PATH = "/health"


class RuntimeHttpError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 401) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class RuntimeRequestAuthenticator:
    """Validate the existing AgentOS resource HMAC protocol at the host edge."""

    def __init__(
        self,
        credentials: RuntimeCredentialStore,
        *,
        clock_skew: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if clock_skew <= timedelta(0):
            raise ValueError("clock_skew must be positive")
        self.credentials = credentials
        self.clock_skew = clock_skew
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonces: dict[str, datetime] = {}
        self._lock = RLock()

    def authenticate(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        credential_id = self._header(headers, "X-Resource-Credential")
        timestamp_text = self._header(headers, "X-Resource-Timestamp")
        nonce = self._header(headers, "X-Resource-Nonce")
        signature = self._header(headers, "X-Resource-Signature")
        if not credential_id or not timestamp_text or not nonce or not signature:
            raise RuntimeHttpError("AUTHENTICATION_FAILED", "resource authentication failed")
        try:
            timestamp = int(timestamp_text)
            signed_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise RuntimeHttpError("AUTHENTICATION_FAILED", "resource authentication failed") from exc
        now = self.clock().astimezone(timezone.utc)
        if abs((now - signed_at).total_seconds()) > self.clock_skew.total_seconds():
            raise RuntimeHttpError("AUTHENTICATION_FAILED", "resource authentication failed")
        secret = self.credentials.secret_for(credential_id)
        if secret is None:
            raise RuntimeHttpError("AUTHENTICATION_FAILED", "resource authentication failed")
        expected = build_resource_signature(
            secret,
            method=method,
            path=path,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        )
        if not hmac.compare_digest(expected, signature):
            raise RuntimeHttpError("AUTHENTICATION_FAILED", "resource authentication failed")
        expires_at = signed_at + self.clock_skew
        with self._lock:
            self._purge(now)
            if nonce in self._nonces:
                raise RuntimeHttpError(
                    "REPLAY_REJECTED", "resource request replay rejected", status=409
                )
            self._nonces[nonce] = expires_at

    def _purge(self, now: datetime) -> None:
        expired = [nonce for nonce, expires_at in self._nonces.items() if expires_at <= now]
        for nonce in expired:
            self._nonces.pop(nonce, None)

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str:
        for key, value in headers.items():
            if key.lower() == name.lower():
                return str(value).strip()
        return ""


@dataclass(frozen=True)
class RuntimeHttpResponse:
    status: int
    body: bytes


class LocalRuntimeHttpApplication:
    """HTTP endpoint translating signed requests into the runtime service."""

    def __init__(
        self,
        *,
        service: LocalRuntimeService,
        identity: LocalRuntimeIdentity,
        credentials: RuntimeCredentialStore,
        max_body_bytes: int = 8 * 1024 * 1024,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.service = service
        self.identity = identity
        self.max_body_bytes = max_body_bytes
        self.authenticator = RuntimeRequestAuthenticator(credentials, clock=clock)
        self._idempotency: dict[tuple[str, str], tuple[str, LocalRuntimeExecutionResult]] = {}
        self._idempotency_lock = RLock()

    def handle(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> RuntimeHttpResponse:
        request_headers = headers or {}
        if method.upper() == "GET" and path == HEALTH_PATH:
            return self._json(HTTPStatus.OK, self.identity.health_payload(running=self.service.running))
        if method.upper() != "POST" or path != EXECUTION_PATH:
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "local runtime endpoint not found")
        if len(body) > self.max_body_bytes:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "REQUEST_TOO_LARGE", "request body is too large")
        try:
            self.authenticator.authenticate(
                method="POST", path=EXECUTION_PATH, headers=request_headers, body=body
            )
        except RuntimeHttpError as exc:
            return self._error(exc.status, exc.code, exc.message)
        try:
            request = LocalRuntimeExecutionRequest.model_validate_json(body)
        except Exception as exc:
            return self._error(HTTPStatus.BAD_REQUEST, "PROTOCOL_MISMATCH", "request envelope is invalid")
        header_idempotency = RuntimeRequestAuthenticator._header(request_headers, "Idempotency-Key")
        if header_idempotency != request.idempotency_key:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                "PROTOCOL_MISMATCH",
                "idempotency key does not match request envelope",
            )
        return self._execute(request, body)

    def _execute(self, request: LocalRuntimeExecutionRequest, body: bytes) -> RuntimeHttpResponse:
        key = (request.resource_id, request.idempotency_key)
        digest = hashlib.sha256(body).hexdigest()
        # Keep the idempotency decision and execution atomic for the MVP. This
        # deliberately serializes requests in one host process so concurrent
        # retries cannot both miss the cache and mutate the same file.
        with self._idempotency_lock:
            previous = self._idempotency.get(key)
            if previous is not None:
                previous_digest, previous_result = previous
                if previous_digest != digest:
                    conflict = self._failed_result(
                        request,
                        "IDEMPOTENCY_KEY_CONFLICT",
                        "idempotency key was used with a different request",
                    )
                    return self._json(HTTPStatus.OK, conflict.model_dump(by_alias=True, mode="json"))
                correlated = previous_result.model_copy(update={
                    "request_id": request.request_id,
                    "invocation_id": request.invocation_id,
                })
                return self._json(HTTPStatus.OK, correlated.model_dump(by_alias=True, mode="json"))
            try:
                result = asyncio.run(self.service.execute(request))
            except RuntimeLifecycleError as exc:
                result = self._failed_result(request, exc.code, exc.safe_message)
            except Exception:
                result = self._failed_result(request, "EXECUTION_FAILED", "local runtime execution failed")
            self._idempotency[key] = (digest, result)
            return self._json(HTTPStatus.OK, result.model_dump(by_alias=True, mode="json"))

    @staticmethod
    def _failed_result(request: LocalRuntimeExecutionRequest, code: str, message: str) -> LocalRuntimeExecutionResult:
        now = datetime.now(timezone.utc)
        return LocalRuntimeExecutionResult(
            requestId=request.request_id,
            invocationId=request.invocation_id,
            status="failed",
            error=LocalRuntimeExecutionError(code=code, retryable=False, message=message),
            startedAt=now,
            completedAt=now,
        )

    @staticmethod
    def _json(status: int | HTTPStatus, payload: object) -> RuntimeHttpResponse:
        return RuntimeHttpResponse(
            status=int(status),
            body=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )

    @classmethod
    def _error(cls, status: int | HTTPStatus, code: str, message: str) -> RuntimeHttpResponse:
        return cls._json(status, {
            "error": {
                "code": code,
                "retryable": int(status) >= 500,
                "message": message,
            }
        })


class _RuntimeRequestHandler(BaseHTTPRequestHandler):
    server: "LocalRuntimeHttpServer"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length < 0 or content_length > self.server.application.max_body_bytes:
            response = self.server.application._error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "REQUEST_TOO_LARGE", "request body is too large"
            )
        else:
            body = self.rfile.read(content_length) if method == "POST" else b""
            response = self.server.application.handle(
                method=method, path=self.path, headers=self.headers, body=body
            )
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        return


class LocalRuntimeHttpServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], application: LocalRuntimeHttpApplication) -> None:
        self.application = application
        super().__init__(address, _RuntimeRequestHandler)


def create_runtime_http_server(
    application: LocalRuntimeHttpApplication,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> LocalRuntimeHttpServer:
    """Create, but do not start, the host listener."""
    return LocalRuntimeHttpServer((host, port), application)


__all__ = [
    "EXECUTION_PATH",
    "HEALTH_PATH",
    "LocalRuntimeHttpApplication",
    "LocalRuntimeHttpServer",
    "RuntimeCredentialStore",
    "RuntimeRequestAuthenticator",
    "create_runtime_http_server",
]
