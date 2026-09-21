"""In-memory credential authority for the Local Runtime HTTP boundary."""

from __future__ import annotations

from threading import RLock


class RuntimeCredentialStore:
    """Keep only the active credential material and support atomic rotation.

    The secret is supplied by the process supervisor/environment. It is never
    accepted from an execution request and is never included in health output.
    """

    def __init__(self, credential_id: str, secret: str) -> None:
        self._lock = RLock()
        self._credential_id = self._required(credential_id, "credential_id")
        self._secret = self._required(secret, "secret")

    @staticmethod
    def _required(value: str, name: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{name} must not be empty")
        return normalized

    def current(self) -> tuple[str, str]:
        with self._lock:
            return self._credential_id, self._secret

    def secret_for(self, credential_id: str) -> str | None:
        with self._lock:
            if credential_id != self._credential_id:
                return None
            return self._secret

    def rotate(self, credential_id: str, secret: str) -> None:
        with self._lock:
            self._credential_id = self._required(credential_id, "credential_id")
            self._secret = self._required(secret, "secret")


__all__ = ["RuntimeCredentialStore"]
