"""Fail-closed command policy for the Local Runtime process boundary.

This is an obvious-danger filter, not a shell parser and not a filesystem
sandbox. OS containment and capability-level file operations remain separate
security boundaries.
"""

from __future__ import annotations

from enum import Enum
import re

from .models import ProcessExecutionMode, ProcessExecutionRequest


class CommandPolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


_DANGEROUS_PATTERNS = (
    re.compile(r"\bgit\s+reset\s+[^\r\n]*--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+[^\r\n]*-[^\r\n]*f[^\r\n]*(?:d|x)\b", re.IGNORECASE),
    re.compile(r"\b(?:shutdown|restart-computer|stop-computer|reboot)\b", re.IGNORECASE),
    re.compile(r"\b(?:diskpart|format(?:\.com)?|clear-disk|remove-partition)\b", re.IGNORECASE),
    re.compile(r"\b(?:bcdedit|bootrec)\b", re.IGNORECASE),
    re.compile(r"\breg\s+(?:delete|add)\b", re.IGNORECASE),
)

_ELEVATION_PATTERNS = (
    re.compile(r"(?:^|[\s;&|])runas(?:\.exe)?(?:[\s;&|]|$)", re.IGNORECASE),
    re.compile(r"\b(?:sudo|gsudo|elevate)\b", re.IGNORECASE),
    re.compile(r"\bstart-process\b[^\r\n]*-verb\s+runas\b", re.IGNORECASE),
)

_NETWORK_INSTALL_PATTERNS = (
    re.compile(r"\b(?:pip|pip3)\s+install\b", re.IGNORECASE),
    re.compile(r"\bpython(?:\.exe)?\s+-m\s+pip\s+install\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+(?:install|i|ci)\b", re.IGNORECASE),
    re.compile(r"\b(?:git\s+clone|curl|wget|invoke-webrequest|invoke-restmethod)\b", re.IGNORECASE),
)


class CommandPolicy:
    """Block known destructive command families before process creation."""

    def evaluate(self, request: ProcessExecutionRequest) -> CommandPolicyDecision:
        candidate = self.candidate(request)
        return (
            CommandPolicyDecision.DENY
            if any(pattern.search(candidate) for pattern in _DANGEROUS_PATTERNS)
            else CommandPolicyDecision.ALLOW
        )

    @staticmethod
    def candidate(request: ProcessExecutionRequest) -> str:
        if request.mode is ProcessExecutionMode.DIRECT:
            return " ".join((request.program or "", *request.args))
        return request.command or ""

    def is_elevation_attempt(self, request: ProcessExecutionRequest) -> bool:
        candidate = self.candidate(request)
        return any(pattern.search(candidate) for pattern in _ELEVATION_PATTERNS)

    def is_network_install_attempt(self, request: ProcessExecutionRequest) -> bool:
        candidate = self.candidate(request)
        return any(pattern.search(candidate) for pattern in _NETWORK_INSTALL_PATTERNS)


__all__ = ["CommandPolicy", "CommandPolicyDecision"]
