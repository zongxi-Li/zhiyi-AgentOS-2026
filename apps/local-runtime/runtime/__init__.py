"""Independent Windows Local Runtime package."""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "LocalRuntimeExecutor":
        from .executor import LocalRuntimeExecutor

        return LocalRuntimeExecutor
    if name == "InProcessLocalRuntimeTransport":
        from .in_process import InProcessLocalRuntimeTransport

        return InProcessLocalRuntimeTransport
    if name == "LocalRuntimeService":
        from .service import LocalRuntimeService

        return LocalRuntimeService
    if name == "LocalRuntimeHttpApplication":
        from .http_server import LocalRuntimeHttpApplication

        return LocalRuntimeHttpApplication
    if name == "LocalRuntimeIdentity":
        from .identity import LocalRuntimeIdentity

        return LocalRuntimeIdentity
    raise AttributeError(name)

__all__ = [
    "InProcessLocalRuntimeTransport",
    "LocalRuntimeExecutor",
    "LocalRuntimeHttpApplication",
    "LocalRuntimeIdentity",
    "LocalRuntimeService",
]
