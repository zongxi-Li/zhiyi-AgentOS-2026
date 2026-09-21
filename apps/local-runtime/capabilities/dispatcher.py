"""Capability handler dispatch inside the Local Runtime process."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping

from contracts.local_runtime import LocalRuntimeCapability

from runtime.errors import CapabilityNotImplementedError
from .filesystem import FilesystemCapabilities


class CapabilityDispatcher:
    """A private handler dispatch table, not an AgentOS capability registry."""

    def __init__(self, filesystem: FilesystemCapabilities) -> None:
        self._filesystem = filesystem

    async def execute(
        self,
        capability: LocalRuntimeCapability,
        *,
        root: Path,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if capability is LocalRuntimeCapability.FS_READ:
            return await asyncio.to_thread(self._filesystem.read, root, arguments)
        if capability is LocalRuntimeCapability.FS_LIST:
            return await asyncio.to_thread(self._filesystem.list, root, arguments)
        if capability is LocalRuntimeCapability.FS_WRITE:
            return await asyncio.to_thread(self._filesystem.write, root, arguments)
        if capability is LocalRuntimeCapability.FS_PATCH:
            return await asyncio.to_thread(self._filesystem.patch, root, arguments)
        raise CapabilityNotImplementedError()


__all__ = ["CapabilityDispatcher"]
