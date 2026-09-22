"""Small AppContainer feasibility probe used by the PR-7 spike.

The probe checks the platform API surface used by the selected AppContainer
launch path. Tool compatibility remains an empirical runtime concern; the
profile is never treated as a generic guarantee for every unpackaged tool.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class AppContainerProbeResult:
    available: bool
    api_surface: tuple[str, ...]
    selected: bool
    reason: str


def probe_appcontainer_support() -> AppContainerProbeResult:
    required = (
        "CreateAppContainerProfile",
        "DeriveAppContainerSidFromAppContainerName",
    )
    if os.name != "nt":
        return AppContainerProbeResult(
            available=False,
            api_surface=(),
            selected=False,
            reason="AppContainer is Windows-only",
        )
    try:
        import ctypes

        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        kernelbase = ctypes.WinDLL("kernelbase", use_last_error=True)
        available = tuple(
            name for name in required if getattr(userenv, name, None) is not None
        )
        if getattr(kernelbase, "CreateAppContainerToken", None) is not None:
            available += ("CreateAppContainerToken",)
    except (OSError, AttributeError):
        available = ()
    return AppContainerProbeResult(
        available=len(available) == len(required) + 1,
        api_surface=available,
        selected=len(available) == len(required) + 1,
        reason=(
            "AppContainer token + additive workspace ACL is selected; tool "
            "compatibility is recorded by the real compatibility matrix"
            if len(available) == len(required) + 1
            else "required AppContainer API surface is unavailable"
        ),
    )


__all__ = ["AppContainerProbeResult", "probe_appcontainer_support"]
