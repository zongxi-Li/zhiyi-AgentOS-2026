"""Authorized process execution service for the Local Runtime."""

from __future__ import annotations

import os
import ntpath
from pathlib import Path
import re
import shutil
import sys

from contracts.local_runtime import (
    ExecutionSecurityProfile,
    LocalRuntimeExecutionEvent,
    LocalRuntimeExecutionLimits,
)

from runtime.errors import LocalRuntimeError
from security.windows_acl import (
    SecurityBoundaryError,
    SecurityBoundaryUnsupported,
    WindowsWorkspaceSecurityLease,
)
from workspace import CanonicalWorkspaceResolver

from .models import ProcessExecutionRequest
from .policy import CommandPolicy, CommandPolicyDecision
from .supervisor import ProcessSupervisor


_SAFE_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_ENV_NAME = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|HMAC|CREDENTIAL|AUTHORIZATION|GRANT|PRIVATE_KEY|API_KEY)",
    re.IGNORECASE,
)
_ENV_ALLOWLIST = {
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "SystemDrive",
    "SystemRoot",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERNAME",
    "USERDOMAIN",
    "PUBLIC",
    "WINDIR",
    "PYTHONIOENCODING",
}


class ProcessExecutionService:
    """Start structured native processes under policy and tree containment."""

    def __init__(
        self,
        resolver: CanonicalWorkspaceResolver,
        *,
        policy: CommandPolicy | None = None,
        supervisor: ProcessSupervisor | None = None,
    ) -> None:
        self.resolver = resolver
        self.policy = policy or CommandPolicy()
        self.supervisor = supervisor or ProcessSupervisor()

    def start(
        self,
        request: ProcessExecutionRequest,
        *,
        root: Path,
        request_id: str,
        invocation_id: str,
        resource_id: str,
        limits: LocalRuntimeExecutionLimits,
    ) -> str:
        if self.policy.is_elevation_attempt(request):
            raise LocalRuntimeError(
                "ELEVATION_NOT_ALLOWED",
                "process elevation is not allowed",
            )
        if self.policy.evaluate(request) is CommandPolicyDecision.DENY:
            raise LocalRuntimeError("COMMAND_DENIED", "command denied by local runtime policy")
        if (
            request.security_profile is ExecutionSecurityProfile.ISOLATED_WORKSPACE
            and self.policy.is_network_install_attempt(request)
        ):
            # AppContainer network denial is not claimed by this PR. Known
            # package/download entrypoints are rejected until an OS network
            # boundary is available; unknown network behavior remains an
            # explicit security limitation.
            raise LocalRuntimeError(
                "NETWORK_DENIED",
                "network-capable package and download commands are not allowed",
            )
        if Path(request.cwd).is_absolute() or ntpath.isabs(request.cwd) or request.cwd.startswith("~"):
            raise LocalRuntimeError("PATH_INVALID", "process working directory must be workspace-relative")
        cwd = self.resolver.resolve(root, request.cwd, must_exist=True)
        if not cwd.target.is_dir():
            raise LocalRuntimeError("PROCESS_CWD_NOT_DIRECTORY", "process working directory is invalid")
        environment = self._build_environment(request.env)
        security: WindowsWorkspaceSecurityLease | None = None
        if request.security_profile is ExecutionSecurityProfile.ISOLATED_WORKSPACE:
            try:
                security = WindowsWorkspaceSecurityLease(
                    cwd.root,
                    runtime_roots=self._runtime_roots(request, environment),
                )
            except SecurityBoundaryUnsupported as exc:
                raise LocalRuntimeError(
                    "ISOLATION_UNSUPPORTED",
                    "isolated workspace execution is unavailable",
                ) from exc
            except SecurityBoundaryError as exc:
                raise LocalRuntimeError(
                    "ISOLATION_SETUP_FAILED",
                    "isolated workspace security boundary could not be created",
                ) from exc
        try:
            return self.supervisor.start(
                request,
                request_id=request_id,
                invocation_id=invocation_id,
                resource_id=resource_id,
                cwd=cwd.target,
                environment=environment,
                limits=limits,
                security=security,
            )
        except RuntimeError as exc:
            if security is not None:
                security.close()
            raise LocalRuntimeError("PROCESS_SUPERVISOR_UNAVAILABLE", "process supervisor is unavailable") from exc
        except SecurityBoundaryError as exc:
            if security is not None:
                security.close()
            raise LocalRuntimeError(
                "ISOLATION_SETUP_FAILED",
                "isolated workspace security boundary could not be created",
            ) from exc

    def events(
        self,
        execution_id: str,
        *,
        request_id: str,
        invocation_id: str,
        resource_id: str,
        after_sequence: int = -1,
        wait_seconds: float = 0.0,
    ) -> tuple[list[LocalRuntimeExecutionEvent], bool, str]:
        actual_request, actual_invocation, actual_resource, _state = self._identity(execution_id)
        if (actual_request, actual_invocation, actual_resource) != (
            request_id,
            invocation_id,
            resource_id,
        ):
            raise LocalRuntimeError("EXECUTION_IDENTITY_MISMATCH", "execution identity does not match request")
        return self.supervisor.events(
            execution_id,
            after_sequence=after_sequence,
            wait_seconds=wait_seconds,
        )

    def cancel(
        self,
        execution_id: str,
        *,
        request_id: str,
        invocation_id: str,
        resource_id: str,
    ) -> str:
        actual_request, actual_invocation, actual_resource, _state = self._identity(execution_id)
        if (actual_request, actual_invocation, actual_resource) != (
            request_id,
            invocation_id,
            resource_id,
        ):
            raise LocalRuntimeError("EXECUTION_IDENTITY_MISMATCH", "execution identity does not match request")
        return self.supervisor.cancel(execution_id)

    def shutdown(self) -> None:
        self.supervisor.shutdown()

    def _identity(self, execution_id: str) -> tuple[str, str, str, str]:
        try:
            return self.supervisor.get_identity(execution_id)
        except KeyError as exc:
            raise LocalRuntimeError("EXECUTION_NOT_FOUND", "execution was not found") from exc

    @staticmethod
    def _build_environment(overrides: dict[str, str]) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {item.upper() for item in _ENV_ALLOWLIST}
            and not _SENSITIVE_ENV_NAME.search(key)
        }
        for key, value in overrides.items():
            if not _SAFE_ENV_NAME.fullmatch(key) or _SENSITIVE_ENV_NAME.search(key):
                raise LocalRuntimeError("ENVIRONMENT_OVERRIDE_DENIED", "environment override is not allowed")
            if key.upper() not in {item.upper() for item in _ENV_ALLOWLIST}:
                raise LocalRuntimeError("ENVIRONMENT_OVERRIDE_DENIED", "environment override is not allowed")
            environment[key] = value
        return environment

    @staticmethod
    def _runtime_roots(
        request: ProcessExecutionRequest,
        environment: dict[str, str],
    ) -> tuple[Path, ...]:
        """Return read-only roots needed to load the selected tool.

        The workspace remains the only writable authority. A restricted
        process must nevertheless load its interpreter and native libraries;
        those installation roots receive temporary read/execute ACLs only.
        """
        roots: set[Path] = set()
        system_root = Path(environment.get("SystemRoot") or os.environ.get("SystemRoot") or "")

        def add_runtime_root(candidate: Path) -> None:
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                return
            # AppContainer already has the Windows system runtime allowance.
            # Modifying protected System32 ACLs would violate the additive,
            # non-ownership-changing boundary.
            if system_root and CanonicalWorkspaceResolver._contained(system_root, resolved):
                return
            roots.add(resolved)

        if request.mode.value == "direct":
            # A shell request is hosted by ComSpec, which is already covered
            # by the Windows system runtime allowance. Only direct Python or
            # other interpreter launches need the venv/base-prefix read/exec
            # ACL; applying inherited ACEs to the whole venv is expensive and
            # unnecessary for a shell-only request.
            for value in (sys.prefix, sys.base_prefix):
                candidate = Path(value)
                if candidate.exists():
                    add_runtime_root(candidate)
            program = request.program or ""
            resolved = Path(program)
            if not resolved.is_absolute():
                located = shutil.which(program, path=environment.get("PATH"))
                if located:
                    resolved = Path(located)
            if resolved.exists():
                add_runtime_root(resolved if resolved.is_file() else resolved.parent)
        else:
            comspec = environment.get("ComSpec") or environment.get("COMSPEC")
            if comspec and Path(comspec).exists():
                add_runtime_root(Path(comspec).parent)
        return tuple(sorted(roots, key=os.fspath))


__all__ = ["ProcessExecutionService"]
