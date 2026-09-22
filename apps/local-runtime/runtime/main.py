"""Standalone Local Runtime process entrypoint."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Lock, Thread
import signal
import os
from pathlib import Path

from capabilities import CapabilityDispatcher, FileSystemPolicy, FilesystemCapabilities
from grants import GrantAuthorizationService, InMemoryGrantStore
from process import ProcessExecutionService
from workspace import CanonicalWorkspaceResolver

from runtime.bootstrap import (
    BOOTSTRAP_CAPABILITIES,
    SUPPORTED_CAPABILITIES,
    build_grant_store_from_bootstrap,
    load_grants_bootstrap,
)
from runtime.credentials import RuntimeCredentialStore
from runtime.executor import LocalRuntimeExecutor
from runtime.http_server import LocalRuntimeHttpApplication, LocalRuntimeHttpServer, create_runtime_http_server
from runtime.identity import LocalRuntimeIdentity
from runtime.service import LocalRuntimeService


def _required(values: dict[str, str], name: str) -> str:
    value = str(values.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _configured_capabilities(values: dict[str, str]) -> set[str]:
    configured = str(values.get("ZHIYI_LOCAL_RUNTIME_CAPABILITIES") or "").strip()
    capabilities = (
        {item.strip() for item in configured.split(",") if item.strip()}
        if configured
        else set(BOOTSTRAP_CAPABILITIES)
    )
    if not capabilities or not capabilities <= SUPPORTED_CAPABILITIES:
        raise RuntimeError("local runtime capabilities contain unsupported values")
    return capabilities


def _build_grant_store(values: dict[str, str], resolver: CanonicalWorkspaceResolver) -> InMemoryGrantStore:
    grants_file = str(values.get("ZHIYI_LOCAL_RUNTIME_GRANTS_FILE") or "").strip()
    if grants_file:
        return build_grant_store_from_bootstrap(
            load_grants_bootstrap(grants_file),
            resolver=resolver,
        )

    workspace_id = str(values.get("ZHIYI_LOCAL_RUNTIME_WORKSPACE_ID") or "workspace_main").strip()
    grant_id = str(values.get("ZHIYI_LOCAL_RUNTIME_GRANT_ID") or "grant_main").strip()
    workspace_root = Path(_required(values, "ZHIYI_LOCAL_RUNTIME_WORKSPACE_ROOT"))
    grants = InMemoryGrantStore()
    workspace = grants.issue_workspace(
        workspace_id=workspace_id,
        root=workspace_root,
        resolver=resolver,
    )
    grants.issue_grant(
        grant_id=grant_id,
        workspace_id=workspace.workspace_id,
        capabilities=_configured_capabilities(values),
        created_at=datetime.now(timezone.utc),
    )
    return grants


def build_runtime_from_environment(environ: dict[str, str] | None = None) -> LocalRuntimeHttpApplication:
    values = dict(os.environ if environ is None else environ)
    resource_id = str(values.get("ZHIYI_LOCAL_RUNTIME_RESOURCE_ID") or "zhiyi-local-runtime").strip()
    runtime_id = str(values.get("ZHIYI_LOCAL_RUNTIME_ID") or resource_id).strip()
    credential_id = _required(values, "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_ID")
    secret = _required(values, "ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET")

    resolver = CanonicalWorkspaceResolver()
    grants = _build_grant_store(values, resolver)
    filesystem = FilesystemCapabilities(
        resolver,
        policy=FileSystemPolicy(
            max_read_bytes=int(values.get("ZHIYI_LOCAL_RUNTIME_MAX_READ_BYTES") or 4 * 1024 * 1024),
            max_write_bytes=int(values.get("ZHIYI_LOCAL_RUNTIME_MAX_WRITE_BYTES") or 4 * 1024 * 1024),
            max_list_entries=int(values.get("ZHIYI_LOCAL_RUNTIME_MAX_LIST_ENTRIES") or 10_000),
        ),
    )
    service = LocalRuntimeService(LocalRuntimeExecutor(
        resource_id=resource_id,
        authorizer=GrantAuthorizationService(grants),
        dispatcher=CapabilityDispatcher(filesystem),
        process_service=ProcessExecutionService(resolver),
    ))
    service.start()
    identity = LocalRuntimeIdentity(
        runtime_id=runtime_id,
        resource_id=resource_id,
        version=str(values.get("ZHIYI_LOCAL_RUNTIME_VERSION") or "0.1.0"),
        capabilities=tuple(sorted(_configured_capabilities(values))),
    )
    return LocalRuntimeHttpApplication(
        service=service,
        identity=identity,
        credentials=RuntimeCredentialStore(credential_id, secret),
        max_body_bytes=int(values.get("ZHIYI_LOCAL_RUNTIME_MAX_BODY_BYTES") or 8 * 1024 * 1024),
    )


class RuntimeLifecycle:
    """Own the listener and service shutdown as one idempotent transition."""

    def __init__(self, application: LocalRuntimeHttpApplication, server: LocalRuntimeHttpServer) -> None:
        self.application = application
        self.server = server
        self._shutdown_requested = Event()
        self._shutdown_lock = Lock()
        self._shutdown_complete = False

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()

    def run(self) -> int:
        serve_thread = Thread(
            target=self.server.serve_forever,
            name="zhiyi-local-runtime-http",
            daemon=True,
        )
        serve_thread.start()
        try:
            while serve_thread.is_alive() and not self._shutdown_requested.wait(0.1):
                pass
        finally:
            self.shutdown()
            serve_thread.join(timeout=5)
        return 0

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True
        try:
            self.server.shutdown()
        finally:
            try:
                self.server.server_close()
            finally:
                self.application.service.stop()


def _install_shutdown_handlers(lifecycle: RuntimeLifecycle) -> dict[signal.Signals, object]:
    previous: dict[signal.Signals, object] = {}

    def handle_shutdown(_signum: int, _frame: object) -> None:
        lifecycle.request_shutdown()

    signal_names = ("SIGINT", "SIGTERM", "SIGBREAK")
    for name in signal_names:
        candidate = getattr(signal, name, None)
        if candidate is None:
            continue
        previous[candidate] = signal.getsignal(candidate)
        signal.signal(candidate, handle_shutdown)
    return previous


def _restore_shutdown_handlers(previous: dict[signal.Signals, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def main() -> int:
    application = build_runtime_from_environment()
    host = str(os.environ.get("ZHIYI_LOCAL_RUNTIME_BIND_HOST") or "127.0.0.1").strip()
    port = int(os.environ.get("ZHIYI_LOCAL_RUNTIME_PORT") or 8765)
    server = create_runtime_http_server(application, host=host, port=port)
    lifecycle = RuntimeLifecycle(application, server)
    previous_handlers = _install_shutdown_handlers(lifecycle)
    try:
        return lifecycle.run()
    finally:
        lifecycle.shutdown()
        _restore_shutdown_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RuntimeLifecycle", "build_runtime_from_environment", "main"]
