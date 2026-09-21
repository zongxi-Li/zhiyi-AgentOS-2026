"""Stable, sanitized errors emitted by the Local Runtime."""

from __future__ import annotations

from contracts.local_runtime import LocalRuntimeExecutionError


class LocalRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        self.safe_message = message
        super().__init__(message)

    def to_contract(self) -> LocalRuntimeExecutionError:
        return LocalRuntimeExecutionError(
            code=self.code,
            retryable=self.retryable,
            message=self.safe_message,
        )


class RuntimeLifecycleError(LocalRuntimeError):
    def __init__(self) -> None:
        super().__init__("RUNTIME_NOT_RUNNING", "local runtime is not running")


class AuthorizationError(LocalRuntimeError):
    def __init__(self, code: str, message: str = "local runtime authorization denied") -> None:
        super().__init__(code, message)


class PathPolicyError(LocalRuntimeError):
    def __init__(self, code: str = "PATH_OUTSIDE_WORKSPACE") -> None:
        super().__init__(code, "requested path is outside the authorized workspace")


class CapabilityNotImplementedError(LocalRuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "CAPABILITY_NOT_IMPLEMENTED",
            "requested local runtime capability is not implemented",
        )


class FileOperationError(LocalRuntimeError):
    pass


class PatchConflictError(FileOperationError):
    def __init__(self) -> None:
        super().__init__("PATCH_CONFLICT", "file patch could not be applied cleanly")


__all__ = [
    "AuthorizationError",
    "CapabilityNotImplementedError",
    "FileOperationError",
    "LocalRuntimeError",
    "PatchConflictError",
    "PathPolicyError",
    "RuntimeLifecycleError",
]
