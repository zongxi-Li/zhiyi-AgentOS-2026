"""Errors shared by the semantic graph revision boundary."""


class GraphPatchConflictError(ValueError):
    """A semantic revision targets stale or conflicting persisted state."""


__all__ = ["GraphPatchConflictError"]
