"""Windows security-boundary primitives for Local Runtime execution."""

from .appcontainer import AppContainerProbeResult, probe_appcontainer_support
from .windows_acl import (
    ISOLATED_NETWORK_GUARANTEE,
    SecurityBoundaryError,
    SecurityBoundaryUnsupported,
    WindowsWorkspaceSecurityLease,
)

__all__ = [
    "AppContainerProbeResult",
    "ISOLATED_NETWORK_GUARANTEE",
    "SecurityBoundaryError",
    "SecurityBoundaryUnsupported",
    "WindowsWorkspaceSecurityLease",
    "probe_appcontainer_support",
]
