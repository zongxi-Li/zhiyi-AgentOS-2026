"""Consensus workflow-engine contract.

The Appendix I structure reserves a Consensus component.  Implementations may
be registered later; the runtime currently treats a consensus control node as a
dependency join and does not invoke this protocol.
"""

from __future__ import annotations

from typing import Any, Protocol


class ConsensusEngine(Protocol):
    """Reserved interface for future multi-agent consensus strategies."""

    def resolve(self, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        ...


__all__ = ["ConsensusEngine"]
