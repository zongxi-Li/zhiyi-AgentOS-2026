from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from capabilities import CapabilityDispatcher, FileSystemPolicy, FilesystemCapabilities
from contracts.local_runtime import LocalRuntimeCapability
from grants import GrantAuthorizationService, InMemoryGrantStore
from process import ProcessExecutionService
from runtime import LocalRuntimeExecutor, LocalRuntimeService
from workspace import CanonicalWorkspaceResolver


@pytest.fixture
def runtime_factory():
    def build(tmp_path: Path, *, capabilities: set[str] | None = None, policy=None):
        resolver = CanonicalWorkspaceResolver()
        store = InMemoryGrantStore()
        workspace = store.issue_workspace(
            workspace_id="workspace_main",
            root=tmp_path,
            resolver=resolver,
        )
        store.issue_grant(
            grant_id="grant_main",
            workspace_id=workspace.workspace_id,
            capabilities=capabilities or {
                capability.value for capability in LocalRuntimeCapability
                if capability is not LocalRuntimeCapability.SHELL_EXEC
            },
            created_at=datetime.now(timezone.utc),
        )
        filesystem = FilesystemCapabilities(resolver, policy=policy)
        executor = LocalRuntimeExecutor(
            resource_id="zhiyi-local-runtime",
            authorizer=GrantAuthorizationService(store),
            dispatcher=CapabilityDispatcher(filesystem),
            process_service=ProcessExecutionService(resolver),
        )
        service = LocalRuntimeService(executor)
        service.start()
        return service, store, resolver

    return build
