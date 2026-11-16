"""Stable runtime facade; application coordination and assembly live in subpackages."""

from runtime.composition.default_runtime import assemble_default_runtime
from runtime.orchestration.acg_execution import ExecutionRunCancelled, ExecutionStateChanged
from runtime.orchestration.review import ReviewConflictError
from runtime.orchestration.workflow import RuntimeApplication


class ExecutionRuntime(RuntimeApplication):
    """Public runtime type retaining its original import and class identity."""


def build_default_runtime() -> ExecutionRuntime:
    """Assemble the public runtime through the explicit composition boundary."""
    return assemble_default_runtime(ExecutionRuntime)


__all__ = [
    "ExecutionRuntime",
    "ExecutionRunCancelled",
    "ExecutionStateChanged",
    "ReviewConflictError",
    "build_default_runtime",
]
